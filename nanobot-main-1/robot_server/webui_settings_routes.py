"""Feature-owned aiohttp handlers for webui_settings_routes.py."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from aiohttp import web

from robot_server.webui_compat import legacy_webui_websocket

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


from robot_server.app_keys import (
    AGENT_RUNTIME_KEY,
    LOCAL_APPS_SERVICE_KEY,
    LOCAL_AUTOMATION_SERVICE_KEY,
    LOCAL_SETTINGS_SERVICE_KEY,
    ROBOT_IDENTITY_SERVICE_KEY,
    ROBOT_SERVER_CONFIG_KEY,
)

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

HANDLERS = {'_session_automations': _session_automations, '_automations': _automations, '_automation_action': _automation_action, '_automation_enable': _automation_enable, '_automation_disable': _automation_disable, '_automation_delete': _automation_delete, '_automation_run': _automation_run, '_automation_update': _automation_update, '_query_values': _query_values, '_settings': _settings, '_settings_usage': _settings_usage, '_settings_version_check': _settings_version_check, '_settings_web_search_update': _settings_web_search_update, '_settings_network_safety_update': _settings_network_safety_update, '_settings_image_generation_update': _settings_image_generation_update, '_settings_transcription_update': _settings_transcription_update, '_cli_apps': _cli_apps, '_cli_apps_action': _cli_apps_action, '_cli_apps_install': _cli_apps_install, '_cli_apps_update': _cli_apps_update, '_cli_apps_uninstall': _cli_apps_uninstall, '_cli_apps_test': _cli_apps_test, '_mcp_values': _mcp_values, '_mcp_presets': _mcp_presets, '_mcp_action': _mcp_action, '_mcp_enable': _mcp_enable, '_mcp_remove': _mcp_remove, '_mcp_test': _mcp_test, '_mcp_custom': _mcp_custom, '_mcp_import': _mcp_import, '_mcp_tools': _mcp_tools, '_webui_socket': _webui_socket}
