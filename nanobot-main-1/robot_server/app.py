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
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from ai_runtime.engine_contract import AgentEngine, AgentRequest
from ai_runtime.identity import issue_verified_principal
from nanobot.config.loader import load_config
from robot_platform.application import (
    AuthenticatedPrincipal,
    EmergencyStopApplicationService,
    RobotEmergencyStopCommand,
    RobotDiagnosticsApplicationService,
    RobotDiagnosticsQuery,
    RobotStatusApplicationService,
)
from robot_platform import LibraryExecutionRegistry, RobotPlatform
from robot_platform.feature_policy import FeatureDisabledError, ProductFeaturePolicy
from robot_server.audit_api import RobotAuditService
from robot_server.command_management import RobotCommandManagementService
from robot_server.flow_management import RobotFlowManagementService
from robot_server.execution_api import RobotExecutionService
from robot_server.bootstrap import compose_runtime_container
from robot_server.container import RuntimeContainer
from robot_server.identity_api import RobotIdentityService
from robot_server.library_api import RobotLibraryService
from robot_server.library_transfer import RobotLibraryTransferService
from robot_server.position_maintenance import RobotPositionMaintenanceService
from robot_server.product_profile import ProductProfileService
from robot_server.request_context import bind_principal
from robot_server.route_modules import register_feature_routes
from robot_server.route_support import (
    identity_token as _identity_token,
    json_body as _json_body,
    robot_principal as _robot_principal,
    service_error_response as _service_error_response,
)
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
from robot_server.app_keys import (
    AGENT_RUNTIME_KEY,
    LOCAL_APPS_SERVICE_KEY,
    LOCAL_AUTOMATION_SERVICE_KEY,
    LOCAL_MEDIA_SERVICE_KEY,
    LOCAL_SETTINGS_SERVICE_KEY,
    LOCAL_UI_STATE_SERVICE_KEY,
    PRODUCT_PROFILE_SERVICE_KEY,
    ROBOT_AUDIT_SERVICE_KEY,
    ROBOT_COMMAND_MANAGEMENT_KEY,
    ROBOT_DIAGNOSTICS_SERVICE_KEY,
    ROBOT_EMERGENCY_STOP_SERVICE_KEY,
    ROBOT_EXECUTION_SERVICE_KEY,
    ROBOT_FLOW_MANAGEMENT_KEY,
    ROBOT_IDENTITY_SERVICE_KEY,
    ROBOT_LIBRARY_SERVICE_KEY,
    ROBOT_LIBRARY_TRANSFER_KEY,
    ROBOT_OPERATION_SERVICE_KEY,
    ROBOT_PLATFORM_KEY,
    ROBOT_POSITION_MAINTENANCE_KEY,
    ROBOT_SERVER_CONFIG_KEY,
    ROBOT_STATUS_SERVICE_KEY,
    PRODUCT_FEATURE_POLICY_KEY,
)

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
    # Compatibility escape hatch for rollback only. Production and tests use
    # trusted user-session principals by default.
    trusted_principal_v1: bool = True
    robot_id: str = "primary-robot"
    controller_id: str = ""
    product_profile_version: str = "1"
    capability_version: str = "1"
    core_version: str = "1"
    deployment_instance_id: str = ""
    # A host-only, read-only probe used by the login diagnostics.  Production
    # uses ``probe_product_controller``; the hook keeps the HTTP layer vendor
    # neutral and makes the contract testable without controller hardware.
    controller_probe: Callable[[str], dict[str, object]] | None = None


def create_robot_server_app(
    *,
    container: RuntimeContainer | None = None,
    platform: RobotPlatform | None = None,
    config: RobotServerConfig | None = None,
) -> web.Application:
    """Create the single-process robot server application.

    State-changing routes call the same ``RobotPlatform`` safety boundary as
    AI tools; the server owns only HTTP parsing and pending-plan lifecycle.
    """

    if container is not None and (platform is not None or config is not None):
        raise ValueError("container cannot be combined with legacy platform/config arguments")
    server_config = container.config if container is not None else (config or RobotServerConfig())
    runtime_container = container or compose_runtime_container(
        server_config, platform=platform,
    )
    app = web.Application(client_max_size=20 * 1024 * 1024)
    # Unstarted inspection apps (route-contract tests, embedding probes) never
    # receive aiohttp cleanup callbacks. Finalization keeps exclusive runtime
    # resources from leaking when such an app is abandoned.
    weakref.finalize(app, runtime_container.close)
    app[ROBOT_PLATFORM_KEY] = runtime_container.platform
    app[ROBOT_STATUS_SERVICE_KEY] = runtime_container.status_service
    app[ROBOT_DIAGNOSTICS_SERVICE_KEY] = runtime_container.diagnostics_service
    app[ROBOT_EMERGENCY_STOP_SERVICE_KEY] = runtime_container.emergency_stop_service
    app[ROBOT_SERVER_CONFIG_KEY] = server_config
    app[ROBOT_OPERATION_SERVICE_KEY] = runtime_container.operation_service
    app[ROBOT_LIBRARY_SERVICE_KEY] = runtime_container.library_service
    app[ROBOT_IDENTITY_SERVICE_KEY] = runtime_container.identity_service
    app[ROBOT_COMMAND_MANAGEMENT_KEY] = runtime_container.command_management
    app[ROBOT_FLOW_MANAGEMENT_KEY] = runtime_container.flow_management
    app[ROBOT_AUDIT_SERVICE_KEY] = runtime_container.audit_service
    app[ROBOT_LIBRARY_TRANSFER_KEY] = runtime_container.library_transfer
    app[ROBOT_POSITION_MAINTENANCE_KEY] = runtime_container.position_maintenance
    app[ROBOT_EXECUTION_SERVICE_KEY] = runtime_container.execution_service
    app[PRODUCT_PROFILE_SERVICE_KEY] = runtime_container.product_profile
    app[AGENT_RUNTIME_KEY] = runtime_container.agent_runtime
    app[LOCAL_UI_STATE_SERVICE_KEY] = runtime_container.ui_state
    app[LOCAL_SETTINGS_SERVICE_KEY] = runtime_container.settings
    app[LOCAL_AUTOMATION_SERVICE_KEY] = runtime_container.automations
    app[LOCAL_APPS_SERVICE_KEY] = runtime_container.apps
    app[LOCAL_MEDIA_SERVICE_KEY] = runtime_container.media
    feature_policy = runtime_container.feature_policy or getattr(
        runtime_container.platform, "feature_policy", ProductFeaturePolicy(),
    )
    app[PRODUCT_FEATURE_POLICY_KEY] = feature_policy

    async def _close_runtime_container(_app: web.Application) -> None:
        runtime_container.close()

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
        try:
            for feature_id in _features_for_path(request.path):
                feature_policy.require(feature_id)
        except FeatureDisabledError:
            return web.json_response(
                {"error": "feature_disabled", "path": request.path}, status=404,
            )
        return await handler(request)

    app.middlewares.append(local_auth)
    # Handler implementations remain protocol-compatible while route ownership
    # is split into WebUI, product-control, and management feature catalogs.
    register_feature_routes(app)

    if runtime_container.agent_runtime is not None:
        async def start_agent_runtime(_app: web.Application) -> None:
            try:
                await runtime_container.agent_runtime.start()
            except BaseException as start_error:
                # aiohttp does not guarantee on_cleanup after a failed startup.
                try:
                    runtime_container.close()
                except BaseException as cleanup_error:
                    start_error.add_note(
                        f"runtime cleanup also failed: {cleanup_error!r}"
                    )
                raise

        async def stop_agent_and_close_container(_app: web.Application) -> None:
            try:
                await runtime_container.agent_runtime.stop()
            finally:
                runtime_container.close()

        app.on_startup.append(start_agent_runtime)
        app.on_cleanup.append(stop_agent_and_close_container)
    else:
        app.on_cleanup.append(_close_runtime_container)

    static_dist = server_config.static_dist_path
    if static_dist is not None and static_dist.is_dir():
        index = static_dist / "index.html"
        if index.is_file():
            app.router.add_get("/", _static_index)
        app.router.add_static("/", str(static_dist), show_index=False)
    return app

async def _static_index(request: web.Request) -> web.FileResponse:
    config = request.app[ROBOT_SERVER_CONFIG_KEY]
    assert config.static_dist_path is not None
    return web.FileResponse(config.static_dist_path / "index.html")


def _features_for_path(path: str) -> tuple[str, ...]:
    if "/automations" in path:
        return ("cron",)
    if path.startswith("/api/management/positions"):
        return ("robot_position",)
    if path.startswith("/api/management/flows"):
        return ("robot_flow",)
    if path.startswith("/api/management/commands") or path.startswith(
        "/api/management/library"
    ):
        return ("robot_library",)
    if path.startswith("/api/library/flows"):
        return ("robot_library", "robot_flow")
    if path.startswith("/api/library"):
        return ("robot_library",)
    if path in {"/api/robot/flow-execute", "/api/robot/flows/run"}:
        return ("robot_flow", "robot_arm")
    if path.startswith("/api/robot/flow") or path.startswith("/api/robot/flows"):
        return ("robot_flow",)
    if path.startswith("/api/robot"):
        return ("robot_arm",)
    return ()
