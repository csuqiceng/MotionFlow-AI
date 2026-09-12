"""Explicit test/reference plugin for the minimal Dummy Backend."""

from __future__ import annotations

from robot_platform.backends.dummy_backend import DummyRobotBackend
from robot_platform.backends.registry import BackendRegistry


class DummyBackendPlugin:
    plugin_id = "dummy"
    plugin_version = "1.0.0"
    backend_modes = ("dummy",)
    required_ports = (
        "lifecycle", "diagnostics", "motion", "system_control", "io",
    )
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
        registry.register("dummy", lambda _config, **_options: DummyRobotBackend())
