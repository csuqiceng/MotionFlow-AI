from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from typing import Any

from nanobot.audio.tts import (
    EffectiveTTSConfig,
    TTSError,
    resolve_tts_config,
    synthesize_text,
)
from robot_ai.backends.factory import RobotBackend, create_robot_backend
from robot_ai.models import ToolResult
from robot_ai.tools.robot_tools import RobotToolFacade


BotFactory = Callable[[], Any]
TTSAdapterFactory = Callable[[EffectiveTTSConfig], Any]
BackendFactory = Callable[[], RobotBackend]


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
    ) -> None:
        backend = backend_factory() if tools is None and backend_factory is not None else None
        self._tools = tools or RobotToolFacade(backend=backend or create_robot_backend())
        self._bot_factory = bot_factory or self._default_bot_factory
        self._app_config = app_config if app_config is not None else object()
        self._tts_adapter_factory = tts_adapter_factory
        self._bot: Any | None = None

    def health(self) -> dict:
        return ToolResult.success(
            state="healthy",
            message="Robot desktop bridge is ready.",
            data={
                "bridge": "pywebview",
                "robot_state": self._tools.robot_get_status()["data"]["robot_state"],
            },
        ).to_dict()

    def get_robot_state(self) -> dict:
        return self._tools.robot_get_status()

    def move_axis(self, axis: str, delta: float) -> dict:
        return self._tools.robot_move_axis(axis=axis, delta=delta)

    def home(self) -> dict:
        return self._tools.robot_home()

    def stop(self) -> dict:
        return self._tools.robot_stop()

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
            audio = asyncio.run(
                synthesize_text(
                    text,
                    tts_config,
                    adapter_factory=self._tts_adapter_factory,
                )
            )
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
        return resolve_tts_config(self._app_config)

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
        from nanobot.nanobot import Nanobot

        return Nanobot.from_config()

    @staticmethod
    def _run_bot(bot: Any, message: str) -> Any:
        run = getattr(bot, "run", None)
        if not callable(run):
            raise TypeError("bot object does not provide run(text)")
        result = run(message)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result
