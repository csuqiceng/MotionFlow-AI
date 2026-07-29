"""Feature-owned aiohttp handlers for management_command_routes.py."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


from robot_server.app_keys import ROBOT_COMMAND_MANAGEMENT_KEY
from robot_server.route_support import identity_token as _identity_token, json_body as _json_body

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

HANDLERS = {'_management_commands': _management_commands, '_management_create_command': _management_create_command, '_management_command': _management_command, '_management_save_command': _management_save_command, '_management_delete_command': _management_delete_command, '_management_update_draft': _management_update_draft, '_management_start_draft': _management_start_draft, '_management_publish': _management_publish, '_management_archive': _management_archive, '_management_duplicate_command': _management_duplicate_command, '_management_bulk_archive_commands': _management_bulk_archive_commands}
