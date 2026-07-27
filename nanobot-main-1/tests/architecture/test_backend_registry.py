from __future__ import annotations

import pytest

from robot_platform.backends.factory import RobotBackendConfig, create_robot_backend
from robot_platform.backends.registry import BackendRegistry
from robot_platform.application.operations import RobotOperationRequest
from robot_platform.models import RobotState


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


def test_product_controller_probe_uses_entered_host_without_reusing_live_backend(monkeypatch) -> None:
    """Login diagnostics receive a disposable, host-specific backend."""
    from robot_platform.backends import product_wiring

    seen: dict[str, object] = {}

    class ProbeBackend:
        def get_state(self) -> RobotState:
            return RobotState(mode="idle", connected_real_device=True)

        def close(self) -> None:
            seen["closed"] = True

    def create_probe_backend(config: RobotBackendConfig, *, probe_only: bool = False, **_options: object):
        seen["host"] = config.controller_host
        seen["probe_only"] = probe_only
        return ProbeBackend()

    monkeypatch.setattr(product_wiring, "create_product_robot_backend", create_probe_backend)

    state = product_wiring.probe_product_controller(
        "10.20.30.40",
        RobotBackendConfig(mode="zmotion_readonly", controller_host="10.168.3.21"),
    )

    assert seen == {"host": "10.20.30.40", "probe_only": True, "closed": True}
    assert state["connected_real_device"] is True


def test_system_actions_enter_the_selected_backend_before_vendor_execution(monkeypatch) -> None:
    """Safety buttons must not bypass the backend selected by the profile."""
    from robot_platform.backends import product_wiring, wiring

    received: list[RobotOperationRequest] = []

    class SafetyBackend:
        def execute_system_action(self, request: RobotOperationRequest) -> dict[str, object]:
            received.append(request)
            return {"ok": True, "state": "delegated_system_action"}

    monkeypatch.setattr(product_wiring, "create_product_robot_backend", lambda *_args, **_kwargs: SafetyBackend())

    request = RobotOperationRequest(
        command="system",
        parameters={"action": "pause"},
        execute_real=True,
    )
    result = wiring.run_default_operator_command(
        request=request,
        config=RobotBackendConfig(mode="zmotion_readonly"),
    )

    assert result == {"ok": True, "state": "delegated_system_action"}
    assert received == [request]
