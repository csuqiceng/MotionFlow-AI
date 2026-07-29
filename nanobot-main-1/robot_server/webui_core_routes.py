"""Feature-owned aiohttp handlers for webui_core_routes.py."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

from robot_server.file_preview_api import file_preview
from robot_server.voice.aliyun_realtime_asr import RealtimeAsrError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


from robot_server import app as composition_root
from robot_server.app_keys import (
    AGENT_RUNTIME_KEY,
    LOCAL_MEDIA_SERVICE_KEY,
    LOCAL_UI_STATE_SERVICE_KEY,
    ROBOT_IDENTITY_SERVICE_KEY,
    ROBOT_SERVER_CONFIG_KEY,
)
from robot_server.route_support import identity_token as _identity_token, json_body as _json_body

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
        config = composition_root.load_config(
            request.app[ROBOT_SERVER_CONFIG_KEY].deployment_config_path
        )
        try:
            await composition_root.probe_bailian_realtime_asr(
                config.providers.dashscope.api_key or ""
            )
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

HANDLERS = {'_health': _health, '_bootstrap': _bootstrap, '_webui_bootstrap': _webui_bootstrap, '_webui_login': _webui_login, '_webui_logout': _webui_logout, '_webui_login_preflight': _webui_login_preflight, '_media': _media, '_ui_sessions': _ui_sessions, '_ui_session_thread': _ui_session_thread, '_ui_file_preview': _ui_file_preview, '_ui_delete_session': _ui_delete_session, '_ui_sidebar_state': _ui_sidebar_state, '_ui_update_sidebar_state': _ui_update_sidebar_state, '_ui_skills': _ui_skills, '_ui_skill_detail': _ui_skill_detail, '_ui_workspaces': _ui_workspaces, '_ui_commands': _ui_commands}
