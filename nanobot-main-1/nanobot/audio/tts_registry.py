"""Registry for text-to-speech providers.

Provider-specific adapters live in ``nanobot.providers.tts``.  This module is
the lightweight source of truth for provider names, aliases, default voices,
credential env vars, and adapter class paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol


class TTSProviderAdapter(Protocol):
    """Runtime protocol implemented by provider-specific TTS adapters."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        voice: str | None = None,
        audio_format: str | None = None,
    ) -> None: ...

    async def synthesize(self, text: str) -> bytes: ...


@dataclass(frozen=True)
class TTSProviderSpec:
    name: str
    default_voice: str
    adapter: str
    aliases: tuple[str, ...] = ()
    default_audio_format: str = "mp3"
    default_api_base: str = ""
    env_key: str = ""
    requires_api_key: bool = True

    def load_adapter(self) -> type[TTSProviderAdapter]:
        module_name, _, class_name = self.adapter.partition(":")
        if not module_name or not class_name:
            raise RuntimeError(f"Invalid TTS adapter path: {self.adapter}")
        adapter = getattr(import_module(module_name), class_name)
        return adapter


TTS_PROVIDERS: tuple[TTSProviderSpec, ...] = (
    TTSProviderSpec(
        name="edge_tts",
        default_voice="zh-CN-XiaoxiaoNeural",
        adapter="nanobot.providers.tts:EdgeTTSProvider",
        aliases=("edge", "microsoft_edge"),
        default_audio_format="mp3",
        requires_api_key=False,
    ),
    TTSProviderSpec(
        name="azure_speech",
        default_voice="zh-CN-XiaoxiaoNeural",
        adapter="nanobot.providers.tts:AzureSpeechTTSProvider",
        aliases=("azure", "microsoft", "azure_tts"),
        default_audio_format="wav",
        env_key="AZURE_SPEECH_KEY",
        default_api_base="https://eastasia.tts.speech.microsoft.com",
    ),
    TTSProviderSpec(
        name="xfyun",
        default_voice="xiaoyan",
        adapter="nanobot.providers.tts:XfyunTTSProvider",
        aliases=("iflytek", "spark_tts", "xunfei"),
        default_audio_format="mp3",
        env_key="XFYUN_API_KEY",
    ),
)

_BY_NAME = {spec.name: spec for spec in TTS_PROVIDERS}
_BY_ALIAS = {alias: spec for spec in TTS_PROVIDERS for alias in spec.aliases}


def tts_provider_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in TTS_PROVIDERS)


def get_tts_provider(name: str) -> TTSProviderSpec | None:
    return _BY_NAME.get(name)


def resolve_tts_provider(value: Any) -> TTSProviderSpec | None:
    if not isinstance(value, str):
        return None
    name = value.strip().lower().replace("-", "_")
    return _BY_NAME.get(name) or _BY_ALIAS.get(name)
