"""Alibaba Cloud Bailian realtime-ASR bridge.

The browser only speaks to the loopback robot server.  This module owns the
provider WebSocket, keeping the embedded API key out of renderer processes and
allowing the desktop host bridge to continue using JSON text frames.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

ASR_MODEL = "qwen3-asr-flash-realtime"
ASR_URL = (
    "wss://llm-i1wy573whim6m2p4.cn-beijing.maas.aliyuncs.com/"
    "api-ws/v1/realtime?model=" + ASR_MODEL
)
MAX_AUDIO_CHUNK_BYTES = 96 * 1024

VoiceFrameSender = Callable[[dict[str, Any]], Awaitable[None]]


class RealtimeAsrError(RuntimeError):
    """A provider or protocol error safe to show in the local UI."""


def _session_update_frame() -> dict[str, Any]:
    """Return the shared ASR session setup frame.

    Keeping the probe and live-session setup identical prevents the login
    readiness badge from validating a different endpoint or capability than the
    one the operator uses after sign-in.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "type": "session.update",
        "session": {
            "input_audio_format": "pcm",
            "sample_rate": 16000,
            "input_audio_transcription": {"language": "zh"},
            "turn_detection": None,
        },
    }


async def probe_bailian_realtime_asr(api_key: str) -> None:
    """Verify that the configured realtime ASR endpoint accepts a session.

    A WebSocket upgrade alone is not sufficient: credentials and model access
    are reported by the provider after ``session.update``.  The probe sends no
    audio and immediately closes after the setup acknowledgement, so opening
    the login page cannot create a transcript or speech task.
    """
    if not api_key.strip():
        raise RealtimeAsrError("voice_not_configured")
    try:
        async with ClientSession() as http:
            async with http.ws_connect(
                ASR_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "OpenAI-Beta": "realtime=v1",
                },
                heartbeat=20,
                timeout=10,
            ) as socket:
                await socket.send_json(_session_update_frame())
                for _ in range(8):
                    message = await socket.receive(timeout=10)
                    if message.type is WSMsgType.TEXT:
                        frame = message.json()
                        if not isinstance(frame, dict):
                            continue
                        event = frame.get("type")
                        if event == "session.updated":
                            return
                        if event == "error":
                            raise RealtimeAsrError("voice_provider_error")
                        continue
                    if message.type in {WSMsgType.CLOSED, WSMsgType.CLOSING, WSMsgType.ERROR}:
                        break
    except RealtimeAsrError:
        raise
    except Exception as exc:
        raise RealtimeAsrError("voice_connection_failed") from exc
    raise RealtimeAsrError("voice_connection_failed")


class BailianRealtimeAsrSession:
    """One manual push-to-talk Qwen-ASR realtime session."""

    def __init__(
        self,
        *,
        api_key: str,
        chat_id: str,
        session_id: str,
        emit: VoiceFrameSender,
    ) -> None:
        self._api_key = api_key
        self._chat_id = chat_id
        self._session_id = session_id
        self._emit = emit
        self._http: ClientSession | None = None
        self._socket: ClientWebSocketResponse | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._closed = False
        self._final_sent = False
        self._finish_requested = False
        self._pending_final_text: str | None = None
        self._audio_chunks = 0
        self._audio_bytes = 0

    @property
    def audio_stats(self) -> tuple[int, int]:
        """Number and size of browser PCM chunks accepted for this turn."""
        return self._audio_chunks, self._audio_bytes

    async def connect(self) -> None:
        if not self._api_key.strip():
            raise RealtimeAsrError("voice_not_configured")
        self._http = ClientSession()
        try:
            self._socket = await self._http.ws_connect(
                ASR_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "OpenAI-Beta": "realtime=v1",
                },
                heartbeat=20,
                timeout=15,
            )
            await self._send_provider(_session_update_frame())
            self._receiver = asyncio.create_task(self._receive(), name=f"asr-{self._session_id}")
        except Exception as exc:
            await self.close()
            raise RealtimeAsrError("voice_connection_failed") from exc

    async def append_audio(self, encoded_pcm: str) -> None:
        if self._closed or self._socket is None:
            raise RealtimeAsrError("voice_session_closed")
        if not isinstance(encoded_pcm, str) or not encoded_pcm:
            raise RealtimeAsrError("voice_audio_invalid")
        try:
            raw = base64.b64decode(encoded_pcm, validate=True)
        except Exception as exc:
            raise RealtimeAsrError("voice_audio_invalid") from exc
        if not raw or len(raw) > MAX_AUDIO_CHUNK_BYTES:
            raise RealtimeAsrError("voice_audio_invalid")
        self._audio_chunks += 1
        self._audio_bytes += len(raw)
        await self._send_provider({
            "event_id": self._event_id(),
            "type": "input_audio_buffer.append",
            "audio": encoded_pcm,
        })

    async def finish(self) -> None:
        # Do not forward a provider final until the browser has explicitly
        # ended the push-to-talk turn. Some provider paths complete early; if
        # we forwarded that frame first, the WebUI had no pending `stopVoice`
        # promise yet and would discard it before later timing out.
        self._finish_requested = True
        if self._closed or self._socket is None:
            await self._emit_final(self._pending_final_text or "")
            return
        try:
            if self._pending_final_text is not None:
                await self._emit_final(self._pending_final_text)
            await self._send_provider({"event_id": self._event_id(), "type": "input_audio_buffer.commit"})
            await self._send_provider({"event_id": self._event_id(), "type": "session.finish"})
        except Exception as exc:
            await self._emit_error("voice_finish_failed")
            await self.close()
            raise RealtimeAsrError("voice_finish_failed") from exc

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        receiver = self._receiver
        self._receiver = None
        if receiver is not None and receiver is not asyncio.current_task():
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver
        socket, self._socket = self._socket, None
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()
        http, self._http = self._http, None
        if http is not None:
            with contextlib.suppress(Exception):
                await http.close()

    async def _receive(self) -> None:
        try:
            assert self._socket is not None
            async for message in self._socket:
                if message.type is WSMsgType.TEXT:
                    await self._handle_provider_frame(message.json())
                elif message.type in {WSMsgType.CLOSED, WSMsgType.CLOSING, WSMsgType.ERROR}:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._emit_error("voice_provider_error")
        finally:
            if not self._final_sent:
                if self._finish_requested:
                    await self._emit_final(self._pending_final_text or "")
                else:
                    self._pending_final_text = self._pending_final_text or ""
            await self.close()

    async def _handle_provider_frame(self, frame: Any) -> None:
        if not isinstance(frame, dict):
            return
        event = frame.get("type")
        if event == "conversation.item.input_audio_transcription.text":
            text = self._text_from(frame)
            if text:
                await self._emit({
                    "event": "voice_partial", "chat_id": self._chat_id,
                    "voice_session_id": self._session_id, "text": text,
                })
            return
        if event == "conversation.item.input_audio_transcription.completed":
            text = self._text_from(frame)
            if self._finish_requested:
                await self._emit_final(text)
            else:
                self._pending_final_text = text
            return
        if event == "error":
            await self._emit_error("voice_provider_error")
            return
        if event == "session.finished":
            if self._finish_requested and not self._final_sent:
                await self._emit_final("")
            elif not self._finish_requested:
                self._pending_final_text = self._pending_final_text or ""
            return

    @staticmethod
    def _text_from(frame: dict[str, Any]) -> str:
        for key in ("transcript", "text", "delta"):
            value = frame.get(key)
            if isinstance(value, str):
                return value
        item = frame.get("item")
        if isinstance(item, dict):
            for key in ("transcript", "text"):
                value = item.get(key)
                if isinstance(value, str):
                    return value
        return ""

    async def _emit_final(self, text: str) -> None:
        if self._final_sent:
            return
        self._final_sent = True
        await self._emit({
            "event": "voice_final", "chat_id": self._chat_id,
            "voice_session_id": self._session_id, "text": text,
        })

    async def _emit_error(self, detail: str) -> None:
        await self._emit({
            "event": "voice_error", "chat_id": self._chat_id,
            "voice_session_id": self._session_id, "detail": detail,
        })

    async def _send_provider(self, frame: dict[str, Any]) -> None:
        if self._socket is None:
            raise RealtimeAsrError("voice_session_closed")
        await self._socket.send_json(frame)

    @staticmethod
    def _event_id() -> str:
        return f"evt_{uuid.uuid4().hex}"
