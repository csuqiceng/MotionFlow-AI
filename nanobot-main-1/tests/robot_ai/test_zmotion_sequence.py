from __future__ import annotations

from robot_ai.backends.zmotion_write_plan import ZMotionCommandPlan, ZMotionWritePlanner
from robot_ai.models import RobotState, ToolResult


class FakeSinglePlanExecutor:
    def __init__(self, results: list[dict] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[ZMotionCommandPlan, bool, bool]] = []

    def execute(
        self,
        plan: ZMotionCommandPlan,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict:
        self.calls.append(
            (plan, allow_real_motion_writes, confirmed_real_motion)
        )
        if self.results:
            return self.results.pop(0)
        return ToolResult.success(
            state="real_motion_write_submitted",
            data={"action": plan.action},
        ).to_dict()


def _safe_state() -> RobotState:
    return RobotState(
        mode="idle",
        axes_mm={
            "x": 900.0,
            "y": 0.0,
            "z": 1000.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        },
        connected_real_device=True,
    )


def _linear_plans() -> list[ZMotionCommandPlan]:
    planner = ZMotionWritePlanner()
    common = {
        "robot_state": _safe_state(),
        "speed_pct": 5.0,
        "acceleration_pct": 5.0,
        "deceleration_pct": 5.0,
        "confirmed_real_motion": True,
        "allow_real_motion_writes": True,
    }
    return [
        planner.plan_linear_move(
            target_pose={
                "x": 900.0,
                "y": 0.0,
                "z": z,
                "rx": 0.0,
                "ry": 0.0,
                "rz": 0.0,
            },
            **common,
        )
        for z in (999.0, 998.0, 997.0)
    ]


def test_sequence_executes_func108_segments_in_order() -> None:
    from robot_ai.backends.zmotion_sequence import ZMotionSequenceRunner

    plans = _linear_plans()
    executor = FakeSinglePlanExecutor()

    result = ZMotionSequenceRunner(executor).execute(
        plans,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_sequence_submitted"
    assert result["data"]["segment_count"] == 3
    assert [call[0].parameter_writes[3].value for call in executor.calls] == [
        999.0,
        998.0,
        997.0,
    ]
    assert all(call[1:] == (True, True) for call in executor.calls)


def test_sequence_stops_after_first_failed_segment() -> None:
    from robot_ai.backends.zmotion_sequence import ZMotionSequenceRunner

    results = [
        ToolResult.success(state="real_motion_write_submitted").to_dict(),
        ToolResult.failure(
            state="real_motion_echo_mismatch",
            message="echo mismatch",
        ).to_dict(),
    ]
    executor = FakeSinglePlanExecutor(results)

    result = ZMotionSequenceRunner(executor).execute(
        _linear_plans(),
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_sequence_failed"
    assert result["data"]["failed_segment"] == 2
    assert result["data"]["segment_state"] == "real_motion_echo_mismatch"
    assert len(executor.calls) == 2


def test_sequence_rejects_non_func108_plan_before_execution() -> None:
    from robot_ai.backends.zmotion_sequence import ZMotionSequenceRunner

    plans = _linear_plans()
    plans.append(
        ZMotionWritePlanner().plan_delay(
            seconds=0.1,
            robot_state=_safe_state(),
            confirmed_real_motion=True,
            allow_real_motion_writes=True,
        )
    )
    executor = FakeSinglePlanExecutor()

    result = ZMotionSequenceRunner(executor).execute(
        plans,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_sequence_invalid"
    assert result["data"]["invalid_segment"] == 4
    assert executor.calls == []
