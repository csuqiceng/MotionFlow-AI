from __future__ import annotations

import pytest

from robot_platform.backends.factory import RobotBackendConfig, create_robot_backend
from robot_platform.backends.registry import BackendRegistry


class _SentinelBackend:
    pass


def test_registry_resolves_normalized_names_and_aliases() -> None:
    registry = BackendRegistry()
    backend = _SentinelBackend()
    registry.register("fake", lambda config, **options: backend, aliases=("demo",))

    assert registry.create("  DEMO  ", RobotBackendConfig(mode="demo")) is backend


def test_registry_rejects_duplicate_names_and_unknown_modes() -> None:
    registry = BackendRegistry()
    registry.register("fake", lambda config, **options: _SentinelBackend())

    with pytest.raises(ValueError, match="already registered"):
        registry.register("FAKE", lambda config, **options: _SentinelBackend())
    with pytest.raises(ValueError, match="Unknown robot backend mode: absent"):
        registry.create("absent", RobotBackendConfig(mode="absent"))


def test_legacy_factory_delegates_to_an_injected_registry() -> None:
    registry = BackendRegistry()
    backend = _SentinelBackend()
    seen: dict[str, object] = {}

    def build(config: RobotBackendConfig, **options: object) -> _SentinelBackend:
        seen["config"] = config
        seen["client_factory"] = options.get("client_factory")
        return backend

    registry.register("fake", build)
    client_factory = object()

    assert create_robot_backend(
        RobotBackendConfig(mode="fake"),
        registry=registry,
        client_factory=client_factory,
    ) is backend
    assert seen["config"] == RobotBackendConfig(mode="fake")
    assert seen["client_factory"] is client_factory
