"""Feature-owned aiohttp handlers for management_flow_routes.py."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


from robot_server.app_keys import ROBOT_FLOW_MANAGEMENT_KEY
from robot_server.route_support import identity_token as _identity_token, json_body as _json_body

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

HANDLERS = {'_management_flows': _management_flows, '_management_create_flow': _management_create_flow, '_management_flow': _management_flow, '_management_save_flow': _management_save_flow, '_management_delete_flow': _management_delete_flow, '_management_update_flow_draft': _management_update_flow_draft, '_management_start_flow_draft': _management_start_flow_draft, '_management_validate_flow': _management_validate_flow, '_management_publish_flow': _management_publish_flow, '_management_archive_flow': _management_archive_flow, '_management_duplicate_flow': _management_duplicate_flow, '_management_bulk_archive_flows': _management_bulk_archive_flows}
