from __future__ import annotations

from robot_ai.safety import RobotSafetyChecker, SafetyLimits, SafetyPrecheckService


def _checker() -> RobotSafetyChecker:
    precheck = SafetyPrecheckService(SafetyLimits.default(), max_sphere_radius=0.0)
    return RobotSafetyChecker(l1_service=precheck)


def _passing_snapshot() -> dict:
    return {
        "safety": {"estop": False, "alarm_active": False, "paused": False},
        "connection": {"controller": "online", "realtime_feedback": "online"},
        "motion": {"active_plan_id": None, "running_state": "idle"},
        "position": {"cartesian": {"x": 900.0, "y": 0.0, "z": 1000.0, "r": 900.0}},
    }


def test_l1_pass_returns_safe_with_l2_soft_passed() -> None:
    verdict = _checker().check_target(
        target_pose=[900.0, 0.0, 999.0, 0.0, 0.0, 0.0],
        snapshot=_passing_snapshot(),
        speed={"spd_pct": 5.0, "acc_pct": 5.0, "dec_pct": 5.0},
        func_id=108,
    )
    assert verdict["safe"] is True
    assert verdict["position_ok"] is True
    assert verdict["blocking_level"] is None
    # L2/pose are deferred in this project.
    assert verdict["ik_ok"] is None
    assert verdict["pose_ok"] is None


def test_l1_fail_on_estop() -> None:
    snapshot = _passing_snapshot()
    snapshot["safety"]["estop"] = True
    verdict = _checker().check_target(
        target_pose=[900.0, 0.0, 999.0, 0.0, 0.0, 0.0],
        snapshot=snapshot,
        speed={"spd_pct": 5.0},
        func_id=108,
    )
    assert verdict["safe"] is False
    assert verdict["blocking_level"] == "L1"
    assert verdict["suggestion_zh"]


def test_l1_fail_on_target_out_of_soft_limit() -> None:
    verdict = _checker().check_target(
        target_pose=[9999.0, 0.0, 999.0, 0.0, 0.0, 0.0],
        snapshot=_passing_snapshot(),
        speed={"spd_pct": 5.0},
        func_id=108,
    )
    assert verdict["safe"] is False
    assert verdict["blocking_level"] == "L1"
    assert "X" in verdict["detail_zh"] or "X" in verdict["suggestion_zh"]


def test_strict_l2_blocks_when_unavailable() -> None:
    precheck = SafetyPrecheckService(SafetyLimits.default(), max_sphere_radius=0.0)
    strict = RobotSafetyChecker(l1_service=precheck, strict_l2=True)
    verdict = strict.check_target(
        target_pose=[900.0, 0.0, 999.0, 0.0, 0.0, 0.0],
        snapshot=_passing_snapshot(),
        speed={"spd_pct": 5.0},
        func_id=108,
    )
    assert verdict["safe"] is False
    assert verdict["blocking_level"] == "L2"
