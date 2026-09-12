"""Reusable assertions every robot Backend plugin must satisfy."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from robot_platform.backends.lifecycle import (
    BackendCallContext,
    BackendLifecycleState,
    BackendManager,
)
from threading import Event
from time import monotonic
from robot_platform.models import ControllerCapabilities, RobotModel, RobotState, ToolResult

BackendManagerFactory = Callable[[], BackendManager]


def assert_backend_contract(factory: BackendManagerFactory) -> None:
    """Exercise the vendor-neutral lifecycle, diagnostics, and motion contract."""
    manager = factory()
    assert manager.lifecycle_state is BackendLifecycleState.CREATED

    health = manager.start(timeout=1)
    assert health.state in {
        BackendLifecycleState.READY,
        BackendLifecycleState.DEGRADED,
    }
    assert manager.start(timeout=1) == health
    assert isinstance(manager.model, RobotModel)
    assert manager.model.position_unit
    assert manager.model.orientation_unit
    assert isinstance(manager.capabilities, ControllerCapabilities)
    assert isinstance(manager.get_state(), RobotState)
    if "motion" in manager.manifest.required_ports:
        cancelled = Event()
        cancelled.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            manager.move_axis(
                "x", 0, context=BackendCallContext(cancel_event=cancelled),
            )
        with pytest.raises(TimeoutError, match="deadline"):
            manager.move_axis(
                "x", 0,
                context=BackendCallContext(deadline_monotonic=monotonic() - 1),
            )
        assert isinstance(manager.move_axis("x", 0), ToolResult)
        assert isinstance(manager.home(), ToolResult)
        assert isinstance(manager.stop(), ToolResult)
    if "system_control" in manager.manifest.required_ports:
        result = manager.execute_system_action(SimpleNamespace(
            command="system", parameters={"action": "pause"},
            execute_real=False,
        ))
        assert isinstance(result, dict)
        assert isinstance(result.get("ok"), bool)
    if "io" in manager.manifest.required_ports:
        result = manager.execute_io(SimpleNamespace(
            command="io", parameters={"io_number": 0, "enabled": False},
            execute_real=False,
        ))
        assert isinstance(result, dict)
        assert isinstance(result.get("ok"), bool)

    manager.close(timeout=1)
    manager.close(timeout=1)
    assert manager.lifecycle_state is BackendLifecycleState.STOPPED
    with pytest.raises(RuntimeError, match="not ready"):
        manager.get_state()
    for operation in (
        lambda: manager.move_axis("x", 0),
        lambda: manager.execute_system_action(SimpleNamespace()),
        lambda: manager.execute_io(SimpleNamespace()),
    ):
        with pytest.raises(RuntimeError, match="not ready"):
            operation()
