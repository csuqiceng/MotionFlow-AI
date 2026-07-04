"""Text-to-speech provider adapters.

The concrete HTTP implementations are intentionally kept behind this small
adapter interface so desktop and WebUI code can use the same TTS service.
"""

from __future__ import annotations

from importlib import import_module


class BaseTTSProvider:
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        voice: str | None = None,
        audio_format: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.voice = voice
        self.audio_format = audio_format

    async def synthesize(self, text: str) -> bytes:
        raise NotImplementedError("TTS provider adapter is not implemented yet")


class EdgeTTSProvider(BaseTTSProvider):
    """Placeholder for the dependency-backed Microsoft Edge TTS adapter."""

    async def synthesize(self, text: str) -> bytes:
        try:
            edge_tts = import_module("edge_tts")
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "edge_tts is required for the edge_tts provider"
            ) from exc

        voice = self.voice or "zh-CN-XiaoxiaoNeural"
        communicate = edge_tts.Communicate(text, voice=voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        return b"".join(chunks)


class AzureSpeechTTSProvider(BaseTTSProvider):
    """Placeholder for the Azure Speech TTS adapter."""


class XfyunTTSProvider(BaseTTSProvider):
    """Placeholder for the iFlytek/XFYun TTS adapter."""
