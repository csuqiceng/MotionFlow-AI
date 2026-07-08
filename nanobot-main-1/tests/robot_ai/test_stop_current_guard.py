from __future__ import annotations

from robot_ai.models import RobotState
from robot_ai.zmotion_operator_control import ZMotionOperatorRequest, _run_safety_gate


def _req(action: str) -> ZMotionOperatorRequest:
    return ZMotionOperatorRequest(command="system", parameters={"action": action})


def test_stop_current_rejected_when_idle() -> None:
    state = RobotState(mode="idle", connected_real_device=True, cancel_latch=False)
    r = _run_safety_gate(_req("stop_current"), state)
    assert r["ok"] is False
    assert r["state"] == "stop_current_not_allowed_when_idle"


def test_stop_current_allowed_when_executing() -> None:
    state = RobotState(mode="moving", connected_real_device=True, cancel_latch=False)
    r = _run_safety_gate(_req("stop_current"), state)
    assert r is None  # proceeds to planner


def test_release_cancel_rejected_without_latch() -> None:
    state = RobotState(mode="idle", connected_real_device=True, cancel_latch=False)
    r = _run_safety_gate(_req("release_cancel"), state)
    assert r["ok"] is False
    assert r["state"] == "release_cancel_no_latch"


def test_release_cancel_allowed_with_latch() -> None:
    state = RobotState(mode="idle", connected_real_device=True, cancel_latch=True)
    r = _run_safety_gate(_req("release_cancel"), state)
    assert r is None
