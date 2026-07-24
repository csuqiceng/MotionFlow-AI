from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from robot_platform.backends.factory import RobotBackend, RobotBackendConfig, create_robot_backend
from robot_platform.models import ToolResult
from robot_platform.tools.robot_tools import RobotToolFacade
from robot_platform.zmotion_operator_control import (
    ZMotionOperatorRequest,
    run_zmotion_operator_command,
)
from robot_platform.zmotion_readonly_smoke import run_zmotion_readonly_smoke


BotFactory = Callable[[], Any]
TTSAdapterFactory = Callable[["EffectiveTTSConfig"], Any]
BackendFactory = Callable[[], RobotBackend]
ReadonlyDiagnosticsRunner = Callable[..., dict[str, Any]]
OperatorRunner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class EffectiveTTSConfig:
    """Platform-neutral voice settings passed to a host-provided adapter."""

    enabled: bool = False
    provider: str | None = None
    voice: str | None = None
    audio_format: str = "mp3"

    @property
    def configured(self) -> bool:
        return bool(self.provider)


class TTSError(Exception):
    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


class RobotApi:
    """pywebview-facing API bridge.

    Robot controls stay local and deterministic. Chat is lazy so the desktop
    shell can run even when nanobot provider dependencies are not installed yet.
    """

    def __init__(
        self,
        tools: RobotToolFacade | None = None,
        bot_factory: BotFactory | None = None,
        app_config: Any | None = None,
        tts_adapter_factory: TTSAdapterFactory | None = None,
        backend_factory: BackendFactory | None = None,
        backend_config: RobotBackendConfig | None = None,
        readonly_diagnostics_runner: ReadonlyDiagnosticsRunner = run_zmotion_readonly_smoke,
        operator_runner: OperatorRunner = run_zmotion_operator_command,
    ) -> None:
        self._backend_config = backend_config or RobotBackendConfig.from_env()
        backend = backend_factory() if tools is None and backend_factory is not None else None
        self._tools = tools or RobotToolFacade(backend=backend or create_robot_backend(self._backend_config))
        self._bot_factory = bot_factory or self._default_bot_factory
        self._app_config = app_config if app_config is not None else object()
        self._tts_adapter_factory = tts_adapter_factory
        self._readonly_diagnostics_runner = readonly_diagnostics_runner
        self._operator_runner = operator_runner
        self._bot: Any | None = None

    def health(self) -> dict:
        status = self._tools.robot_get_status()
        robot_state = status["data"]["robot_state"]
        return ToolResult.success(
            state="healthy",
            message="Robot desktop bridge is ready.",
            data={
                "bridge": "pywebview",
                "robot_state": robot_state,
                "backend": self._backend_summary(robot_state),
            },
        ).to_dict()

    def get_robot_state(self) -> dict:
        return self._with_backend_summary(self._tools.robot_get_status())

    def run_zmotion_readonly_diagnostics(self, confirmed_readonly_diagnostics: bool = False) -> dict:
        result = self._readonly_diagnostics_runner(
            confirmed_readonly_diagnostics=bool(confirmed_readonly_diagnostics),
            config=self._backend_config,
        )
        return self._with_backend_summary(result)

    def operator_system_control(
        self,
        action: str,
        execute_real: bool = False,
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        confirmation_code: str = "",
    ) -> dict:
        return self._run_operator(
            command="system",
            parameters={"action": str(action)},
            execute_real=execute_real,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            confirmation_code=confirmation_code,
        )

    def operator_delay(
        self,
        seconds: float,
        execute_real: bool = False,
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        confirmation_code: str = "",
    ) -> dict:
        return self._run_operator(
            command="delay",
            parameters={"seconds": float(seconds)},
            execute_real=execute_real,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            confirmation_code=confirmation_code,
        )

    def operator_io(
        self,
        io_number: int,
        enabled: bool,
        allowed_io_channels: list[int] | None = None,
        execute_real: bool = False,
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        confirmation_code: str = "",
    ) -> dict:
        return self._run_operator(
            command="io",
            parameters={
                "io_number": int(io_number),
                "enabled": bool(enabled),
                "allowed_io_channels": [int(value) for value in (allowed_io_channels or [])],
            },
            execute_real=execute_real,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            confirmation_code=confirmation_code,
        )

    def operator_linear_move(
        self,
        target_pose: dict[str, Any],
        speed_pct: float = 5.0,
        acceleration_pct: float = 5.0,
        deceleration_pct: float = 5.0,
        r_min: float = 200.0,
        r_max: float = 1800.0,
        z_min: float = 0.0,
        z_max: float = 2500.0,
        execute_real: bool = False,
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        confirmation_code: str = "",
    ) -> dict:
        return self._run_operator(
            command="linear_move",
            parameters={
                "target_pose": self._coerce_pose(target_pose),
                **self._motion_parameters(
                    speed_pct=speed_pct,
                    acceleration_pct=acceleration_pct,
                    deceleration_pct=deceleration_pct,
                    r_min=r_min,
                    r_max=r_max,
                    z_min=z_min,
                    z_max=z_max,
                ),
            },
            execute_real=execute_real,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            confirmation_code=confirmation_code,
        )

    def operator_linear_path(
        self,
        target_poses: list[dict[str, Any]],
        speed_pct: float = 5.0,
        acceleration_pct: float = 5.0,
        deceleration_pct: float = 5.0,
        r_min: float = 200.0,
        r_max: float = 1800.0,
        z_min: float = 0.0,
        z_max: float = 2500.0,
        execute_real: bool = False,
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        confirmation_code: str = "",
    ) -> dict:
        return self._run_operator(
            command="linear_path",
            parameters={
                "target_poses": [self._coerce_pose(pose) for pose in target_poses],
                **self._motion_parameters(
                    speed_pct=speed_pct,
                    acceleration_pct=acceleration_pct,
                    deceleration_pct=deceleration_pct,
                    r_min=r_min,
                    r_max=r_max,
                    z_min=z_min,
                    z_max=z_max,
                ),
            },
            execute_real=execute_real,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            confirmation_code=confirmation_code,
        )

    def get_voice_state(self) -> dict:
        tts_config = self._resolve_tts_config()
        return ToolResult.success(
            state="voice_ready",
            message="Voice bridge settings resolved.",
            data={
                "tts": {
                    "enabled": tts_config.enabled,
                    "provider": tts_config.provider,
                    "provider_configured": tts_config.configured,
                    "voice": tts_config.voice,
                    "audio_format": tts_config.audio_format,
                }
            },
        ).to_dict()

    def synthesize_speech(self, text: str) -> dict:
        tts_config = self._resolve_tts_config()
        try:
            audio = asyncio.run(self._synthesize_text(text, tts_config))
        except TTSError as exc:
            return ToolResult.failure(
                state=f"tts_{exc.detail}",
                message=f"TTS failed: {exc.detail}",
                errors=[{"code": f"tts_{exc.detail}", **exc.extra}],
            ).to_dict()
        except ModuleNotFoundError as exc:
            return ToolResult.failure(
                state="tts_unavailable",
                message=f"TTS dependency is unavailable in this Python environment: {exc}",
                errors=[{"code": "tts_dependency_missing", "detail": str(exc)}],
            ).to_dict()
        except Exception as exc:
            return ToolResult.failure(
                state="tts_error",
                message=f"TTS failed: {exc}",
                errors=[{"code": "tts_error", "detail": str(exc)}],
            ).to_dict()

        return ToolResult.success(
            state="tts_completed",
            message="Speech synthesis completed.",
            data={
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "mime_type": self._mime_type(tts_config.audio_format),
                "provider": tts_config.provider,
                "voice": tts_config.voice,
            },
        ).to_dict()

    def send_message(self, text: str) -> dict:
        message = str(text or "").strip()
        if not message:
            return ToolResult.failure(
                state="empty_message",
                message="Please enter a message before sending.",
                errors=[{"code": "empty_message"}],
            ).to_dict()

        try:
            bot = self._get_bot()
            response = self._run_bot(bot, message)
        except ModuleNotFoundError as exc:
            return ToolResult.failure(
                state="chat_unavailable",
                message=f"nanobot SDK is unavailable in this Python environment: {exc}",
                errors=[{"code": "nanobot_dependency_missing", "detail": str(exc)}],
            ).to_dict()
        except Exception as exc:
            return ToolResult.failure(
                state="chat_error",
                message=f"nanobot chat failed: {exc}",
                errors=[{"code": "nanobot_chat_error", "detail": str(exc)}],
            ).to_dict()

        return ToolResult.success(
            state="chat_completed",
            message="Chat response completed.",
            data={"text": str(response)},
        ).to_dict()

    def _get_bot(self) -> Any:
        if self._bot is None:
            self._bot = self._bot_factory()
        return self._bot

    def _resolve_tts_config(self) -> EffectiveTTSConfig:
        raw = getattr(self._app_config, "tts", None)
        provider = str(getattr(raw, "provider", "") or "").strip()
        # Preserve the historic desktop shorthand while keeping the core free
        # of a particular host application's TTS registry.
        if provider == "edge":
            provider = "edge_tts"
        return EffectiveTTSConfig(
            enabled=bool(getattr(raw, "enabled", False)),
            provider=provider or None,
            voice=(str(getattr(raw, "voice", "") or "").strip() or None),
            audio_format=str(getattr(raw, "audio_format", "mp3") or "mp3"),
        )

    async def _synthesize_text(self, text: str, config: EffectiveTTSConfig) -> bytes:
        if not text.strip():
            raise TTSError("empty_text")
        if not config.enabled:
            raise TTSError("disabled")
        if not config.configured:
            raise TTSError("not_configured")
        if self._tts_adapter_factory is None:
            raise ModuleNotFoundError("No platform voice adapter configured")
        adapter = self._tts_adapter_factory(config)
        synthesize = getattr(adapter, "synthesize", None)
        if not callable(synthesize):
            raise TypeError("voice adapter does not provide synthesize(text)")
        result = synthesize(text.strip())
        return await result if asyncio.iscoroutine(result) else result

    def _with_backend_summary(self, result: dict) -> dict:
        updated = dict(result)
        data = dict(updated.get("data") or {})
        data["backend"] = self._backend_summary(data.get("robot_state") or {})
        updated["data"] = data
        return updated

    def _run_operator(
        self,
        *,
        command: str,
        parameters: dict[str, Any],
        execute_real: bool,
        confirm_work_area_clear: bool,
        confirm_estop_ready: bool,
        confirmation_code: str,
    ) -> dict:
        request = ZMotionOperatorRequest(
            command=command,
            parameters=parameters,
            execute_real=bool(execute_real),
            confirm_work_area_clear=bool(confirm_work_area_clear),
            confirm_estop_ready=bool(confirm_estop_ready),
            confirmation_code=str(confirmation_code or ""),
        )
        result = self._operator_runner(request=request, config=self._backend_config)
        return self._with_backend_summary(result)

    @staticmethod
    def _motion_parameters(
        *,
        speed_pct: float,
        acceleration_pct: float,
        deceleration_pct: float,
        r_min: float,
        r_max: float,
        z_min: float,
        z_max: float,
    ) -> dict[str, float]:
        return {
            "speed_pct": float(speed_pct),
            "acceleration_pct": float(acceleration_pct),
            "deceleration_pct": float(deceleration_pct),
            "r_min": float(r_min),
            "r_max": float(r_max),
            "z_min": float(z_min),
            "z_max": float(z_max),
        }

    @staticmethod
    def _coerce_pose(pose: dict[str, Any]) -> dict[str, float]:
        axes = ("x", "y", "z", "rx", "ry", "rz")
        return {axis: float(pose[axis]) for axis in axes}

    def _backend_summary(self, robot_state: dict[str, Any]) -> dict[str, Any]:
        mode = self._backend_config.mode.strip().lower() or "simulation"
        is_readonly_real = mode in {"zmotion_readonly", "zreadonly", "real_readonly"}
        missing_config = self._missing_backend_config() if is_readonly_real else []
        configuration_ready = not missing_config
        diagnostic_state, message = self._backend_diagnostic(
            is_readonly_real=is_readonly_real,
            configuration_ready=configuration_ready,
            robot_state=robot_state,
        )
        return {
            "mode": mode,
            "controller_host": self._backend_config.controller_host,
            "real_readonly": is_readonly_real,
            "control_enabled": not is_readonly_real,
            "configuration_ready": configuration_ready,
            "missing_config": missing_config,
            "connected_real_device": bool(robot_state.get("connected_real_device")),
            "diagnostic_state": diagnostic_state,
            "message": message,
        }

    def _missing_backend_config(self) -> list[str]:
        missing: list[str] = []
        if not self._backend_config.controller_host.strip():
            missing.append("ROBOT_CONTROLLER_HOST")
        if not self._backend_config.zmotion_wrapper_path.strip():
            missing.append("ROBOT_ZMOTION_WRAPPER_PATH")
        if not self._backend_config.zmotion_dll_dir.strip():
            missing.append("ROBOT_ZMOTION_DLL_DIR")
        return missing

    def _backend_diagnostic(
        self,
        *,
        is_readonly_real: bool,
        configuration_ready: bool,
        robot_state: dict[str, Any],
    ) -> tuple[str, str]:
        if not is_readonly_real:
            return "simulation", "Simulation backend is active; no real controller writes are issued."
        if not configuration_ready:
            return (
                "configuration_missing",
                "Real controller writes are disabled. Configure ZMotion SDK paths to read controller status.",
            )

        alarms = [str(alarm) for alarm in robot_state.get("alarms") or []]
        alarm_text = " ".join(alarms).lower()
        if "zmotion sdk wrapper not found" in alarm_text:
            return "sdk_wrapper_missing", "ZMotion SDK wrapper not found. Check ROBOT_ZMOTION_WRAPPER_PATH."
        if "zmotion sdk dll directory not found" in alarm_text:
            return "sdk_dll_dir_missing", "ZMotion SDK DLL directory not found. Check ROBOT_ZMOTION_DLL_DIR."
        if "controller_read_failed" in alarm_text:
            return (
                "controller_read_failed",
                "Controller read failed. Check power, network, host, and SDK compatibility.",
            )
        if robot_state.get("mode") == "alarm" or "controller_alarm" in alarms:
            return "controller_alarm", f"Controller alarm is active: {', '.join(alarms) or 'unknown'}."
        if not bool(robot_state.get("connected_real_device")):
            return "controller_disconnected", "Controller is not connected or did not return a valid status."
        return "readonly_connected", "Real controller writes are disabled; ZMotion status is read-only."

    @staticmethod
    def _mime_type(audio_format: str) -> str:
        normalized = audio_format.strip().lower()
        if normalized == "wav":
            return "audio/wav"
        if normalized == "ogg":
            return "audio/ogg"
        return "audio/mpeg"

    @staticmethod
    def _default_bot_factory() -> Any:
        raise ModuleNotFoundError("No AI runtime adapter configured")

    @staticmethod
    def _run_bot(bot: Any, message: str) -> Any:
        run = getattr(bot, "run", None)
        if not callable(run):
            raise TypeError("bot object does not provide run(text)")
        result = run(message)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result
