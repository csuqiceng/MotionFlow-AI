"""Alibaba Cloud Bailian CosyVoice bridge for assistant speech playback."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

TTS_URL = "wss://llm-i1wy573whim6m2p4.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
TTS_MODEL = "cosyvoice-v3-flash"
TTS_VOICE = "longanyang"
TTS_SAMPLE_RATE = 24_000
TTS_INPUT_CHUNK_CHARS = 240

_SPEECH_REPLACEMENTS = {
    "dry-run": "演练模式",
    "Dry-run": "演练模式",
    "ZMotion": "运动控制器",
    "WebUI": "控制界面",
    "Home": "原点",
    "home": "原点",
}

VoiceFrameSender = Callable[[dict[str, Any]], Awaitable[None]]


class RealtimeTtsError(RuntimeError):
    """A provider error safe to expose to the local WebUI."""


def speech_text_from_markdown(value: str) -> str:
    """Produce Chinese-first, natural speech text from a rendered reply.

    The chat UI keeps complete Markdown, code and technical identifiers.  Those
    are useful on-screen but sound wrong when read aloud (for example ``##``
    and raw API names).  The speech channel is deliberately presentation-only:
    it retains prose and numbers while dropping markup, URLs and untranslated
    English identifiers.
    """
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"!\[[^]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    for source, replacement in _SPEECH_REPLACEMENTS.items():
        text = text.replace(source, replacement)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[ \t]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[ \t]*\d+[.)、]\s*", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    text = text.replace("|", "，")
    text = re.sub(r"^[\s:|_-]+$", "", text, flags=re.MULTILINE)
    # Model/tool names and source-code fragments are not meaningful speech for
    # an operator.  Keep CJK text and numeric values, but avoid an English TTS
    # voice switching in the middle of a Chinese response.
    text = re.sub(r"[A-Za-z]+(?:[._:/-][A-Za-z0-9._:/-]+)*", "", text)
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r" *\n+ *", "。", text)
    text = re.sub(r"[，。；：！？]{2,}", lambda match: match.group(0)[-1], text)
    return text.strip(" ，。；：！？")


def chunk_speech_text(text: str, maximum: int = TTS_INPUT_CHUNK_CHARS) -> list[str]:
    """Split long prose at Chinese sentence boundaries for duplex CosyVoice."""
    if len(text) <= maximum:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[。！？；])", text):
        if not sentence:
            continue
        while len(sentence) > maximum:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:maximum])
            sentence = sentence[maximum:]
        if current and len(current) + len(sentence) > maximum:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks


class BailianRealtimeTts:
    """One cancelable CosyVoice task, streamed as 24 kHz PCM to the browser."""

    def __init__(self, *, api_key: str, chat_id: str, emit: VoiceFrameSender) -> None:
        self._api_key = api_key
        self._chat_id = chat_id
        self._emit = emit
        self._task_id = str(uuid.uuid4())
        self._http: ClientSession | None = None
        self._socket: ClientWebSocketResponse | None = None
        self._closed = False

    async def synthesize(self, text: str) -> None:
        if not self._api_key.strip():
            raise RealtimeTtsError("voice_not_configured")
        speech_text = speech_text_from_markdown(text)
        if not speech_text:
            return
        self._http = ClientSession()
        try:
            self._socket = await self._http.ws_connect(
                TTS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                heartbeat=20,
                timeout=15,
            )
            await self._send("run-task", {
                "task_group": "audio",
                "task": "tts",
                "function": "SpeechSynthesizer",
                "model": TTS_MODEL,
                "parameters": {
                    "text_type": "PlainText",
                    "voice": TTS_VOICE,
                    "format": "pcm",
                    "sample_rate": TTS_SAMPLE_RATE,
                    "volume": 50,
                    "rate": 1,
                    "pitch": 1,
                },
                "input": {},
            })
            await self._wait_for("task-started")
            # CosyVoice duplex input is incremental.  Long replies must be
            # sent in bounded chunks before ``finish-task``; a single oversized
            # input can be cut off by the service while the UI still displays
            # the complete answer.
            for chunk in chunk_speech_text(speech_text):
                await self._send("continue-task", {"input": {"text": chunk}})
            await self._send("finish-task", {"input": {}})
            await self._emit({"event": "tts_started", "chat_id": self._chat_id, "task_id": self._task_id,
                              "sample_rate": TTS_SAMPLE_RATE})
            await self._receive_audio()
        except asyncio.CancelledError:
            raise
        except RealtimeTtsError:
            raise
        except Exception as exc:
            raise RealtimeTtsError("tts_provider_error") from exc
        finally:
            await self.close()

    async def cancel(self) -> None:
        if self._closed or self._socket is None:
            return
        with contextlib.suppress(Exception):
            await self._send("finish-task", {"input": {"directive": "cancel"}})
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        socket, self._socket = self._socket, None
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()
        http, self._http = self._http, None
        if http is not None:
            with contextlib.suppress(Exception):
                await http.close()

    async def _wait_for(self, expected_event: str) -> None:
        assert self._socket is not None
        while True:
            message = await self._socket.receive(timeout=15)
            if message.type is not WSMsgType.TEXT:
                continue
            frame = _json_object(message.data)
            event = _event_name(frame)
            if event == expected_event:
                return
            if event == "task-failed":
                raise RealtimeTtsError("tts_provider_error")

    async def _receive_audio(self) -> None:
        assert self._socket is not None
        async for message in self._socket:
            if message.type is WSMsgType.BINARY:
                if message.data:
                    await self._emit({
                        "event": "tts_audio", "chat_id": self._chat_id,
                        "task_id": self._task_id,
                        "audio": base64.b64encode(message.data).decode("ascii"),
                        "sample_rate": TTS_SAMPLE_RATE,
                    })
                continue
            if message.type is not WSMsgType.TEXT:
                break
            event = _event_name(_json_object(message.data))
            if event == "task-finished":
                await self._emit({"event": "tts_end", "chat_id": self._chat_id, "task_id": self._task_id})
                return
            if event == "task-failed":
                raise RealtimeTtsError("tts_provider_error")

    async def _send(self, action: str, payload: dict[str, Any]) -> None:
        if self._socket is None:
            raise RealtimeTtsError("tts_session_closed")
        await self._socket.send_json({
            "header": {"action": action, "task_id": self._task_id, "streaming": "duplex"},
            "payload": payload,
        })


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _event_name(frame: dict[str, Any]) -> str:
    header = frame.get("header")
    return header.get("event", "") if isinstance(header, dict) else ""
