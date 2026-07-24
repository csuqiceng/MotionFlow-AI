"""Compatibility WebSocket adapter for the retained React WebUI.

This module translates the former browser protocol at the edge.  The public
robot runtime continues to expose only transport-neutral conversation IDs.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from aiohttp import web

from ai_runtime import AgentRuntime, RuntimeEvent, RuntimeRequest
from nanobot.audio.transcription import (
    TranscriptionIngressError,
    resolve_transcription_config,
    transcribe_audio_data_url,
)
from nanobot.config.loader import load_config
from robot_server.identity_api import RobotIdentityService


async def legacy_webui_websocket(
    request: web.Request, *, runtime: AgentRuntime | None, identity: RobotIdentityService
) -> web.StreamResponse:
    if runtime is None:
        return web.json_response({"error": "agent runtime is unavailable"}, status=503)
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)
    streamed_conversations: set[str] = set()

    async def send_events() -> None:
        async for event in runtime.subscribe():
            frame = legacy_webui_frame_for_runtime_event(event, streamed_conversations)
            if frame is not None:
                await socket.send_json(frame)

    sender = asyncio.create_task(send_events())
    try:
        await socket.send_json({"event": "ready", "client_id": "robot-server"})
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
            if kind == "auth":
                session, error = identity.require_session(str(envelope.get("user_token") or ""))
                if error is not None:
                    await socket.close(code=1008, message=b"invalid user token")
                    break
                await socket.send_json({
                    "event": "auth_ok", "user_id": session["user_id"], "role": session["role"],
                })
                continue
            if kind == "new_chat":
                await socket.send_json({"event": "attached", "chat_id": str(uuid.uuid4())})
                continue
            conversation_id = envelope.get("chat_id")
            if not isinstance(conversation_id, str) or not conversation_id.strip():
                await socket.send_json({"event": "error", "detail": "chat_id_required"})
                continue
            if kind == "attach":
                await socket.send_json({"event": "attached", "chat_id": conversation_id})
                continue
            if kind == "cancel":
                cancelled = await runtime.cancel(conversation_id)
                await socket.send_json({"event": "cancelled", "chat_id": conversation_id, "count": cancelled})
                continue
            if kind == "transcribe_audio":
                await socket.send_json(await _transcription_frame(envelope))
                continue
            if kind != "message" or not isinstance(envelope.get("content"), str):
                await socket.send_json({"event": "error", "detail": "message_content_required"})
                continue
            try:
                await runtime.submit(RuntimeRequest(
                    conversation_id=conversation_id,
                    actor_id="local-operator",
                    content=envelope["content"],
                    stream=True,
                    request_id=envelope.get("turn_id") if isinstance(envelope.get("turn_id"), str) else None,
                ))
            except (RuntimeError, ValueError) as exc:
                await socket.send_json({"event": "error", "chat_id": conversation_id, "detail": str(exc)})
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
    return socket


async def _transcription_frame(envelope: dict[str, Any]) -> dict[str, Any]:
    """Preserve the old WebUI's voice-recording WebSocket contract."""
    request_id = envelope.get("request_id")
    valid_id = isinstance(request_id, str) and 0 < len(request_id) <= 80
    if not valid_id:
        return {"event": "transcription_error", "detail": "invalid_request"}
    try:
        text = await transcribe_audio_data_url(
            envelope.get("data_url"),
            resolve_transcription_config(load_config()),
            duration_ms=envelope.get("duration_ms"),
        )
    except TranscriptionIngressError as exc:
        return {
            "event": "transcription_error", "request_id": request_id,
            "detail": exc.detail, **exc.extra,
        }
    return {"event": "transcription_result", "request_id": request_id, "text": text}


def legacy_webui_frame_for_runtime_event(
    event: RuntimeEvent, streamed_conversations: set[str]
) -> dict[str, Any] | None:
    """Translate runtime events to the retained React stream semantics.

    The old UI renders ``delta`` eagerly and treats ``message`` as a complete
    non-streaming answer.  Sending both for one turn duplicates text and makes
    the activity/thinking timeline appear out of order, so a streamed final is
    represented only by ``turn_end``.
    """
    chat_id = event.conversation_id
    if event.kind == "delta":
        streamed_conversations.add(chat_id)
        return {"event": "delta", "chat_id": chat_id, "text": event.payload.get("content", "")}
    if event.kind == "stream_end":
        return {"event": "stream_end", "chat_id": chat_id}
    if event.kind == "reasoning_delta":
        return {"event": "reasoning_delta", "chat_id": chat_id, "text": event.payload.get("content", "")}
    if event.kind == "reasoning_end":
        return {"event": "reasoning_end", "chat_id": chat_id}
    if event.kind == "file_edit":
        return {"event": "file_edit", "chat_id": chat_id, "edits": event.payload.get("edits", [])}
    if event.kind == "tool_progress":
        # Tool activity is the only remaining use of this event.  It is kept
        # separate from the dedicated reasoning events above so the retained
        # UI cannot accidentally render model thought as "Working …" traces.
        frame: dict[str, Any] = {
            "event": "message",
            "chat_id": chat_id,
            "text": event.payload.get("content", ""),
            "kind": "tool_hint" if event.payload.get("tool_hint") else "progress",
        }
        if event.payload.get("tool_events"):
            frame["tool_events"] = event.payload["tool_events"]
        return frame
    if event.kind == "final":
        if chat_id in streamed_conversations:
            return None
        return {"event": "message", "chat_id": chat_id, "text": event.payload.get("content", "")}
    if event.kind == "error":
        return {"event": "error", "chat_id": chat_id, "detail": event.payload.get("message", "runtime_error")}
    if event.kind == "turn_end":
        streamed_conversations.discard(chat_id)
        return {"event": "turn_end", "chat_id": chat_id}
    return None
