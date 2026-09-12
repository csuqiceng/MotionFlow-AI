"""Explicit, static backend plugins keep controller vendors outside the core."""

from __future__ import annotations

import pytest

from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.simulation_plugin import SimulationBackendPlugin


class _SentinelBackend:
    pass


class _FakePlugin:
    plugin_id = "fake-controller"
    plugin_version = "1.0.0"
    backend_modes = ("fake", "fake-alias")

    def __init__(self) -> None:
        self.backend = _SentinelBackend()

    def register(self, registry: BackendRegistry) -> None:
        registry.register("fake", lambda config, **options: self.backend, aliases=("fake-alias",))


def test_registry_registers_an_explicit_backend_plugin_manifest() -> None:
    registry = BackendRegistry()
    plugin = _FakePlugin()

    registry.register_plugin(plugin)

    assert registry.plugin_ids == ("fake-controller",)
    assert registry.create("fake-alias", RobotBackendConfig(mode="fake")) is plugin.backend


def test_simulation_is_registered_through_the_reference_plugin_manifest() -> None:
    registry = BackendRegistry()

    registry.register_plugin(SimulationBackendPlugin())

    backend = registry.create("sim", RobotBackendConfig(mode="simulation"))
    assert registry.plugin_ids == ("simulation",)
    assert backend.get_state().mode == "idle"


def test_plugin_registration_reverts_if_declared_modes_are_missing() -> None:
    class _BrokenPlugin:
        plugin_id = "broken"
        plugin_version = "1.0.0"
        backend_modes = ("absent",)

        def register(self, registry: BackendRegistry) -> None:
            return None

    registry = BackendRegistry()

    with pytest.raises(ValueError, match="did not register declared modes: absent"):
        registry.register_plugin(_BrokenPlugin())

    assert registry.plugin_ids == ()
    with pytest.raises(ValueError, match="Unknown robot backend mode: absent"):
        registry.create("absent", RobotBackendConfig(mode="absent"))
