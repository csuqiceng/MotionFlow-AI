import asyncio
from types import SimpleNamespace

import pytest

from nanobot.audio.tts import TTSError, resolve_tts_config, synthesize_text
from nanobot.audio.tts_registry import (
    get_tts_provider,
    resolve_tts_provider,
    tts_provider_names,
)
from nanobot.providers.tts import EdgeTTSProvider


class FakeAdapter:
    def __init__(self, config) -> None:
        self.config = config

    async def synthesize(self, text: str) -> bytes:
        return f"{self.config.provider}:{self.config.voice}:{text}".encode()


def test_tts_registry_exposes_expected_robot_voice_providers() -> None:
    assert tts_provider_names() == ("edge_tts", "azure_speech", "xfyun")
    assert get_tts_provider("edge_tts").requires_api_key is False
    assert get_tts_provider("xfyun").requires_api_key is True


def test_tts_registry_resolves_aliases() -> None:
    assert resolve_tts_provider("edge").name == "edge_tts"
    assert resolve_tts_provider("azure").name == "azure_speech"
    assert resolve_tts_provider("iflytek").name == "xfyun"
    assert resolve_tts_provider("unknown") is None
    assert resolve_tts_provider(None) is None


def test_resolve_tts_config_defaults_to_disabled_edge_voice() -> None:
    config = resolve_tts_config(object())

    assert config.enabled is False
    assert config.provider == "edge_tts"
    assert config.voice == "zh-CN-XiaoxiaoNeural"
    assert config.configured is True


def test_resolve_tts_config_uses_provider_settings_and_env(monkeypatch) -> None:
    monkeypatch.setenv("XFYUN_API_KEY", "env-xfyun-key")

    class TTSConfig:
        enabled = True
        provider = "iflytek"
        voice = "xiaoyan"
        audio_format = "mp3"

    class Config:
        tts = TTSConfig()
        providers = object()

    config = resolve_tts_config(Config())

    assert config.enabled is True
    assert config.provider == "xfyun"
    assert config.voice == "xiaoyan"
    assert config.audio_format == "mp3"
    assert config.api_key == "env-xfyun-key"
    assert config.configured is True


def test_synthesize_text_uses_injected_adapter() -> None:
    class TTSConfig:
        enabled = True
        provider = "edge"
        voice = "zh-CN-YunxiNeural"

    class Config:
        tts = TTSConfig()

    config = resolve_tts_config(Config())

    result = asyncio.run(synthesize_text("  hello robot  ", config, adapter_factory=FakeAdapter))

    assert result == b"edge_tts:zh-CN-YunxiNeural:hello robot"


def test_synthesize_text_reports_disabled_and_empty_text() -> None:
    config = resolve_tts_config(object())

    with pytest.raises(TTSError, match="empty_text"):
        asyncio.run(synthesize_text(" ", config, adapter_factory=FakeAdapter))

    with pytest.raises(TTSError, match="disabled"):
        asyncio.run(synthesize_text("hello", config, adapter_factory=FakeAdapter))


def test_edge_tts_provider_collects_audio_chunks(monkeypatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            self.text = text
            self.voice = voice

        async def stream(self):
            yield {"type": "WordBoundary", "data": b"ignored"}
            yield {"type": "audio", "data": b"one"}
            yield {"type": "audio", "data": b"two"}

    monkeypatch.setitem(
        __import__("sys").modules,
        "edge_tts",
        SimpleNamespace(Communicate=FakeCommunicate),
    )

    provider = EdgeTTSProvider(voice="zh-CN-YunxiNeural")

    assert asyncio.run(provider.synthesize("hello")) == b"onetwo"
