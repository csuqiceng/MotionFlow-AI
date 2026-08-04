"""Optional PyBullet plugin for model-driven offline simulation."""

from __future__ import annotations

from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.simulation_backend import PyBulletSimulationBackend


class PyBulletBackendPlugin:
    plugin_id = "pybullet-simulation"
    plugin_version = "1.0.0"
    backend_modes = ("pybullet",)
    required_ports = ("lifecycle", "diagnostics", "motion", "system_control", "io", "operation")
    configuration_schema = {
        "type": "object",
        "properties": {"simulation_model_id": {"type": "string", "minLength": 1}},
        "additionalProperties": False,
    }
    core_compatibility = ">=1,<2"
    dependencies = ("pybullet>=3.2.7,<3.3",)
    health_contract_version = 1
    migration_version = 1

    def register(self, registry: BackendRegistry) -> None:
        registry.register("pybullet", _create_pybullet)


def _create_pybullet(config: Any, **options: Any) -> RobotBackend:
    del options
    return PyBulletSimulationBackend(
        model_id=str(getattr(config, "simulation_model_id", "generic-six-axis")),
    )
