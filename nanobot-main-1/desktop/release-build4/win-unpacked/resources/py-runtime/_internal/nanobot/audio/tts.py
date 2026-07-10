"""Application-level text-to-speech service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from nanobot.audio.tts_registry import (
    TTSProviderAdapter,
    get_tts_provider,
    resolve_tts_provider,
)

TTSProviderName = str

_DEFAULT_PROVIDER: TTSProviderName = "edge_tts"


@dataclass(frozen=True)
class EffectiveTTSConfig:
    enabled: bool
    provider: TTSProviderName
    voice: str
    audio_format: str
    api_key: str = field(repr=False)
    api_base: str
    requires_api_key: bool = True

    @property
    def configured(self) -> bool:
        return not self.requires_api_key or bool(self.api_key)


class TTSError(Exception):
    """Stable TTS error surfaced to desktop and WebUI clients."""

    def __init__(self, detail: str, **extra: Any):
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


def _as_provider(value: Any) -> TTSProviderName | None:
    spec = resolve_tts_provider(value)
    return spec.name if spec else None


def _provider_config(config: Any, provider: str) -> Any:
    return getattr(getattr(config, "providers", None), provider, None)


def _resolve_tts_api_key(provider: str, provider_cfg: Any) -> str:
    api_key = getattr(provider_cfg, "api_key", None) if provider_cfg else None
    if api_key:
        return api_key

    spec = get_tts_provider(provider)
    env_key = spec.env_key if spec else ""
    return os.environ.get(env_key, "") if env_key else ""


def _resolve_tts_api_base(provider: str, provider_cfg: Any) -> str:
    api_base = getattr(provider_cfg, "api_base", None) if provider_cfg else None
    if api_base:
        return api_base

    spec = get_tts_provider(provider)
    return spec.default_api_base if spec else ""


def resolve_tts_config(config: Any) -> EffectiveTTSConfig:
    """Resolve top-level TTS settings from an app config-like object."""
    top = getattr(config, "tts", None)
    provider = _as_provider(getattr(top, "provider", None)) or _DEFAULT_PROVIDER
    spec = get_tts_provider(provider)
    if spec is None:
        provider = _DEFAULT_PROVIDER
        spec = get_tts_provider(provider)

    default_voice = spec.default_voice if spec else ""
    default_format = spec.default_audio_format if spec else "mp3"
    provider_cfg = _provider_config(config, provider)
    return EffectiveTTSConfig(
        enabled=bool(getattr(top, "enabled", False)),
        provider=provider,
        voice=(getattr(top, "voice", None) or default_voice).strip(),
        audio_format=(getattr(top, "audio_format", None) or default_format).strip(),
        api_key=_resolve_tts_api_key(provider, provider_cfg),
        api_base=_resolve_tts_api_base(provider, provider_cfg),
        requires_api_key=bool(spec.requires_api_key) if spec else True,
    )


async def synthesize_text(
    text: Any,
    config: EffectiveTTSConfig,
    *,
    adapter_factory: Callable[[EffectiveTTSConfig], TTSProviderAdapter] | None = None,
) -> bytes:
    """Synthesize text using the already-resolved TTS config."""
    if not isinstance(text, str) or not text.strip():
        raise TTSError("empty_text")
    if not config.enabled:
        raise TTSError("disabled")
    if not config.configured:
        raise TTSError("not_configured", provider=config.provider)

    adapter = adapter_factory(config) if adapter_factory else _load_adapter(config)
    audio = await adapter.synthesize(text.strip())
    if not audio:
        raise TTSError("empty_audio", provider=config.provider)
    return audio


def _load_adapter(config: EffectiveTTSConfig) -> TTSProviderAdapter:
    spec = get_tts_provider(config.provider)
    if spec is None:
        raise TTSError("unknown_provider", provider=config.provider)
    return spec.load_adapter()(
        api_key=config.api_key or None,
        api_base=config.api_base or None,
        voice=config.voice,
        audio_format=config.audio_format,
    )
