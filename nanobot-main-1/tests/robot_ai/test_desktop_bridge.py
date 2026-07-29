from robot_ai.bridge import RobotApi
from robot_ai.backends.factory import RobotBackendConfig
from robot_ai.models import RobotState, ToolResult
from robot_ai.zmotion_operator_control import ZMotionOperatorRequest


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


class FakeReadOnlyBackend:
    def __init__(self, *, state: RobotState | None = None) -> None:
        self._state = state or RobotState(mode="disconnected", connected_real_device=False, alarms=["sdk path missing"])

    def get_state(self) -> RobotState:
        return self._state

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        return ToolResult.failure(state="real_control_disabled", message="read-only")

    def home(self) -> ToolResult:
        return ToolResult.failure(state="real_control_disabled", message="read-only")

    def stop(self) -> ToolResult:
        return ToolResult.failure(state="real_control_disabled", message="read-only")


def _operator_runner(**kwargs):
    request = kwargs["request"]
    return ToolResult.success(
        state=f"operator_{request.command}",
        message="operator command accepted",
        data={
            "request": {
                "command": request.command,
                "parameters": request.parameters,
                "execute_real": request.execute_real,
                "confirm_work_area_clear": request.confirm_work_area_clear,
                "confirm_estop_ready": request.confirm_estop_ready,
                "confirmation_code": request.confirmation_code,
            },
            "config_mode": kwargs["config"].mode,
        },
    ).to_dict()


def test_health_reports_bridge_and_robot_state() -> None:
    api = RobotApi()

    result = api.health()

    assert result["ok"] is True
    assert result["state"] == "healthy"
    assert result["data"]["bridge"] == "pywebview"
    assert result["data"]["robot_state"]["mode"] == "disconnected"
    assert result["data"]["backend"]["mode"] == "unavailable"
    assert result["data"]["backend"]["control_enabled"] is False


def test_status_reports_readonly_backend_metadata_for_desktop() -> None:
    config = RobotBackendConfig(
        mode="zmotion_readonly",
        controller_host="10.168.3.21",
        zmotion_wrapper_path="",
        zmotion_dll_dir="",
    )
    api = RobotApi(backend_config=config, backend_factory=lambda: FakeReadOnlyBackend())

    health = api.health()
    status = api.get_robot_state()

    backend = health["data"]["backend"]
    assert backend["mode"] == "zmotion_readonly"
    assert backend["controller_host"] == "10.168.3.21"
    assert backend["real_readonly"] is True
    assert backend["control_enabled"] is False
    assert backend["configuration_ready"] is False
    assert backend["missing_config"] == ["ROBOT_ZMOTION_WRAPPER_PATH", "ROBOT_ZMOTION_DLL_DIR"]
    assert "Real controller writes are disabled" in backend["message"]
    assert status["data"]["backend"] == backend


def test_readonly_backend_summary_maps_sdk_wrapper_failure_for_operator() -> None:
    config = RobotBackendConfig(
        mode="zmotion_readonly",
        controller_host="10.168.3.21",
        zmotion_wrapper_path="C:\\missing\\zauxdllPython.py",
        zmotion_dll_dir="C:\\sdk",
    )
    state = RobotState(
        mode="disconnected",
        connected_real_device=False,
        alarms=["controller_read_failed: ZMotionSdkError: ZMotion SDK wrapper not found: C:\\missing\\zauxdllPython.py"],
    )
    api = RobotApi(backend_config=config, backend_factory=lambda: FakeReadOnlyBackend(state=state))

    backend = api.health()["data"]["backend"]

    assert backend["diagnostic_state"] == "sdk_wrapper_missing"
    assert backend["configuration_ready"] is True
    assert backend["connected_real_device"] is False
    assert backend["message"] == "ZMotion SDK wrapper not found. Check ROBOT_ZMOTION_WRAPPER_PATH."


def test_readonly_backend_summary_maps_dll_and_controller_read_failures_for_operator() -> None:
    config = RobotBackendConfig(
        mode="zmotion_readonly",
        controller_host="10.168.3.21",
        zmotion_wrapper_path="C:\\sdk\\zauxdllPython.py",
        zmotion_dll_dir="C:\\missing_dll",
    )
    dll_state = RobotState(
        mode="disconnected",
        connected_real_device=False,
        alarms=["controller_read_failed: ZMotionSdkError: ZMotion SDK DLL directory not found: C:\\missing_dll"],
    )
    api = RobotApi(backend_config=config, backend_factory=lambda: FakeReadOnlyBackend(state=dll_state))

    dll_backend = api.health()["data"]["backend"]

    assert dll_backend["diagnostic_state"] == "sdk_dll_dir_missing"
    assert dll_backend["message"] == "ZMotion SDK DLL directory not found. Check ROBOT_ZMOTION_DLL_DIR."

    read_state = RobotState(
        mode="disconnected",
        connected_real_device=False,
        alarms=["controller_read_failed: TimeoutError: timed out"],
    )
    api = RobotApi(backend_config=config, backend_factory=lambda: FakeReadOnlyBackend(state=read_state))

    read_backend = api.health()["data"]["backend"]

    assert read_backend["diagnostic_state"] == "controller_read_failed"
    assert read_backend["message"] == "Controller read failed. Check power, network, host, and SDK compatibility."


def test_readonly_backend_summary_maps_controller_alarm_for_operator() -> None:
    config = RobotBackendConfig(
        mode="zmotion_readonly",
        controller_host="10.168.3.21",
        zmotion_wrapper_path="C:\\sdk\\zauxdllPython.py",
        zmotion_dll_dir="C:\\sdk",
    )
    state = RobotState(
        mode="alarm",
        connected_real_device=True,
        alarms=["controller_alarm", "alarm_detail_12"],
    )
    api = RobotApi(backend_config=config, backend_factory=lambda: FakeReadOnlyBackend(state=state))

    backend = api.health()["data"]["backend"]

    assert backend["diagnostic_state"] == "controller_alarm"
    assert backend["connected_real_device"] is True
    assert backend["message"] == "Controller alarm is active: controller_alarm, alarm_detail_12."


def test_readonly_diagnostics_bridge_requires_explicit_confirmation() -> None:
    calls: list[dict] = []

    def readonly_runner(**kwargs):
        calls.append(kwargs)
        return ToolResult.failure(
            state="readonly_diagnostics_confirmation_required",
            message="confirmation required",
            errors=[{"code": "readonly_diagnostics_confirmation_required"}],
        ).to_dict()

    api = RobotApi(readonly_diagnostics_runner=readonly_runner)

    result = api.run_zmotion_readonly_diagnostics(False)

    assert result["ok"] is False
    assert result["state"] == "readonly_diagnostics_confirmation_required"
    assert calls[0]["confirmed_readonly_diagnostics"] is False
    assert calls[0]["config"].mode == "simulation"


def test_readonly_diagnostics_bridge_enriches_result_for_status_card() -> None:
    config = RobotBackendConfig(
        mode="zmotion_readonly",
        controller_host="10.168.3.21",
        zmotion_wrapper_path="C:\\sdk\\zauxdllPython.py",
        zmotion_dll_dir="C:\\sdk",
    )
    calls: list[dict] = []

    def readonly_runner(**kwargs):
        calls.append(kwargs)
        return ToolResult.success(
            state="zmotion_readonly_smoke_passed",
            message="read-only ok",
            data={
                "robot_state": RobotState(mode="idle", connected_real_device=True).to_dict(),
            },
        ).to_dict()

    api = RobotApi(backend_config=config, readonly_diagnostics_runner=readonly_runner)

    result = api.run_zmotion_readonly_diagnostics(True)

    assert result["ok"] is True
    assert result["state"] == "zmotion_readonly_smoke_passed"
    assert calls[0]["confirmed_readonly_diagnostics"] is True
    assert calls[0]["config"] == config
    assert result["data"]["backend"]["mode"] == "zmotion_readonly"
    assert result["data"]["backend"]["diagnostic_state"] == "readonly_connected"
    assert result["data"]["backend"]["control_enabled"] is False


def test_desktop_bridge_exposes_only_restricted_operator_commands() -> None:
    api = RobotApi(operator_runner=_operator_runner)

    system = api.operator_system_control("pause")
    delay = api.operator_delay(0.25)
    io = api.operator_io(3, True, [2, 3, 4])
    linear = api.operator_linear_move({"x": 900, "y": 0, "z": 999, "rx": 0, "ry": 0, "rz": 0})
    path = api.operator_linear_path(
        [
            {"x": 900, "y": 0, "z": 999, "rx": 0, "ry": 0, "rz": 0},
            {"x": 901, "y": 0, "z": 999, "rx": 0, "ry": 0, "rz": 0},
        ]
    )

    assert system["data"]["request"]["command"] == "system"
    assert system["data"]["request"]["parameters"] == {"action": "pause"}
    assert delay["data"]["request"]["parameters"] == {"seconds": 0.25}
    assert io["data"]["request"]["parameters"] == {
        "io_number": 3,
        "enabled": True,
        "allowed_io_channels": [2, 3, 4],
    }
    assert linear["data"]["request"]["command"] == "linear_move"
    assert linear["data"]["request"]["parameters"]["target_pose"]["z"] == 999.0
    assert path["data"]["request"]["command"] == "linear_path"
    assert len(path["data"]["request"]["parameters"]["target_poses"]) == 2
    assert not hasattr(api, "move_axis")
    assert not hasattr(api, "home")
    assert not hasattr(api, "stop")


def test_operator_bridge_rejects_legacy_real_execution_credentials() -> None:
    calls: list[ZMotionOperatorRequest] = []

    def runner(**kwargs):
        calls.append(kwargs["request"])
        return ToolResult.success(state="operator_real").to_dict()

    api = RobotApi(operator_runner=runner)

    result = api.operator_system_control(
        "emergency_stop",
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code="EXECUTE_ZMOTION_REAL",
    )

    assert result["ok"] is False
    assert result["state"] == "staged_execution_required"
    assert calls == []


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
