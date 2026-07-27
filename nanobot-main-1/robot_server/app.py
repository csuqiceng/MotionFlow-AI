"""aiohttp composition root for the local robot-control server.

The server deliberately depends on the public :class:`RobotPlatform` use
cases, never on WebSocket channels or a gateway manager.  Agent communication
is added as a runtime adapter in a later migration stage.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from ai_runtime.engine_contract import AgentEngine, AgentRequest
from nanobot.config.loader import load_config
from robot_platform import LibraryExecutionRegistry, RobotPlatform, configure_robot_runtime
from robot_platform import (
    _PENDING_PLAN_STORE as _DEFAULT_PENDING_PLAN_STORE,
)
from robot_platform import (
    _SESSION_GATE_STORE as _DEFAULT_SESSION_GATE_STORE,
)
from robot_platform.models import ControllerCapabilities
from robot_server.audit_api import RobotAuditService
from robot_server.command_management import RobotCommandManagementService
from robot_server.flow_management import RobotFlowManagementService
from robot_server.execution_api import RobotExecutionService
from robot_server.identity_api import RobotIdentityService
from robot_server.library_api import RobotLibraryService
from robot_server.library_transfer import RobotLibraryTransferService
from robot_server.position_maintenance import RobotPositionMaintenanceService
from robot_server.product_profile import ProductProfileService
from robot_server.request_context import bind_session_key, current_session_key
from robot_server.robot_api import RobotOperationService
from robot_server.settings_api import LocalSettingsService
from robot_server.automations_api import LocalAutomationService
from robot_server.apps_api import LocalAppsService
from robot_server.file_preview_api import file_preview
from robot_server.media_api import LocalMediaService
from robot_server.ui_state_api import LocalUiStateService
from robot_server.websocket_frames import webui_frame_for_runtime_event
from robot_server.webui_compat import legacy_webui_websocket
from robot_server.voice.aliyun_realtime_asr import RealtimeAsrError, probe_bailian_realtime_asr

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(frozen=True)
class RobotServerConfig:
    """Local server configuration.

    ``access_token`` is optional only for loopback desktop deployments.  A
    non-loopback process must set it before the process is started; the CLI
    enforces that rule as a second line of defence.
    """

    access_token: str = ""
    static_dist_path: Path | None = None
    runtime_name: str = "robot-server"
    agent_runtime: AgentEngine | None = None
    deployment_config_path: Path | None = None
    robot_data_dir: Path | None = None
    execution_registry: LibraryExecutionRegistry | None = None
    # A host-only, read-only probe used by the login diagnostics.  Production
    # uses ``probe_product_controller``; the hook keeps the HTTP layer vendor
    # neutral and makes the contract testable without controller hardware.
    controller_probe: Callable[[str], dict[str, object]] | None = None


ROBOT_PLATFORM_KEY: web.AppKey[RobotPlatform] = web.AppKey("robot_platform", RobotPlatform)
ROBOT_SERVER_CONFIG_KEY: web.AppKey[RobotServerConfig] = web.AppKey(
    "robot_server_config", RobotServerConfig
)
ROBOT_OPERATION_SERVICE_KEY: web.AppKey[RobotOperationService] = web.AppKey(
    "robot_operation_service", RobotOperationService
)
ROBOT_LIBRARY_SERVICE_KEY: web.AppKey[RobotLibraryService] = web.AppKey(
    "robot_library_service", RobotLibraryService
)
ROBOT_IDENTITY_SERVICE_KEY: web.AppKey[RobotIdentityService] = web.AppKey(
    "robot_identity_service", RobotIdentityService
)
ROBOT_COMMAND_MANAGEMENT_KEY: web.AppKey[RobotCommandManagementService] = web.AppKey(
    "robot_command_management", RobotCommandManagementService
)
ROBOT_FLOW_MANAGEMENT_KEY: web.AppKey[RobotFlowManagementService] = web.AppKey(
    "robot_flow_management", RobotFlowManagementService
)
ROBOT_AUDIT_SERVICE_KEY: web.AppKey[RobotAuditService] = web.AppKey(
    "robot_audit_service", RobotAuditService
)
ROBOT_LIBRARY_TRANSFER_KEY: web.AppKey[RobotLibraryTransferService] = web.AppKey(
    "robot_library_transfer", RobotLibraryTransferService
)
ROBOT_POSITION_MAINTENANCE_KEY: web.AppKey[RobotPositionMaintenanceService] = web.AppKey(
    "robot_position_maintenance", RobotPositionMaintenanceService
)
ROBOT_EXECUTION_SERVICE_KEY: web.AppKey[RobotExecutionService] = web.AppKey(
    "robot_execution_service", RobotExecutionService
)
PRODUCT_PROFILE_SERVICE_KEY: web.AppKey[ProductProfileService] = web.AppKey(
    "product_profile_service", ProductProfileService
)
LOCAL_UI_STATE_SERVICE_KEY: web.AppKey[LocalUiStateService] = web.AppKey(
    "local_ui_state_service", LocalUiStateService
)
LOCAL_SETTINGS_SERVICE_KEY: web.AppKey[LocalSettingsService] = web.AppKey(
    "local_settings_service", LocalSettingsService
)
LOCAL_AUTOMATION_SERVICE_KEY: web.AppKey[LocalAutomationService] = web.AppKey(
    "local_automation_service", LocalAutomationService
)
LOCAL_APPS_SERVICE_KEY: web.AppKey[LocalAppsService] = web.AppKey(
    "local_apps_service", LocalAppsService
)
LOCAL_MEDIA_SERVICE_KEY: web.AppKey[LocalMediaService] = web.AppKey(
    "local_media_service", LocalMediaService
)
AGENT_RUNTIME_KEY: web.AppKey[AgentEngine | None] = web.AppKey("agent_runtime", object)


def create_robot_server_app(
    *,
    platform: RobotPlatform | None = None,
    config: RobotServerConfig | None = None,
) -> web.Application:
    """Create the single-process robot server application.

    State-changing routes call the same ``RobotPlatform`` safety boundary as
    AI tools; the server owns only HTTP parsing and pending-plan lifecycle.
    """

    server_config = config or RobotServerConfig()
    runtime_data_dir = server_config.robot_data_dir or _default_robot_data_dir()
    configure_robot_runtime(
        data_dir=runtime_data_dir,
        session_key_provider=current_session_key,
    )
    robot_platform = platform or RobotPlatform()
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app[ROBOT_PLATFORM_KEY] = robot_platform
    app[ROBOT_SERVER_CONFIG_KEY] = server_config
    # The current low-level safety gate verifies these process-local stores.
    # Sharing them during migration preserves the existing plan/confirm proof;
    # their ownership moves into the platform backend in the final cleanup.
    operation_service = RobotOperationService(
        platform=robot_platform,
        pending_plans=_DEFAULT_PENDING_PLAN_STORE,
        session_gates=_DEFAULT_SESSION_GATE_STORE,
    )
    app[ROBOT_OPERATION_SERVICE_KEY] = operation_service
    app[ROBOT_LIBRARY_SERVICE_KEY] = RobotLibraryService(runtime_data_dir)
    app[ROBOT_IDENTITY_SERVICE_KEY] = RobotIdentityService(runtime_data_dir)
    app[ROBOT_COMMAND_MANAGEMENT_KEY] = RobotCommandManagementService(
        runtime_data_dir, app[ROBOT_IDENTITY_SERVICE_KEY]
    )
    app[ROBOT_FLOW_MANAGEMENT_KEY] = RobotFlowManagementService(
        runtime_data_dir, app[ROBOT_IDENTITY_SERVICE_KEY]
    )
    app[ROBOT_AUDIT_SERVICE_KEY] = RobotAuditService(
        runtime_data_dir, app[ROBOT_IDENTITY_SERVICE_KEY]
    )
    app[ROBOT_LIBRARY_TRANSFER_KEY] = RobotLibraryTransferService(
        runtime_data_dir, app[ROBOT_IDENTITY_SERVICE_KEY]
    )
    app[ROBOT_POSITION_MAINTENANCE_KEY] = RobotPositionMaintenanceService(
        runtime_data_dir, app[ROBOT_IDENTITY_SERVICE_KEY]
    )
    app[ROBOT_EXECUTION_SERVICE_KEY] = RobotExecutionService(
        runtime_data_dir,
        app[ROBOT_IDENTITY_SERVICE_KEY],
        robot_platform,
        registry=server_config.execution_registry,
    )
    app[PRODUCT_PROFILE_SERVICE_KEY] = ProductProfileService(
        runtime_data_dir, app[ROBOT_IDENTITY_SERVICE_KEY]
    )
    app[AGENT_RUNTIME_KEY] = server_config.agent_runtime
    app[LOCAL_UI_STATE_SERVICE_KEY] = LocalUiStateService(
        runtime_data_dir, app[ROBOT_IDENTITY_SERVICE_KEY], server_config.agent_runtime
    )
    app[LOCAL_SETTINGS_SERVICE_KEY] = LocalSettingsService()
    app[LOCAL_AUTOMATION_SERVICE_KEY] = LocalAutomationService(server_config.agent_runtime)
    app[LOCAL_APPS_SERVICE_KEY] = LocalAppsService()
    app[LOCAL_MEDIA_SERVICE_KEY] = LocalMediaService()

    @web.middleware
    async def local_auth(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]) -> web.StreamResponse:
        if request.path == "/health":
            return await handler(request)
        token = server_config.access_token.strip()
        if token:
            supplied = request.headers.get("Authorization", "")
            if not supplied.startswith("Bearer ") or not hmac.compare_digest(
                supplied[7:], token
            ):
                return web.json_response({"error": "unauthorized"}, status=401)
        elif request.remote not in {"127.0.0.1", "::1", None}:
            return web.json_response(
                {"error": "access token required for non-loopback clients"}, status=403
            )
        return await handler(request)

    app.middlewares.append(local_auth)
    app.router.add_get("/health", _health)
    app.router.add_get("/api/bootstrap", _bootstrap)
    # Compatibility endpoints consumed by the retained React WebUI.  They
    # translate its bootstrap/login handshake to this single-process server;
    # no gateway or channel manager is reintroduced.
    app.router.add_get("/webui/bootstrap", _webui_bootstrap)
    app.router.add_get("/webui", _webui_socket)
    app.router.add_get("/api/auth/login", _webui_login)
    app.router.add_get("/api/auth/logout", _webui_logout)
    app.router.add_get("/api/login/preflight", _webui_login_preflight)
    app.router.add_get("/api/media/{signature}/{payload}", _media)
    app.router.add_get("/api/sessions", _ui_sessions)
    app.router.add_get("/api/sessions/{key}/webui-thread", _ui_session_thread)
    app.router.add_get("/api/sessions/{key}/file-preview", _ui_file_preview)
    app.router.add_post("/api/sessions/{key}/delete", _ui_delete_session)
    app.router.add_get("/api/webui/sidebar-state", _ui_sidebar_state)
    app.router.add_post("/api/webui/sidebar-state", _ui_update_sidebar_state)
    app.router.add_get("/api/webui/sidebar-state/update", _ui_update_sidebar_state)
    app.router.add_get("/api/webui/skills", _ui_skills)
    app.router.add_get("/api/webui/skills/{name}", _ui_skill_detail)
    app.router.add_get("/api/workspaces", _ui_workspaces)
    app.router.add_get("/api/commands", _ui_commands)
    app.router.add_get("/api/sessions/{key}/automations", _session_automations)
    app.router.add_get("/api/webui/automations", _automations)
    app.router.add_get("/api/webui/automations/enable", _automation_enable)
    app.router.add_get("/api/webui/automations/disable", _automation_disable)
    app.router.add_get("/api/webui/automations/delete", _automation_delete)
    app.router.add_get("/api/webui/automations/run", _automation_run)
    app.router.add_get("/api/webui/automations/update", _automation_update)
    app.router.add_get("/api/settings", _settings)
    app.router.add_get("/api/settings/usage", _settings_usage)
    app.router.add_get("/api/settings/version-check", _settings_version_check)
    app.router.add_get("/api/settings/web-search/update", _settings_web_search_update)
    app.router.add_get("/api/settings/network-safety/update", _settings_network_safety_update)
    app.router.add_get("/api/settings/image-generation/update", _settings_image_generation_update)
    app.router.add_get("/api/settings/transcription/update", _settings_transcription_update)
    app.router.add_get("/api/settings/cli-apps", _cli_apps)
    app.router.add_get("/api/settings/cli-apps/install", _cli_apps_install)
    app.router.add_get("/api/settings/cli-apps/update", _cli_apps_update)
    app.router.add_get("/api/settings/cli-apps/uninstall", _cli_apps_uninstall)
    app.router.add_get("/api/settings/cli-apps/test", _cli_apps_test)
    app.router.add_get("/api/settings/mcp-presets", _mcp_presets)
    app.router.add_get("/api/settings/mcp-presets/enable", _mcp_enable)
    app.router.add_get("/api/settings/mcp-presets/remove", _mcp_remove)
    app.router.add_get("/api/settings/mcp-presets/test", _mcp_test)
    app.router.add_get("/api/settings/mcp-presets/custom", _mcp_custom)
    app.router.add_get("/api/settings/mcp-presets/import", _mcp_import)
    app.router.add_get("/api/settings/mcp-presets/tools", _mcp_tools)
    app.router.add_get("/api/robot/status", _robot_status)
    app.router.add_post("/api/robot/plans", _robot_plan)
    app.router.add_post("/api/robot/plans/{plan_id}/confirm", _robot_confirm)
    app.router.add_post("/api/robot/plans/{plan_id}/execute", _robot_execute)
    app.router.add_post("/api/robot/flow-pending-plan", _robot_flow_plan)
    app.router.add_post("/api/robot/flow-confirm", _robot_flow_confirm)
    app.router.add_post("/api/robot/flow-execute", _robot_flow_execute)
    app.router.add_post("/api/robot/emergency-stop", _robot_emergency_stop)
    app.router.add_post("/api/robot/flows/run", _robot_run_flow)
    app.router.add_post("/api/identity/login", _identity_login)
    app.router.add_post("/api/identity/logout", _identity_logout)
    app.router.add_get("/api/identity/me", _identity_me)
    app.router.add_get("/api/identity/users", _identity_users)
    app.router.add_post("/api/identity/users", _identity_create_user)
    app.router.add_patch("/api/identity/users/{user_id}", _identity_update_user)
    app.router.add_delete("/api/identity/users/{user_id}", _identity_delete_user)
    app.router.add_post("/api/identity/users/{user_id}/password", _identity_reset_password)
    app.router.add_post("/api/identity/me/password", _identity_change_own_password)
    app.router.add_get("/api/management/commands", _management_commands)
    app.router.add_post("/api/management/commands", _management_create_command)
    app.router.add_get("/api/management/commands/{command_id}", _management_command)
    app.router.add_put("/api/management/commands/{command_id}", _management_save_command)
    app.router.add_delete("/api/management/commands/{command_id}", _management_delete_command)
    app.router.add_put("/api/management/commands/{command_id}/draft", _management_update_draft)
    app.router.add_post("/api/management/commands/{command_id}/draft", _management_start_draft)
    app.router.add_post("/api/management/commands/{command_id}/publish", _management_publish)
    app.router.add_post("/api/management/commands/{command_id}/archive", _management_archive)
    app.router.add_post("/api/management/commands/{command_id}/duplicate", _management_duplicate_command)
    app.router.add_post("/api/management/commands/bulk-archive", _management_bulk_archive_commands)
    app.router.add_get("/api/management/flows", _management_flows)
    app.router.add_post("/api/management/flows", _management_create_flow)
    app.router.add_get("/api/management/flows/{flow_id}", _management_flow)
    app.router.add_put("/api/management/flows/{flow_id}", _management_save_flow)
    app.router.add_delete("/api/management/flows/{flow_id}", _management_delete_flow)
    app.router.add_put("/api/management/flows/{flow_id}/draft", _management_update_flow_draft)
    app.router.add_post("/api/management/flows/{flow_id}/draft", _management_start_flow_draft)
    app.router.add_post("/api/management/flows/{flow_id}/validate", _management_validate_flow)
    app.router.add_post("/api/management/flows/{flow_id}/publish", _management_publish_flow)
    app.router.add_post("/api/management/flows/{flow_id}/archive", _management_archive_flow)
    app.router.add_post("/api/management/flows/{flow_id}/duplicate", _management_duplicate_flow)
    app.router.add_post("/api/management/flows/bulk-archive", _management_bulk_archive_flows)
    app.router.add_get("/api/management/product-profile", _management_product_profile)
    app.router.add_put("/api/management/product-profile", _management_update_product_profile)
    app.router.add_get("/api/management/diagnostics", _management_diagnostics)
    app.router.add_get("/api/management/audit", _management_audit)
    app.router.add_get("/api/management/library/export", _management_export_library)
    app.router.add_post("/api/management/library/import", _management_import_library)
    app.router.add_get("/api/management/positions/cleanup-preview", _management_position_cleanup_preview)
    app.router.add_post("/api/management/positions/cleanup", _management_position_cleanup_apply)
    app.router.add_post("/api/library/commands/{command_id}/executions", _library_start_command_execution)
    app.router.add_post("/api/library/flows/{flow_id}/executions", _library_start_flow_execution)
    app.router.add_get("/api/library/executions", _library_list_executions)
    app.router.add_get("/api/library/executions/{execution_id}", _library_execution)
    app.router.add_post("/api/library/executions/{execution_id}/control", _library_control_execution)
    app.router.add_get("/api/library/components", _library_components)
    app.router.add_get("/api/library/components/{component_id}", _library_component)
    app.router.add_get("/api/library/commands", _library_commands)
    app.router.add_get("/api/library/commands/{command_id}", _library_command)
    app.router.add_get("/api/library/flows", _library_flows)
    app.router.add_get("/api/library/flows/{flow_id}", _library_flow)
    app.router.add_get("/ws/agent", _agent_websocket)

    if server_config.agent_runtime is not None:
        async def start_agent_runtime(_app: web.Application) -> None:
            await server_config.agent_runtime.start()

        async def stop_agent_runtime(_app: web.Application) -> None:
            await server_config.agent_runtime.stop()

        app.on_startup.append(start_agent_runtime)
        app.on_cleanup.append(stop_agent_runtime)

    static_dist = server_config.static_dist_path
    if static_dist is not None and static_dist.is_dir():
        index = static_dist / "index.html"
        if index.is_file():
            app.router.add_get("/", _static_index)
        app.router.add_static("/", str(static_dist), show_index=False)
    return app


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "robot-server"})


async def _bootstrap(request: web.Request) -> web.Response:
    config = request.app[ROBOT_SERVER_CONFIG_KEY]
    return web.json_response({
        "service": config.runtime_name,
        "auth_required": bool(config.access_token.strip()),
        "api": {
            "robot_status": "/api/robot/status",
            "plans": "/api/robot/plans",
            "emergency_stop": "/api/robot/emergency-stop",
            "run_flow": "/api/robot/flows/run",
            "library": "/api/library",
            "identity": "/api/identity",
            "management": "/api/management",
        },
    })


async def _webui_bootstrap(request: web.Request) -> web.Response:
    """Provide the retained React UI with a local WebSocket target."""
    return web.json_response({
        "token": "local",
        "ws_path": "/webui",
        # Optional for older WebUI builds; v1 is the retained HTTP/WS frame contract.
        "protocol_version": 1,
        "expires_in": 24 * 60 * 60,
        "runtime_surface": "browser",
        "runtime_capabilities": {
            "can_restart_engine": False,
            "can_pick_folder": False,
            "can_open_logs": False,
            "can_export_diagnostics": False,
        },
    })


async def _webui_login(request: web.Request) -> web.Response:
    """Accept the legacy UI's GET-plus-header login shape locally."""
    raw_body = request.headers.get("X-Nanobot-Robot-Body", "")
    try:
        body: Any = json.loads(raw_body)
    except json.JSONDecodeError:
        body = None
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].login,
        body,
        client_key=request.remote or "local",
    )
    return web.json_response(result, status=status)


async def _webui_logout(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].logout,
        request.headers.get("X-Nanobot-User-Token", "").strip(),
    )
    return web.json_response(result, status=status)


async def _webui_login_preflight(request: web.Request) -> web.Response:
    """Run the retained login-page diagnostics without restoring a gateway.

    The AI check deliberately performs the same minimal, no-tools provider
    request as the former page.  Controller status is read-only and never
    attempts a motion command.
    """
    raw_body = request.headers.get("X-Nanobot-Robot-Body", "")
    try:
        body: Any = json.loads(raw_body)
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid request body"}, status=400)
    host = body.get("controller_host") if isinstance(body, dict) else None
    try:
        address = ipaddress.ip_address(str(host or "").strip())
        if not (address.is_private or address.is_loopback):
            raise ValueError
    except ValueError:
        return web.json_response({"error": "controller_host must be a private or loopback IP address"}, status=400)

    async def probe(
        action: Callable[[], Awaitable[None]], *, expected_reasons: set[str] | None = None,
    ) -> dict[str, object]:
        # ``latency_ms`` is the local duration of this readiness probe. It is
        # not a motion-control cycle time or an end-to-end control latency.
        started = time.perf_counter()
        try:
            await action()
        except Exception as exc:
            # A controller backend deliberately turns communication failures
            # into a disconnected RobotState so callers can still show its
            # diagnostics.  Preserve those two expected states here instead
            # of reporting a false successful connection merely because
            # ``get_status`` itself returned normally.
            reason = str(exc)
            accepted = {"lower_machine_not_connected", "simulation_mode"}
            if expected_reasons:
                accepted.update(expected_reasons)
            if reason not in accepted:
                reason = "service_unavailable"
            return {"state": "unhealthy", "reason": reason, "latency_ms": round((time.perf_counter() - started) * 1000)}
        return {"state": "healthy", "latency_ms": round((time.perf_counter() - started) * 1000)}

    async def check_controller() -> None:
        configured_probe = request.app[ROBOT_SERVER_CONFIG_KEY].controller_probe
        if configured_probe is None:
            # This product-wiring function constructs a temporary backend for
            # the entered host only.  It never writes to the controller and
            # does not replace the running backend configuration.
            from robot_platform.backends.product_wiring import probe_product_controller

            robot_state = await asyncio.to_thread(probe_product_controller, str(address))
        else:
            robot_state = await asyncio.to_thread(configured_probe, str(address))
        if not isinstance(robot_state, dict):
            raise RuntimeError("service_unavailable")
        if robot_state.get("connected_real_device") is True:
            return
        if robot_state.get("mode") == "simulation":
            raise RuntimeError("simulation_mode")
        raise RuntimeError("lower_machine_not_connected")

    async def check_ai() -> None:
        runtime = request.app[AGENT_RUNTIME_KEY]
        if runtime is None:
            raise RuntimeError("agent runtime unavailable")
        await asyncio.wait_for(runtime.check_ai_connectivity(), timeout=12)

    async def check_voice() -> None:
        config = load_config(request.app[ROBOT_SERVER_CONFIG_KEY].deployment_config_path)
        try:
            await probe_bailian_realtime_asr(config.providers.dashscope.api_key or "")
        except RealtimeAsrError as exc:
            raise RuntimeError(str(exc)) from exc

    controller = await probe(check_controller)
    controller["host"] = str(address)
    ai = await probe(check_ai)
    # The platform's recording path is the built-in Bailian realtime-ASR
    # bridge, not nanobot's legacy upload/transcription provider.  Verify the
    # actual provider session so this login badge cannot disagree with the mic.
    voice = await probe(check_voice, expected_reasons={
        "voice_not_configured", "voice_connection_failed", "voice_provider_error",
    })
    if voice["state"] == "healthy":
        voice["provider"] = "bailian-realtime-asr"
    return web.json_response({"ok": True, "data": {"controller": controller, "voice": voice, "ai": ai}})


async def _media(request: web.Request) -> web.Response:
    return request.app[LOCAL_MEDIA_SERVICE_KEY].response(
        request.match_info["signature"], request.match_info["payload"], request
    )


async def _ui_sessions(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].list_sessions, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _ui_session_thread(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].thread,
        _identity_token(request), request.match_info["key"],
    )
    return web.json_response(result, status=status)


async def _ui_file_preview(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(file_preview, request.query.get("path"))
    return web.json_response(result, status=status)


async def _ui_delete_session(request: web.Request) -> web.Response:
    status, result = await request.app[LOCAL_UI_STATE_SERVICE_KEY].delete_session(
        _identity_token(request), request.match_info["key"]
    )
    return web.json_response(result, status=status)


async def _ui_sidebar_state(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].sidebar_state, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _ui_update_sidebar_state(request: web.Request) -> web.Response:
    if request.method == "GET":
        raw_state = request.query.get("state", "")
        try:
            state = json.loads(raw_state)
        except (TypeError, json.JSONDecodeError):
            return web.json_response({"error": "invalid_sidebar_state"}, status=400)
    else:
        state = await _json_body(request)
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].update_sidebar_state,
        _identity_token(request), state,
    )
    return web.json_response(result, status=status)


async def _ui_skills(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].skills, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _ui_skill_detail(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].skills,
        _identity_token(request), request.match_info["name"],
    )
    return web.json_response(result, status=status)


async def _ui_workspaces(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].workspaces, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _ui_commands(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_UI_STATE_SERVICE_KEY].commands, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _session_automations(request: web.Request) -> web.Response:
    key = request.match_info["key"]
    if key.startswith("robot-server:"):
        session_key = key
    elif key.startswith("websocket:"):
        session_key = f"robot-server:{key.removeprefix('websocket:')}"
    else:
        return web.json_response(
            {"error": {"code": "invalid_session", "message": "invalid local session key"}},
            status=400,
        )
    status, result = await asyncio.to_thread(
        request.app[LOCAL_AUTOMATION_SERVICE_KEY].payload, session_key
    )
    return web.json_response(result, status=status)


async def _automations(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(request.app[LOCAL_AUTOMATION_SERVICE_KEY].payload)
    return web.json_response(result, status=status)


async def _automation_action(request: web.Request, action: str) -> web.Response:
    job_id = request.query.get("id", "")
    if action == "run":
        status, result = await request.app[LOCAL_AUTOMATION_SERVICE_KEY].run(job_id)
    else:
        status, result = await asyncio.to_thread(
            request.app[LOCAL_AUTOMATION_SERVICE_KEY].action, action, job_id
        )
    return web.json_response(result, status=status)


async def _automation_enable(request: web.Request) -> web.Response:
    return await _automation_action(request, "enable")


async def _automation_disable(request: web.Request) -> web.Response:
    return await _automation_action(request, "disable")


async def _automation_delete(request: web.Request) -> web.Response:
    return await _automation_action(request, "delete")


async def _automation_run(request: web.Request) -> web.Response:
    return await _automation_action(request, "run")


async def _automation_update(request: web.Request) -> web.Response:
    values = request.app[LOCAL_AUTOMATION_SERVICE_KEY].values(
        request.headers.get("X-Nanobot-Automation-Values")
    )
    status, result = await asyncio.to_thread(
        request.app[LOCAL_AUTOMATION_SERVICE_KEY].update, request.query.get("id", ""), values
    )
    return web.json_response(result, status=status)


def _query_values(request: web.Request) -> dict[str, str]:
    return {key: value for key, value in request.query.items()}


async def _settings(request: web.Request) -> web.Response:
    return web.json_response(request.app[LOCAL_SETTINGS_SERVICE_KEY].payload())


async def _settings_usage(request: web.Request) -> web.Response:
    return web.json_response(request.app[LOCAL_SETTINGS_SERVICE_KEY].usage())


async def _settings_version_check(request: web.Request) -> web.Response:
    result = await asyncio.to_thread(request.app[LOCAL_SETTINGS_SERVICE_KEY].version_check)
    return web.json_response(result)


async def _settings_web_search_update(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_SETTINGS_SERVICE_KEY].update_web_search, _query_values(request)
    )
    return web.json_response(result, status=status)


async def _settings_network_safety_update(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_SETTINGS_SERVICE_KEY].update_network_safety, _query_values(request)
    )
    return web.json_response(result, status=status)


async def _settings_image_generation_update(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_SETTINGS_SERVICE_KEY].update_image_generation, _query_values(request)
    )
    return web.json_response(result, status=status)


async def _settings_transcription_update(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_SETTINGS_SERVICE_KEY].update_transcription, _query_values(request)
    )
    return web.json_response(result, status=status)


async def _cli_apps(request: web.Request) -> web.Response:
    installed_only = request.query.get("installed_only", "").lower() in {"1", "true", "yes"}
    result = await asyncio.to_thread(request.app[LOCAL_APPS_SERVICE_KEY].cli_payload, installed_only=installed_only)
    return web.json_response(result)


async def _cli_apps_action(request: web.Request, action: str) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[LOCAL_APPS_SERVICE_KEY].cli_action, action, request.query.get("name", "")
    )
    return web.json_response(result, status=status)


async def _cli_apps_install(request: web.Request) -> web.Response:
    return await _cli_apps_action(request, "install")


async def _cli_apps_update(request: web.Request) -> web.Response:
    return await _cli_apps_action(request, "update")


async def _cli_apps_uninstall(request: web.Request) -> web.Response:
    return await _cli_apps_action(request, "uninstall")


async def _cli_apps_test(request: web.Request) -> web.Response:
    return await _cli_apps_action(request, "test")


def _mcp_values(request: web.Request) -> dict[str, Any]:
    raw = request.headers.get("X-Nanobot-MCP-Values")
    if not raw: return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


async def _mcp_presets(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(request.app[LOCAL_APPS_SERVICE_KEY].mcp_payload))


async def _mcp_action(request: web.Request, action: str) -> web.Response:
    try:
        status, result = await asyncio.to_thread(request.app[LOCAL_APPS_SERVICE_KEY].mcp_action, action,
                                                  request.query.get("name", ""), _mcp_values(request))
    except ValueError as exc:
        status, result = 400, {"error": {"code": "invalid_request", "message": str(exc)}}
    return web.json_response(result, status=status)


async def _mcp_enable(request: web.Request) -> web.Response:
    return await _mcp_action(request, "enable")


async def _mcp_remove(request: web.Request) -> web.Response:
    return await _mcp_action(request, "remove")


async def _mcp_test(request: web.Request) -> web.Response:
    return await _mcp_action(request, "test")


async def _mcp_custom(request: web.Request) -> web.Response:
    return await _mcp_action(request, "custom")


async def _mcp_import(request: web.Request) -> web.Response:
    return await _mcp_action(request, "import")


async def _mcp_tools(request: web.Request) -> web.Response:
    return await _mcp_action(request, "tools")


async def _webui_socket(request: web.Request) -> web.StreamResponse:
    """Host the retained WebUI protocol outside the direct runtime boundary."""
    return await legacy_webui_websocket(
        request,
        runtime=request.app[AGENT_RUNTIME_KEY],
        identity=request.app[ROBOT_IDENTITY_SERVICE_KEY],
        deployment_config_path=request.app[ROBOT_SERVER_CONFIG_KEY].deployment_config_path,
    )


async def _robot_status(request: web.Request) -> web.Response:
    platform = request.app[ROBOT_PLATFORM_KEY]
    try:
        result: dict[str, Any] = await asyncio.to_thread(platform.get_status)
    except Exception:
        # Do not surface a controller stack trace or configuration secrets over
        # HTTP.  Detailed diagnostics remain in server logs.
        return web.json_response({"error": "robot status unavailable"}, status=503)
    return web.json_response(_with_public_capabilities(result))


def _with_public_capabilities(result: dict[str, Any]) -> dict[str, Any]:
    """Add the v1 contract for legacy platform implementations when possible.

    The retained ``controller_capabilities`` field is not changed, so existing
    clients keep their response shape while new clients can depend on the
    versioned vendor-neutral ``capabilities`` field.
    """
    data = result.get("data")
    if not isinstance(data, dict) or isinstance(data.get("capabilities"), dict):
        return result
    legacy_capabilities = data.get("controller_capabilities")
    if not isinstance(legacy_capabilities, dict):
        return result
    motion_primitives = legacy_capabilities.get("motion_primitives", ())
    if not isinstance(motion_primitives, (list, tuple)):
        motion_primitives = ()
    public_capabilities = ControllerCapabilities(
        vendor=str(legacy_capabilities.get("vendor", "")),
        supports_state_read=bool(legacy_capabilities.get("supports_state_read", True)),
        supports_real_writes=bool(legacy_capabilities.get("supports_real_writes", False)),
        motion_primitives=tuple(str(item) for item in motion_primitives),
    ).to_public_dict()
    return {**result, "data": {**data, "capabilities": public_capabilities}}


async def _robot_plan(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    status, result = await asyncio.to_thread(service.plan, await _json_body(request))
    return web.json_response(result, status=status)


async def _robot_confirm(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    status, result = await asyncio.to_thread(
        service.confirm, request.match_info["plan_id"], await _json_body(request)
    )
    return web.json_response(result, status=status)


async def _robot_execute(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    with bind_session_key(_body_session_key(body)):
        status, result = await asyncio.to_thread(
            service.execute, request.match_info["plan_id"], body
        )
    return web.json_response(result, status=status)


async def _robot_flow_plan(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    status, result = await asyncio.to_thread(service.plan_flow, await _json_body(request))
    return web.json_response(result, status=status)


async def _robot_flow_confirm(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    plan_id = body.get("plan_id") if isinstance(body, dict) else ""
    if not isinstance(plan_id, str) or not plan_id:
        return web.json_response({"error": {"code": 400, "message": "plan_id is required"}}, status=400)
    status, result = await asyncio.to_thread(service.confirm, plan_id, body)
    return web.json_response(result, status=status)


async def _robot_flow_execute(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    plan_id = body.get("plan_id") if isinstance(body, dict) else ""
    if not isinstance(plan_id, str) or not plan_id:
        return web.json_response({"error": {"code": 400, "message": "plan_id is required"}}, status=400)
    with bind_session_key(_body_session_key(body)):
        status, result = await asyncio.to_thread(service.execute_flow, plan_id, body)
    return web.json_response(result, status=status)


async def _robot_emergency_stop(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    with bind_session_key(_body_session_key(body)):
        status, result = await asyncio.to_thread(service.emergency_stop, body)
    return web.json_response(result, status=status)


async def _robot_run_flow(request: web.Request) -> web.Response:
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    with bind_session_key(_body_session_key(body)):
        status, result = await asyncio.to_thread(service.run_flow, body)
    return web.json_response(result, status=status)


async def _identity_login(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].login,
        await _json_body(request),
        client_key=request.remote or "local",
    )
    return web.json_response(result, status=status)


async def _identity_logout(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].logout,
        _identity_token(request),
    )
    return web.json_response(result, status=status)


async def _identity_me(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].session,
        _identity_token(request),
    )
    return web.json_response(result, status=status)


async def _identity_users(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].list_users,
        _identity_token(request),
    )
    return web.json_response(result, status=status)


async def _identity_create_user(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].create_user,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _identity_update_user(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].update_user,
        _identity_token(request),
        request.match_info["user_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _identity_reset_password(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].reset_password,
        _identity_token(request),
        request.match_info["user_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _identity_delete_user(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].delete_user,
        _identity_token(request),
        request.match_info["user_id"],
    )
    return web.json_response(result, status=status)


async def _identity_change_own_password(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].change_own_password,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_commands(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].list,
        _identity_token(request),
    )
    return web.json_response(result, status=status)


async def _management_create_command(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].create,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_command(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].get,
        _identity_token(request),
        request.match_info["command_id"],
    )
    return web.json_response(result, status=status)


async def _management_save_command(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].save,
        _identity_token(request),
        request.match_info["command_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_delete_command(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].delete,
        _identity_token(request),
        request.match_info["command_id"],
    )
    return web.json_response(result, status=status)


async def _management_update_draft(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].update_draft,
        _identity_token(request),
        request.match_info["command_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_start_draft(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].start_draft,
        _identity_token(request),
        request.match_info["command_id"],
    )
    return web.json_response(result, status=status)


async def _management_publish(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].publish,
        _identity_token(request),
        request.match_info["command_id"],
    )
    return web.json_response(result, status=status)


async def _management_archive(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].archive,
        _identity_token(request),
        request.match_info["command_id"],
    )
    return web.json_response(result, status=status)


async def _management_duplicate_command(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].duplicate,
        _identity_token(request),
        request.match_info["command_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_bulk_archive_commands(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_COMMAND_MANAGEMENT_KEY].bulk_archive,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_flows(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].list, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _management_create_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].create,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].get,
        _identity_token(request),
        request.match_info["flow_id"],
    )
    return web.json_response(result, status=status)


async def _management_save_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].save,
        _identity_token(request),
        request.match_info["flow_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_delete_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].delete,
        _identity_token(request),
        request.match_info["flow_id"],
    )
    return web.json_response(result, status=status)


async def _management_update_flow_draft(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].update_draft,
        _identity_token(request),
        request.match_info["flow_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_start_flow_draft(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].start_draft,
        _identity_token(request),
        request.match_info["flow_id"],
    )
    return web.json_response(result, status=status)


async def _management_validate_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].validate_draft,
        _identity_token(request),
        request.match_info["flow_id"],
    )
    return web.json_response(result, status=status)


async def _management_publish_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].publish,
        _identity_token(request),
        request.match_info["flow_id"],
    )
    return web.json_response(result, status=status)


async def _management_archive_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].archive,
        _identity_token(request),
        request.match_info["flow_id"],
    )
    return web.json_response(result, status=status)


async def _management_duplicate_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].duplicate,
        _identity_token(request),
        request.match_info["flow_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_bulk_archive_flows(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_FLOW_MANAGEMENT_KEY].bulk_archive,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_product_profile(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[PRODUCT_PROFILE_SERVICE_KEY].get,
        _identity_token(request),
    )
    return web.json_response(result, status=status)


async def _management_update_product_profile(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[PRODUCT_PROFILE_SERVICE_KEY].update,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_diagnostics(request: web.Request) -> web.Response:
    """Expose the retained engineer diagnostics panel through robot-server.

    This is deliberately read-only and engineer-scoped.  The shape preserves
    the existing React panel while deriving every value from the public
    platform status result rather than the retired gateway.
    """
    _session, error = await asyncio.to_thread(
        request.app[ROBOT_IDENTITY_SERVICE_KEY].require_engineer_session,
        _identity_token(request),
    )
    if error is not None:
        status, result = error
        return web.json_response(result, status=status)
    try:
        result = await asyncio.to_thread(request.app[ROBOT_PLATFORM_KEY].get_status)
    except Exception:
        return web.json_response(
            {"error": {"code": "robot_status_unavailable", "message": "Robot status unavailable."}},
            status=503,
        )
    data = result.get("data", {}) if isinstance(result, dict) else {}
    state = data.get("robot_state", {}) if isinstance(data, dict) else {}
    if not isinstance(state, dict):
        state = {}
    return web.json_response({"ok": True, "data": {
        "connection": {
            "mode": str(state.get("mode", "unknown")),
            "real_device": bool(state.get("connected_real_device", False)),
        },
        "execution_mode": str(data.get("execution_mode", "dry_run_only")),
        "position": dict(state.get("axes_mm", {})) if isinstance(state.get("axes_mm"), dict) else {},
        "io": dict(data.get("io", {})) if isinstance(data.get("io"), dict) else {},
        "alarms": list(state.get("alarms", [])) if isinstance(state.get("alarms"), list) else [],
        "task": state.get("mode", "unknown"),
        "command_echo": data.get("command_echo", {}),
    }})


async def _management_audit(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_AUDIT_SERVICE_KEY].list,
        _identity_token(request),
        limit=request.query.get("limit", "50"),
        before=request.query.get("before", ""),
    )
    return web.json_response(result, status=status)


async def _management_export_library(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_LIBRARY_TRANSFER_KEY].export, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _management_import_library(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_LIBRARY_TRANSFER_KEY].import_payload,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _management_position_cleanup_preview(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_POSITION_MAINTENANCE_KEY].preview, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _management_position_cleanup_apply(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_POSITION_MAINTENANCE_KEY].apply,
        _identity_token(request),
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _library_start_command_execution(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_EXECUTION_SERVICE_KEY].start_command,
        _identity_token(request),
        request.match_info["command_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _library_start_flow_execution(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_EXECUTION_SERVICE_KEY].start_flow,
        _identity_token(request),
        request.match_info["flow_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _library_list_executions(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_EXECUTION_SERVICE_KEY].list, _identity_token(request)
    )
    return web.json_response(result, status=status)


async def _library_execution(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_EXECUTION_SERVICE_KEY].get,
        _identity_token(request),
        request.match_info["execution_id"],
    )
    return web.json_response(result, status=status)


async def _library_control_execution(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_EXECUTION_SERVICE_KEY].control,
        _identity_token(request),
        request.match_info["execution_id"],
        await _json_body(request),
    )
    return web.json_response(result, status=status)


async def _library_components(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_LIBRARY_SERVICE_KEY].list_components
    )
    return web.json_response(result, status=status)


async def _library_component(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_LIBRARY_SERVICE_KEY].get_component,
        request.match_info["component_id"],
    )
    return web.json_response(result, status=status)


async def _library_commands(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_LIBRARY_SERVICE_KEY].list_commands,
        component_id=request.query.get("component_id", ""),
        risk_level=request.query.get("risk_level", ""),
        query=request.query.get("q", ""),
    )
    return web.json_response(result, status=status)


async def _library_command(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_LIBRARY_SERVICE_KEY].get_command,
        request.match_info["command_id"],
    )
    return web.json_response(result, status=status)


async def _library_flows(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(request.app[ROBOT_LIBRARY_SERVICE_KEY].list_flows)
    return web.json_response(result, status=status)


async def _library_flow(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_LIBRARY_SERVICE_KEY].get_flow,
        request.match_info["flow_id"],
    )
    return web.json_response(result, status=status)


async def _agent_websocket(request: web.Request) -> web.StreamResponse:
    runtime = request.app[AGENT_RUNTIME_KEY]
    if runtime is None:
        return web.json_response({"error": "agent runtime is unavailable"}, status=503)
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)

    async def send_events() -> None:
        async for event in runtime.subscribe():
            frame = webui_frame_for_runtime_event(event)
            if frame is not None:
                await socket.send_json(frame)

    sender = asyncio.create_task(send_events())
    try:
        await socket.send_json({"event": "ready", "service": "robot-server"})
        async for message in socket:
            if message.type is not web.WSMsgType.TEXT:
                continue
            try:
                envelope = json.loads(message.data)
            except json.JSONDecodeError:
                await socket.send_json({"event": "error", "detail": "invalid_json"})
                continue
            if not isinstance(envelope, dict):
                await socket.send_json({"event": "error", "detail": "invalid_envelope"})
                continue
            kind = envelope.get("type")
            conversation_id = envelope.get("session_id")
            if not isinstance(conversation_id, str) or not conversation_id.strip():
                await socket.send_json({"event": "error", "detail": "session_id_required"})
                continue
            if kind == "cancel":
                cancelled = await runtime.cancel(conversation_id)
                await socket.send_json({"event": "cancelled", "session_id": conversation_id, "count": cancelled})
                continue
            if kind != "message" or not isinstance(envelope.get("content"), str):
                await socket.send_json({"event": "error", "detail": "message_content_required"})
                continue
            try:
                await runtime.submit(AgentRequest(
                    conversation_id=conversation_id,
                    actor_id=str(envelope.get("actor_id") or "local-operator"),
                    content=envelope["content"],
                    stream=bool(envelope.get("stream", True)),
                    request_id=envelope.get("request_id") if isinstance(envelope.get("request_id"), str) else None,
                ))
            except (RuntimeError, ValueError) as exc:
                await socket.send_json({"event": "error", "detail": str(exc)})
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
    return socket


async def _json_body(request: web.Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return None


def _body_session_key(body: Any) -> str:
    if isinstance(body, dict) and isinstance(body.get("session_id"), str):
        return f"robot-server:{body['session_id'].strip()[:128]}"
    return "robot-server:default"


def _identity_token(request: web.Request) -> str:
    # Keep the original WebUI header as the public contract while accepting
    # the short-lived rewrite header for clients built during migration.
    return (
        request.headers.get("X-Nanobot-User-Token", "").strip()
        or request.headers.get("X-Robot-User-Token", "").strip()
    )


def _default_robot_data_dir() -> Path:
    from robot_platform import get_robot_data_dir

    return get_robot_data_dir()


async def _static_index(request: web.Request) -> web.FileResponse:
    config = request.app[ROBOT_SERVER_CONFIG_KEY]
    assert config.static_dist_path is not None
    return web.FileResponse(config.static_dist_path / "index.html")
