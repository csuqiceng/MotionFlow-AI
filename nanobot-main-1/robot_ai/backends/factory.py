from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from robot_ai.backends.simulation_backend import SimulationRobotBackend
from robot_ai.backends.zmotion_backend import ZMotionReadableClient, ZMotionReadOnlyBackend
from robot_ai.backends.zmotion_sdk import ZMotionSdkClient, ZMotionSdkConfig
from robot_ai.backends.zmotion_shared_client import shared_client_enabled
from robot_ai.models import RobotState, ToolResult


class RobotBackend(Protocol):
    def get_state(self) -> RobotState:
        ...

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        ...

    def home(self) -> ToolResult:
        ...

    def stop(self) -> ToolResult:
        ...


ZMotionClientFactory = Callable[[str], ZMotionReadableClient]


@dataclass(frozen=True)
class RobotBackendConfig:
    mode: str = "simulation"
    controller_host: str = "10.168.3.21"
    zmotion_wrapper_path: str = ""
    zmotion_dll_dir: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RobotBackendConfig":
        source = env if env is not None else os.environ
        return cls(
            mode=source.get("ROBOT_AI_BACKEND", cls.mode).strip() or cls.mode,
            controller_host=source.get("ROBOT_CONTROLLER_HOST", cls.controller_host).strip() or cls.controller_host,
            zmotion_wrapper_path=source.get("ROBOT_ZMOTION_WRAPPER_PATH", "").strip(),
            zmotion_dll_dir=source.get("ROBOT_ZMOTION_DLL_DIR", "").strip(),
        )


def create_robot_backend(
    config: RobotBackendConfig | None = None,
    *,
    client_factory: ZMotionClientFactory | None = None,
) -> RobotBackend:
    resolved = config or RobotBackendConfig.from_env()
    mode = resolved.mode.strip().lower()

    if mode in {"simulation", "sim"}:
        return SimulationRobotBackend()

    if mode in {"zmotion_readonly", "zreadonly", "real_readonly"}:
        if client_factory is not None:
            # Explicit factory (tests) — own client, unchanged behavior.
            return ZMotionReadOnlyBackend(
                host=resolved.controller_host,
                client_factory=client_factory,
            )
        if shared_client_enabled():
            # Gateway mode: one shared persistent ZAux connection across status + motion,
            # matching the legacy Qt app (single ZMotionVrClient). Avoids clogging the
            # controller's limited ZAux session table when status + motion each open their
            # own connection (motion fails with code 3402).
            from robot_ai.backends import zmotion_shared_client as shared

            sdk_config = resolve_sdk_config(resolved)
            if sdk_config is None:
                return ZMotionReadOnlyBackend(
                    host=resolved.controller_host,
                    client_factory=_missing_zmotion_client_factory,
                )
            shared.configure(resolved.controller_host, sdk_config)
            return ZMotionReadOnlyBackend(host=resolved.controller_host, use_shared=True)
        return ZMotionReadOnlyBackend(
            host=resolved.controller_host,
            client_factory=_create_zmotion_sdk_client_factory(resolved),
        )

    raise ValueError(f"Unknown robot backend mode: {resolved.mode}")


def resolve_sdk_config(config: RobotBackendConfig) -> ZMotionSdkConfig | None:
    if not config.zmotion_wrapper_path or not config.zmotion_dll_dir:
        return None
    return ZMotionSdkConfig(
        wrapper_path=Path(config.zmotion_wrapper_path),
        dll_dir=Path(config.zmotion_dll_dir),
    )


def _create_zmotion_sdk_client_factory(config: RobotBackendConfig) -> ZMotionClientFactory:
    sdk_config = resolve_sdk_config(config)
    if sdk_config is None:
        return _missing_zmotion_client_factory
    return lambda host: ZMotionSdkClient(host=host, sdk_config=sdk_config)


def _missing_zmotion_client_factory(host: str) -> ZMotionReadableClient:
    raise RuntimeError(
        "ZMotion read-only mode needs a configured ZMotion client factory or "
        "ROBOT_ZMOTION_WRAPPER_PATH plus ROBOT_ZMOTION_DLL_DIR before it can connect "
        f"to {host}."
    )
