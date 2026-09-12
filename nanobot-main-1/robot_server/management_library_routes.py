"""Feature-owned aiohttp handlers for management_library_routes.py."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web
from robot_platform.application import RobotDiagnosticsQuery


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


from robot_server.app_keys import (
    PRODUCT_PROFILE_SERVICE_KEY,
    ROBOT_AUDIT_SERVICE_KEY,
    ROBOT_EXECUTION_SERVICE_KEY,
    ROBOT_DIAGNOSTICS_SERVICE_KEY,
    ROBOT_IDENTITY_SERVICE_KEY,
    ROBOT_LIBRARY_SERVICE_KEY,
    ROBOT_LIBRARY_TRANSFER_KEY,
    ROBOT_PLATFORM_KEY,
    ROBOT_POSITION_MAINTENANCE_KEY,
)
from robot_server.route_support import (
    identity_token as _identity_token,
    json_body as _json_body,
    robot_principal,
    service_error_response,
)

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
    principal, error = robot_principal(request)
    if error is not None:
        return service_error_response(error)
    response = await asyncio.to_thread(
        request.app[ROBOT_DIAGNOSTICS_SERVICE_KEY].query,
        RobotDiagnosticsQuery(principal=principal),
    )
    if response.ok:
        return web.json_response(response.payload)
    code = getattr(response.error, "code", "robot_status_unavailable")
    status = 403 if code == "engineer_required" else 503
    return web.json_response(
        {"error": {"code": code, "message": response.error.message}},
        status=status,
    )

async def _management_audit(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_AUDIT_SERVICE_KEY].list,
        _identity_token(request),
        limit=request.query.get("limit", "50"),
        before=request.query.get("before", ""),
    )
    return web.json_response(result, status=status)

async def _management_unresolved_tool_operations(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_AUDIT_SERVICE_KEY].list_unresolved_tool_operations,
        _identity_token(request),
    )
    return web.json_response(result, status=status)

async def _management_reconcile_tool_operation(request: web.Request) -> web.Response:
    status, result = await asyncio.to_thread(
        request.app[ROBOT_AUDIT_SERVICE_KEY].reconcile_tool_operation,
        _identity_token(request), await _json_body(request),
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

HANDLERS = {'_management_product_profile': _management_product_profile, '_management_update_product_profile': _management_update_product_profile, '_management_diagnostics': _management_diagnostics, '_management_audit': _management_audit, '_management_unresolved_tool_operations': _management_unresolved_tool_operations, '_management_reconcile_tool_operation': _management_reconcile_tool_operation, '_management_export_library': _management_export_library, '_management_import_library': _management_import_library, '_management_position_cleanup_preview': _management_position_cleanup_preview, '_management_position_cleanup_apply': _management_position_cleanup_apply, '_library_start_command_execution': _library_start_command_execution, '_library_start_flow_execution': _library_start_flow_execution, '_library_list_executions': _library_list_executions, '_library_execution': _library_execution, '_library_control_execution': _library_control_execution, '_library_components': _library_components, '_library_component': _library_component, '_library_commands': _library_commands, '_library_command': _library_command, '_library_flows': _library_flows, '_library_flow': _library_flow}
