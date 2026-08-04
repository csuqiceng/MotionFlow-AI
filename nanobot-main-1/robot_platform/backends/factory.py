from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.registry import BackendRegistry


@dataclass(frozen=True)
class RobotBackendConfig:
    mode: str = "simulation"
    controller_host: str = "10.168.3.21"
    zmotion_wrapper_path: str = ""
    zmotion_dll_dir: str = ""
    allowed_io_output_channels: tuple[int, ...] = ()
    simulation_model_id: str = "generic-six-axis"
    simulation_engine: str = "legacy"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RobotBackendConfig":
        source = env if env is not None else os.environ
        return cls(
            mode=source.get("ROBOT_AI_BACKEND", cls.mode).strip() or cls.mode,
            controller_host=source.get("ROBOT_CONTROLLER_HOST", cls.controller_host).strip() or cls.controller_host,
            zmotion_wrapper_path=source.get("ROBOT_ZMOTION_WRAPPER_PATH", "").strip(),
            zmotion_dll_dir=source.get("ROBOT_ZMOTION_DLL_DIR", "").strip(),
            simulation_model_id=(
                source.get("ROBOT_SIMULATION_MODEL_ID", cls.simulation_model_id).strip()
                or cls.simulation_model_id
            ),
            simulation_engine=(
                source.get("ROBOT_SIMULATION_ENGINE", cls.simulation_engine).strip().casefold()
                or cls.simulation_engine
            ),
        )


def create_robot_backend(
    config: RobotBackendConfig | None = None,
    *,
    registry: BackendRegistry | None = None,
    client_factory: Any = None,
    **options: Any,
) -> RobotBackend:
    resolved = config or RobotBackendConfig.from_env()
    if registry is None:
        # The default product wiring remains lazy so importing the contract or
        # factory does not import a vendor SDK. Alternate products inject their
        # own registry at the composition root.
        from robot_platform.backends.wiring import create_default_backend_registry

        registry = create_default_backend_registry()
    return registry.create(
        resolved.mode,
        resolved,
        client_factory=client_factory,
        **options,
    )
