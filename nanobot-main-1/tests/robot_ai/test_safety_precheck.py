from __future__ import annotations

from robot_ai.safety import SafetyLimits, SafetyPrecheckService


def _service(**kwargs) -> SafetyPrecheckService:
    # Mirror the production facade (SafetyServices.from_limits): the legacy
    # origin-sphere check is disabled because its 1200 mm constant does not
    # fit this robot's geometry. Tests that need the legacy sphere logic pass
    # max_sphere_radius explicitly.
    kwargs.setdefault("max_sphere_radius", 0.0)
    return SafetyPrecheckService(SafetyLimits.default(), **kwargs)


def _passing_snapshot() -> dict:
    return {
        "safety": {"estop": False, "alarm_active": False, "paused": False},
        "connection": {"controller": "online", "realtime_feedback": "online"},
        "motion": {"active_plan_id": None, "running_state": "idle"},
        "position": {"cartesian": {"x": 900.0, "y": 0.0, "z": 1000.0, "r": 900.0}},
    }


def _passing_plan(**overrides) -> dict:
    plan = {
        "plan_id": "operator",
        "func_id": 108,
        "action_type": "move",
        "target": {"x": 900.0, "y": 0.0, "z": 999.0},
        "speed": {"spd_pct": 5.0, "acc_pct": 5.0, "dec_pct": 5.0},
    }
    plan.update(overrides)
    return plan


def _failed_ids(result: dict) -> set[str]:
    return {item["id"] for item in result["items"] if item["status"] == "fail"}


def test_clean_snapshot_and_plan_pass() -> None:
    result = _service().run_l1(_passing_snapshot(), _passing_plan())
    assert result["status"] == "pass"
    assert result["suggestion"] is None


def test_estop_fails() -> None:
    snapshot = _passing_snapshot()
    snapshot["safety"]["estop"] = True
    result = _service().run_l1(snapshot, _passing_plan())
    assert result["status"] == "fail"
    assert "estop" in _failed_ids(result)


def test_alarm_and_paused_fail() -> None:
    for field in ("alarm_active", "paused"):
        snapshot = _passing_snapshot()
        snapshot["safety"][field] = True
        assert _service().run_l1(snapshot, _passing_plan())["status"] == "fail"


def test_controller_offline_fails() -> None:
    snapshot = _passing_snapshot()
    snapshot["connection"]["controller"] = "offline"
    assert _service().run_l1(snapshot, _passing_plan())["status"] == "fail"


def test_target_x_outside_soft_limit_fails() -> None:
    plan = _passing_plan(target={"x": 9999.0, "y": 0.0, "z": 999.0})
    result = _service().run_l1(_passing_snapshot(), plan)
    assert result["status"] == "fail"
    assert "target_x_range" in _failed_ids(result)


def test_target_z_outside_safe_height_fails() -> None:
    plan = _passing_plan(target={"x": 900.0, "y": 0.0, "z": 9999.0})
    result = _service().run_l1(_passing_snapshot(), plan)
    assert result["status"] == "fail"
    assert "target_safe_z_range" in _failed_ids(result)


def test_speed_over_limit_fails() -> None:
    plan = _passing_plan(speed={"spd_pct": 200.0, "acc_pct": 5.0, "dec_pct": 5.0})
    result = _service().run_l1(_passing_snapshot(), plan)
    assert result["status"] == "fail"
    assert "speed_pct" in _failed_ids(result)


def test_base_angle_beyond_160_fails() -> None:
    # atan2(100, -1000) ~= 174.3 deg -> beyond ±160.
    plan = _passing_plan(target={"x": -1000.0, "y": 100.0, "z": 999.0})
    result = _service().run_l1(_passing_snapshot(), plan)
    assert "target_base_angle_range" in _failed_ids(result)


def test_legacy_origin_sphere_check_blocks_nominal_pose() -> None:
    # With the legacy 1200 mm origin-sphere default, [900,0,1000] (sphere ~1345)
    # is blocked. This documents why the production facade disables it.
    legacy = SafetyPrecheckService(SafetyLimits.default())  # max_sphere_radius=1200
    plan = _passing_plan(target={"x": 900.0, "y": 0.0, "z": 1000.0})
    result = legacy.run_l1(_passing_snapshot(), plan)
    assert result["status"] == "fail"
    assert "target_sphere_radius" in _failed_ids(result)
