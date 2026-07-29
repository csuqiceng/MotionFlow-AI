"""Feature-owned aiohttp handlers for product_robot_routes.py."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web

from robot_server.request_context import bind_principal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


from robot_server.app_keys import ROBOT_OPERATION_SERVICE_KEY, ROBOT_STATUS_SERVICE_KEY
from robot_server.route_support import (
    json_body as _json_body,
    robot_principal as _robot_principal,
    service_error_response as _service_error_response,
)

async def _robot_status(request: web.Request) -> web.Response:
    response = await asyncio.to_thread(
        request.app[ROBOT_STATUS_SERVICE_KEY].query,
    )
    if not response.ok or response.payload is None:
        return web.json_response({"error": "robot status unavailable"}, status=503)
    return web.json_response(response.payload)

async def _robot_plan(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.plan, await _json_body(request), principal=principal,
        )
    return web.json_response(result, status=status)

async def _robot_confirm(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.confirm, request.match_info["plan_id"], await _json_body(request),
            principal=principal,
        )
    return web.json_response(result, status=status)

async def _robot_execute(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.execute, request.match_info["plan_id"], body, principal=principal,
        )
    return web.json_response(result, status=status)

async def _robot_flow_plan(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.plan_flow, await _json_body(request), principal=principal,
        )
    return web.json_response(result, status=status)

async def _robot_flow_confirm(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    plan_id = body.get("plan_id") if isinstance(body, dict) else ""
    if not isinstance(plan_id, str) or not plan_id:
        return web.json_response({"error": {"code": 400, "message": "plan_id is required"}}, status=400)
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.confirm, plan_id, body, principal=principal,
        )
    return web.json_response(result, status=status)

async def _robot_flow_execute(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    plan_id = body.get("plan_id") if isinstance(body, dict) else ""
    if not isinstance(plan_id, str) or not plan_id:
        return web.json_response({"error": {"code": 400, "message": "plan_id is required"}}, status=400)
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.execute_flow, plan_id, body, principal=principal,
        )
    return web.json_response(result, status=status)

async def _robot_emergency_stop(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.emergency_stop, body, principal=principal,
        )
    return web.json_response(result, status=status)

async def _robot_run_flow(request: web.Request) -> web.Response:
    principal, error = _robot_principal(request)
    if error is not None:
        return _service_error_response(error)
    service = request.app[ROBOT_OPERATION_SERVICE_KEY]
    body = await _json_body(request)
    with bind_principal(principal):
        status, result = await asyncio.to_thread(
            service.run_flow, body, principal=principal,
        )
    return web.json_response(result, status=status)

HANDLERS = {'_robot_status': _robot_status, '_robot_plan': _robot_plan, '_robot_confirm': _robot_confirm, '_robot_execute': _robot_execute, '_robot_flow_plan': _robot_flow_plan, '_robot_flow_confirm': _robot_flow_confirm, '_robot_flow_execute': _robot_flow_execute, '_robot_emergency_stop': _robot_emergency_stop, '_robot_run_flow': _robot_run_flow}
