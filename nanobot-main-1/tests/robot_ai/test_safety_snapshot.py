from __future__ import annotations

import math

from robot_ai.models import RobotState
from robot_ai.safety import build_controller_snapshot, build_l1_plan


def _state(**overrides) -> RobotState:
    base = {
        "mode": "idle",
        "axes_mm": {"x": 900.0, "y": 0.0, "z": 1000.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
        "alarms": [],
        "connected_real_device": True,
    }
    base.update(overrides)
    return RobotState(**base)


def test_idle_connected_snapshot_shape() -> None:
    snapshot = build_controller_snapshot(_state())
    assert snapshot["safety"] == {"estop": False, "alarm_active": False, "paused": False}
    assert snapshot["connection"] == {"controller": "online", "realtime_feedback": "online"}
    assert snapshot["motion"]["running_state"] == "idle"
    assert snapshot["motion"]["active_plan_id"] is None
    cart = snapshot["position"]["cartesian"]
    assert cart["x"] == 900.0
    assert cart["z"] == 1000.0
    assert cart["r"] == math.hypot(900.0, 0.0)


def test_estop_derived_from_stopped_mode() -> None:
    snapshot = build_controller_snapshot(_state(mode="stopped"))
    assert snapshot["safety"]["estop"] is True


def test_estop_derived_from_emergency_stop_alarm() -> None:
    snapshot = build_controller_snapshot(_state(alarms=["emergency_stop"]))
    assert snapshot["safety"]["estop"] is True
    assert snapshot["safety"]["alarm_active"] is True


def test_alarm_active_from_mode_and_alarms() -> None:
    assert build_controller_snapshot(_state(mode="alarm"))["safety"]["alarm_active"] is True
    assert build_controller_snapshot(_state(alarms=["controller_alarm"]))["safety"]["alarm_active"] is True


def test_paused_mode_flagged() -> None:
    assert build_controller_snapshot(_state(mode="paused"))["safety"]["paused"] is True


def test_moving_mode_maps_to_executing() -> None:
    snapshot = build_controller_snapshot(_state(mode="moving"))
    assert snapshot["motion"]["running_state"] == "executing"


def test_disconnected_maps_offline() -> None:
    snapshot = build_controller_snapshot(_state(connected_real_device=False))
    assert snapshot["connection"]["controller"] == "offline"


def test_build_l1_plan_shape() -> None:
    plan = build_l1_plan(
        func_id=108,
        target={"x": 900.0, "y": 0.0, "z": 999.0},
        speed={"spd_pct": 5.0, "acc_pct": 5.0, "dec_pct": 5.0},
    )
    assert plan["func_id"] == 108
    assert plan["action_type"] == "move"
    assert plan["plan_id"] == "operator"
    assert plan["target"]["z"] == 999.0
    assert plan["speed"]["spd_pct"] == 5.0
