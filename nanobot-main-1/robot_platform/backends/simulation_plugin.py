"""Built-in reference plugin for the controller-free simulation backend."""

from __future__ import annotations

from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.simulation_backend import SimulationRobotBackend


class SimulationBackendPlugin:
    """Register the safe simulation backend used by default products and tests."""

    plugin_id = "simulation"
    plugin_version = "1.0.0"
    backend_modes = ("simulation", "sim")
    required_ports = ("lifecycle", "diagnostics", "motion", "system_control", "io")
    configuration_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    core_compatibility = ">=1,<2"
    dependencies = ()
    health_contract_version = 1
    migration_version = 1

    def register(self, registry: BackendRegistry) -> None:
        registry.register("simulation", _create_simulation, aliases=("sim",))


def _create_simulation(config: Any, **options: Any) -> RobotBackend:
    return SimulationRobotBackend()
