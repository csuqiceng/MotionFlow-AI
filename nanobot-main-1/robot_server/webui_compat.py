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
from loguru import logger

from ai_runtime import AgentRuntime, RuntimeEvent, RuntimeRequest
from nanobot.audio.transcription import (
    TranscriptionIngressError,
    resolve_transcription_config,
    transcribe_audio_data_url,
)
from nanobot.config.loader import load_config
from robot_server.identity_api import RobotIdentityService
from robot_server.voice.aliyun_realtime_asr import BailianRealtimeAsrSession, RealtimeAsrError
from robot_server.voice.aliyun_realtime_tts import BailianRealtimeTts, RealtimeTtsError


async def legacy_webui_websocket(
    request: web.Request, *, runtime: AgentRuntime | None, identity: RobotIdentityService
) -> web.StreamResponse:
    if runtime is None:
        return web.json_response({"error": "agent runtime is unavailable"}, status=503)
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)
    streamed_conversations: set[str] = set()
    voice_sessions: dict[str, BailianRealtimeAsrSession] = {}
    tts_tasks: dict[str, tuple[BailianRealtimeTts, asyncio.Task[None]]] = {}

    async def emit_voice(frame: dict[str, Any]) -> None:
        if frame.get("event") == "voice_final":
            logger.info(
                "Realtime ASR final emitted for chat {} session {} ({} characters)",
                frame.get("chat_id"), frame.get("voice_session_id"), len(str(frame.get("text") or "")),
            )
        elif frame.get("event") == "voice_error":
            logger.warning(
                "Realtime ASR error emitted for chat {} session {}: {}",
                frame.get("chat_id"), frame.get("voice_session_id"), frame.get("detail"),
            )
        if not socket.closed:
            await socket.send_json(frame)

    async def send_events() -> None:
        async for event in runtime.subscribe():
            frame = legacy_webui_frame_for_runtime_event(event, streamed_conversations)
            if frame is not None:
                await socket.send_json(frame)
            if event.kind == "final":
                text = event.payload.get("content", "")
                if isinstance(text, str) and text.strip():
                    await start_tts(event.conversation_id, text)

    async def stop_tts(chat_id: str) -> None:
        current = tts_tasks.pop(chat_id, None)
        if current is None:
            return
        session, task = current
        await session.cancel()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def start_tts(chat_id: str, text: str) -> None:
        await stop_tts(chat_id)
        config = load_config()
        session = BailianRealtimeTts(
            api_key=config.providers.dashscope.api_key or "", chat_id=chat_id, emit=emit_voice,
        )

        async def run() -> None:
            try:
                await session.synthesize(text)
            except asyncio.CancelledError:
                raise
            except RealtimeTtsError as exc:
                await emit_voice({"event": "tts_error", "chat_id": chat_id, "detail": str(exc)})
            finally:
                if tts_tasks.get(chat_id, (None, None))[0] is session:
                    tts_tasks.pop(chat_id, None)

        task = asyncio.create_task(run(), name=f"tts-{chat_id}")
        tts_tasks[chat_id] = (session, task)

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
            if kind == "tts_cancel":
                await stop_tts(conversation_id)
                continue
            if kind == "voice_start":
                await stop_tts(conversation_id)
                voice_session_id = envelope.get("voice_session_id")
                if not _valid_voice_session_id(voice_session_id):
                    await socket.send_json({"event": "voice_error", "chat_id": conversation_id, "detail": "voice_invalid_request"})
                    continue
                previous = voice_sessions.pop(voice_session_id, None)
                if previous is not None:
                    await previous.close()
                config = load_config()
                logger.info("Realtime ASR start requested for chat {} session {}", conversation_id, voice_session_id)
                asr: BailianRealtimeAsrSession | None = None
                connection_error: RealtimeAsrError | None = None
                # Cancelling a long TTS turn and opening ASR back-to-back can
                # briefly race at the provider edge. Retry the one transient
                # connection failure; all other provider errors remain visible.
                for attempt in range(2):
                    asr = BailianRealtimeAsrSession(
                        api_key=config.providers.dashscope.api_key or "",
                        chat_id=conversation_id,
                        session_id=voice_session_id,
                        emit=emit_voice,
                    )
                    try:
                        await asr.connect()
                        connection_error = None
                        break
                    except RealtimeAsrError as exc:
                        connection_error = exc
                        await asr.close()
                        logger.warning(
                            "Realtime ASR start failed for chat {} (attempt {}): {}",
                            conversation_id, attempt + 1, exc,
                        )
                        if str(exc) != "voice_connection_failed" or attempt == 1:
                            break
                        await asyncio.sleep(0.25)
                if connection_error is not None or asr is None:
                    await socket.send_json({
                        "event": "voice_error", "chat_id": conversation_id,
                        "voice_session_id": voice_session_id,
                        "detail": str(connection_error or "voice_connection_failed"),
                    })
                    continue
                voice_sessions[voice_session_id] = asr
                logger.info("Realtime ASR ready for chat {} session {}", conversation_id, voice_session_id)
                await socket.send_json({
                    "event": "voice_started", "chat_id": conversation_id,
                    "voice_session_id": voice_session_id,
                })
                continue
            if kind in {"voice_audio", "voice_stop", "voice_cancel"}:
                voice_session_id = envelope.get("voice_session_id")
                asr = voice_sessions.get(voice_session_id) if isinstance(voice_session_id, str) else None
                if asr is None:
                    logger.warning(
                        "Realtime ASR {} received for missing session {} in chat {}",
                        kind, voice_session_id, conversation_id,
                    )
                    await socket.send_json({
                        "event": "voice_error", "chat_id": conversation_id,
                        "voice_session_id": voice_session_id,
                        "detail": "voice_session_not_found",
                    })
                    continue
                try:
                    if kind == "voice_audio":
                        await asr.append_audio(envelope.get("audio"))
                    elif kind == "voice_stop":
                        chunks, bytes_received = asr.audio_stats
                        logger.info(
                            "Realtime ASR finish requested for chat {} session {} ({} chunks, {} PCM bytes)",
                            conversation_id, voice_session_id, chunks, bytes_received,
                        )
                        await asr.finish()
                    else:
                        logger.info("Realtime ASR cancelled for chat {} session {}", conversation_id, voice_session_id)
                        voice_sessions.pop(voice_session_id, None)
                        await asr.close()
                except RealtimeAsrError as exc:
                    voice_sessions.pop(voice_session_id, None)
                    logger.warning("Realtime ASR turn failed for chat {}: {}", conversation_id, exc)
                    await socket.send_json({
                        "event": "voice_error", "chat_id": conversation_id,
                        "voice_session_id": voice_session_id, "detail": str(exc),
                    })
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
        await asyncio.gather(*(session.close() for session in voice_sessions.values()), return_exceptions=True)
        await asyncio.gather(*(stop_tts(chat_id) for chat_id in list(tts_tasks)), return_exceptions=True)
    return socket


def _valid_voice_session_id(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 80 and value.replace("-", "").isalnum()


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
        return {
            "event": "stream_end",
            "chat_id": chat_id,
            "resuming": bool(event.payload.get("resuming", False)),
        }
    if event.kind == "status":
        return {
            "event": "message",
            "chat_id": chat_id,
            "text": event.payload.get("content", "正在处理…"),
            "kind": "progress",
        }
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
        frame: dict[str, Any] = {"event": "turn_end", "chat_id": chat_id}
        latency_ms = event.payload.get("latency_ms")
        if isinstance(latency_ms, (int, float)) and latency_ms >= 0:
            frame["latency_ms"] = round(latency_ms)
        return frame
    return None
