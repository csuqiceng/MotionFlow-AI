"""Feature-owned aiohttp handlers for product_identity_routes.py."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from aiohttp import web

from ai_runtime.engine_contract import AgentRequest
from robot_server.websocket_frames import webui_frame_for_runtime_event

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


from ai_runtime.identity import issue_verified_principal
from robot_server.app_keys import AGENT_RUNTIME_KEY, ROBOT_IDENTITY_SERVICE_KEY
from robot_server.route_support import (
    identity_token as _identity_token,
    json_body as _json_body,
    robot_principal as _robot_principal,
    service_error_response as _service_error_response,
)

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

async def _agent_websocket(request: web.Request) -> web.StreamResponse:
    runtime = request.app[AGENT_RUNTIME_KEY]
    if runtime is None:
        return web.json_response({"error": "agent runtime is unavailable"}, status=503)
    principal, auth_error = _robot_principal(request)
    if auth_error is not None:
        return _service_error_response(auth_error)
    assert principal is not None
    runtime_actor = f"{principal.role}:{principal.actor_id}"
    runtime_principal = issue_verified_principal(
        actor_id=principal.actor_id,
        role=principal.role,
        session_id=principal.session_id,
        auth_source=principal.auth_source,
    )
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
                    actor_id=runtime_actor,
                    content=envelope["content"],
                    stream=bool(envelope.get("stream", True)),
                    request_id=envelope.get("request_id") if isinstance(envelope.get("request_id"), str) else None,
                    principal=runtime_principal,
                ))
            except (RuntimeError, ValueError) as exc:
                await socket.send_json({"event": "error", "detail": str(exc)})
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
    return socket

HANDLERS = {'_identity_login': _identity_login, '_identity_logout': _identity_logout, '_identity_me': _identity_me, '_identity_users': _identity_users, '_identity_create_user': _identity_create_user, '_identity_update_user': _identity_update_user, '_identity_reset_password': _identity_reset_password, '_identity_delete_user': _identity_delete_user, '_identity_change_own_password': _identity_change_own_password, '_agent_websocket': _agent_websocket}
