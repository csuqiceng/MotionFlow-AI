from __future__ import annotations

from typing import Protocol

from robot_platform.backends.zmotion_write_plan import ZMotionCommandPlan
from robot_platform.models import ToolResult


class ZMotionSinglePlanExecutor(Protocol):
    def execute(
        self,
        plan: ZMotionCommandPlan,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict: ...


class ZMotionSequenceRunner:
    """Executes verified Func108 plans in order and stops on first failure."""

    def __init__(self, executor: ZMotionSinglePlanExecutor) -> None:
        self._executor = executor

    def execute(
        self,
        plans: list[ZMotionCommandPlan],
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict:
        if not plans:
            return ToolResult.failure(
                state="real_motion_sequence_invalid",
                message="A Func108 sequence must contain at least one segment.",
                data={"invalid_segment": None},
            ).to_dict()

        for index, plan in enumerate(plans, start=1):
            if plan.function_code != 108:
                return ToolResult.failure(
                    state="real_motion_sequence_invalid",
                    message="Only Func108 plans are allowed in a motion sequence.",
                    data={
                        "invalid_segment": index,
                        "function_code": plan.function_code,
                    },
                ).to_dict()

        segment_states: list[str] = []
        for index, plan in enumerate(plans, start=1):
            result = self._executor.execute(
                plan,
                allow_real_motion_writes=allow_real_motion_writes,
                confirmed_real_motion=confirmed_real_motion,
            )
            segment_states.append(str(result.get("state", "")))
            if not result.get("ok"):
                return ToolResult.failure(
                    state="real_motion_sequence_failed",
                    message=f"Func108 sequence stopped at segment {index}.",
                    data={
                        "failed_segment": index,
                        "segment_state": result.get("state"),
                        "segment_result": result,
                        "completed_segments": index - 1,
                    },
                ).to_dict()

        return ToolResult.success(
            state="real_motion_sequence_submitted",
            message="All Func108 sequence segments were submitted in order.",
            data={
                "segment_count": len(plans),
                "segment_states": segment_states,
            },
        ).to_dict()
