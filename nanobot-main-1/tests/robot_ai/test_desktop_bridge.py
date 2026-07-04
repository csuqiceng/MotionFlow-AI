from robot_ai.bridge import RobotApi


class FakeBot:
    async def run(self, text: str) -> str:
        return f"echo: {text}"


class FakeTTSAdapter:
    def __init__(self, config) -> None:
        self.config = config

    async def synthesize(self, text: str) -> bytes:
        return f"{self.config.provider}:{text}".encode()


class EnabledTTSConfig:
    enabled = True
    provider = "edge"
    voice = "zh-CN-YunxiNeural"


class ConfigWithTTS:
    tts = EnabledTTSConfig()


def test_health_reports_bridge_and_robot_state() -> None:
    api = RobotApi()

    result = api.health()

    assert result["ok"] is True
    assert result["state"] == "healthy"
    assert result["data"]["bridge"] == "pywebview"
    assert result["data"]["robot_state"]["mode"] == "idle"


def test_robot_controls_work_without_llm() -> None:
    api = RobotApi()

    move_result = api.move_axis("x", 10.0)
    state = api.get_robot_state()
    home_result = api.home()
    stop_result = api.stop()

    assert move_result["ok"] is True
    assert state["data"]["robot_state"]["axes_mm"]["x"] == 10.0
    assert home_result["state"] == "home_completed"
    assert stop_result["state"] == "stopped"


def test_send_message_uses_injected_bot_factory() -> None:
    api = RobotApi(bot_factory=lambda: FakeBot())

    result = api.send_message("hello")

    assert result["ok"] is True
    assert result["state"] == "chat_completed"
    assert result["data"]["text"] == "echo: hello"


def test_send_message_returns_clear_error_when_sdk_unavailable() -> None:
    def missing_bot():
        raise ModuleNotFoundError("No module named 'pydantic'")

    api = RobotApi(bot_factory=missing_bot)

    result = api.send_message("hello")

    assert result["ok"] is False
    assert result["state"] == "chat_unavailable"
    assert "nanobot SDK is unavailable" in result["message"]


def test_send_message_rejects_empty_text_without_calling_bot() -> None:
    called = False

    def bot_factory():
        nonlocal called
        called = True
        return FakeBot()

    api = RobotApi(bot_factory=bot_factory)

    result = api.send_message("   ")

    assert result["ok"] is False
    assert result["state"] == "empty_message"
    assert called is False


def test_voice_state_reports_resolved_tts_config() -> None:
    api = RobotApi(app_config=ConfigWithTTS())

    result = api.get_voice_state()

    assert result["ok"] is True
    assert result["state"] == "voice_ready"
    assert result["data"]["tts"]["enabled"] is True
    assert result["data"]["tts"]["provider"] == "edge_tts"
    assert result["data"]["tts"]["provider_configured"] is True
    assert result["data"]["tts"]["voice"] == "zh-CN-YunxiNeural"


def test_synthesize_speech_returns_base64_audio_with_injected_adapter() -> None:
    api = RobotApi(app_config=ConfigWithTTS(), tts_adapter_factory=FakeTTSAdapter)

    result = api.synthesize_speech(" hello ")

    assert result["ok"] is True
    assert result["state"] == "tts_completed"
    assert result["data"]["audio_base64"] == "ZWRnZV90dHM6aGVsbG8="
    assert result["data"]["mime_type"] == "audio/mpeg"
    assert result["data"]["provider"] == "edge_tts"


def test_synthesize_speech_reports_disabled_without_calling_adapter() -> None:
    called = False

    def adapter_factory(config):
        nonlocal called
        called = True
        return FakeTTSAdapter(config)

    api = RobotApi(tts_adapter_factory=adapter_factory)

    result = api.synthesize_speech("hello")

    assert result["ok"] is False
    assert result["state"] == "tts_disabled"
    assert called is False


def test_synthesize_speech_rejects_empty_text() -> None:
    api = RobotApi(app_config=ConfigWithTTS(), tts_adapter_factory=FakeTTSAdapter)

    result = api.synthesize_speech("  ")

    assert result["ok"] is False
    assert result["state"] == "tts_empty_text"
