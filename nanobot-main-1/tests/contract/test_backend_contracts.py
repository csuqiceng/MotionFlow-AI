from __future__ import annotations

from collections.abc import Callable
from threading import Event
import time

import pytest

from robot_platform.backends.dummy_backend import DummyRobotBackend
from robot_platform.backends.dummy_plugin import DummyBackendPlugin
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.lifecycle import (
    BackendLifecycleState,
    BackendManager,
    BackendPortBundle,
    bundle_legacy_backend,
)
from robot_platform.backends.plugin_contract import BackendManifest
from robot_platform.backends.product_wiring import create_product_backend_manager
from robot_platform.backends.simulation_backend import SimulationRobotBackend
from robot_platform.backends.simulation_plugin import SimulationBackendPlugin
from robot_platform.backends.wiring import create_default_backend_registry
from robot_platform.backends.zmotion_backend import ZMotionReadOnlyBackend
from robot_platform.backends.zmotion_plugin import ZMotionBackendPlugin
from robot_platform.models import ControllerCapabilities, DEFAULT_SIX_AXIS_MODEL, RobotState
from tests.contract.backend_contract_kit import assert_backend_contract


class _ReadableClient:
    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def read_modbus_float(self, request: object) -> list[float]:
        count = int(getattr(request, "count"))
        return [0.0] * count

    def read_modbus_long(self, request: object) -> list[int]:
        start = int(getattr(request, "start_vr"))
        count = int(getattr(request, "count"))
        return [1 << 28] if start == 34 else [0] * count


@pytest.mark.parametrize(
    "factory",
    [
        lambda: BackendManager(
            BackendManifest.from_plugin(SimulationBackendPlugin()),
            bundle_legacy_backend(SimulationRobotBackend()),
        ),
        lambda: BackendManager(
            BackendManifest.from_plugin(DummyBackendPlugin()),
            bundle_legacy_backend(DummyRobotBackend()),
        ),
        lambda: BackendManager(
            BackendManifest.from_plugin(ZMotionBackendPlugin()),
            bundle_legacy_backend(
                ZMotionReadOnlyBackend(
                    client_factory=lambda _host: _ReadableClient(),
                    host="127.0.0.1",
                )
            ),
        ),
    ],
    ids=("simulation", "dummy", "zmotion-readonly"),
)
def test_backend_implements_shared_contract(factory: Callable[[], BackendManager]) -> None:
    assert_backend_contract(factory)


def test_dummy_plugin_is_explicit_and_not_in_default_product_registry() -> None:
    registry = create_default_backend_registry()
    assert "dummy" not in registry.plugin_ids
    with pytest.raises(ValueError, match="Unknown robot backend mode"):
        registry.create("dummy", RobotBackendConfig(mode="dummy"))

    registry.register_plugin(DummyBackendPlugin())
    backend = registry.create("dummy", RobotBackendConfig(mode="dummy"))
    assert isinstance(backend, DummyRobotBackend)


def test_product_manager_starts_simulation_and_degrades_missing_zmotion_sdk() -> None:
    simulation = create_product_backend_manager(RobotBackendConfig(mode="simulation"))
    try:
        assert simulation.lifecycle_state is BackendLifecycleState.READY
    finally:
        simulation.close()

    zmotion = create_product_backend_manager(
        RobotBackendConfig(mode="zmotion_readonly", controller_host="127.0.0.1")
    )
    try:
        assert zmotion.lifecycle_state is BackendLifecycleState.DEGRADED
        assert zmotion.get_state().mode == "disconnected"
    finally:
        zmotion.close()


def test_manifest_rejects_unknown_duplicate_or_missing_required_ports() -> None:
    for required in ((), ("unknown",), ("diagnostics", "diagnostics")):
        plugin = type(
            "InvalidPlugin",
            (),
            {
                "plugin_id": "invalid",
                "plugin_version": "1",
                "backend_modes": ("invalid",),
                "required_ports": required,
            },
        )()
        with pytest.raises(ValueError, match="required ports"):
            BackendManifest.from_plugin(plugin)

    manifest = BackendManifest(
        plugin_id="missing-motion",
        plugin_version="1",
        backend_modes=("missing",),
        required_ports=("lifecycle", "diagnostics", "motion"),
    )
    diagnostics = _MutableBackend()
    with pytest.raises(ValueError, match="missing declared ports: motion"):
        BackendManager(
            manifest,
            BackendPortBundle(lifecycle=diagnostics, diagnostics=diagnostics),
        )


class _MutableBackend:
    def __init__(self) -> None:
        self.mode = "idle"
        self.shutdown_calls = 0

    def start(self) -> None:
        return None

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    @property
    def model(self):
        return DEFAULT_SIX_AXIS_MODEL

    @property
    def capabilities(self):
        return ControllerCapabilities(vendor="test")

    def get_state(self) -> RobotState:
        return RobotState(mode=self.mode)


def _diagnostics_manifest() -> BackendManifest:
    return BackendManifest(
        plugin_id="lifecycle-test",
        plugin_version="1",
        backend_modes=("test",),
    )


def test_manager_health_can_degrade_and_recover() -> None:
    backend = _MutableBackend()
    manager = BackendManager(
        _diagnostics_manifest(),
        BackendPortBundle(lifecycle=backend, diagnostics=backend),
    )
    assert manager.start().state is BackendLifecycleState.READY
    backend.mode = "disconnected"
    assert manager.refresh_health().state is BackendLifecycleState.DEGRADED
    backend.mode = "idle"
    assert manager.refresh_health().state is BackendLifecycleState.READY


def test_manager_start_timeout_enters_error_and_can_be_closed() -> None:
    release = Event()
    backend = _MutableBackend()
    backend.start = lambda: release.wait(1)  # type: ignore[method-assign]
    manager = BackendManager(
        _diagnostics_manifest(),
        BackendPortBundle(lifecycle=backend, diagnostics=backend),
    )

    with pytest.raises(TimeoutError, match="start timed out"):
        manager.start(timeout=0.01)
    assert manager.lifecycle_state is BackendLifecycleState.ERROR
    release.set()
    manager.close()
    assert manager.lifecycle_state is BackendLifecycleState.STOPPED
    assert backend.shutdown_calls == 1


def test_manager_operation_exception_enters_error() -> None:
    class ExplodingBackend(DummyRobotBackend):
        def move_axis(self, axis: str, delta: float):
            raise OSError("transport failed")

    manager = BackendManager(
        BackendManifest.from_plugin(DummyBackendPlugin()),
        bundle_legacy_backend(ExplodingBackend()),
    )
    manager.start()
    with pytest.raises(OSError, match="transport failed"):
        manager.move_axis("x", 1)
    assert manager.health.state is BackendLifecycleState.ERROR
    assert manager.health.message == "Backend motion failed."


def test_late_start_is_torn_down_after_manager_is_already_stopped() -> None:
    release = Event()
    late_opened = Event()

    class LateBackend(_MutableBackend):
        opened = False

        def start(self) -> None:
            release.wait(2)
            self.opened = True
            late_opened.set()

        def shutdown(self) -> None:
            super().shutdown()
            self.opened = False

    backend = LateBackend()
    manager = BackendManager(
        _diagnostics_manifest(),
        BackendPortBundle(lifecycle=backend, diagnostics=backend),
    )
    with pytest.raises(TimeoutError):
        manager.start(timeout=0.01)
    manager.close(timeout=0.1)
    assert manager.lifecycle_state is BackendLifecycleState.STOPPED
    release.set()
    assert late_opened.wait(1)
    deadline = time.monotonic() + 1
    while backend.opened and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.02)
    assert backend.opened is False
