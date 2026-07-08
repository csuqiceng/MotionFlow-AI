from __future__ import annotations

from robot_ai.flow import VALID_TRANSITIONS, FlowEntry, FlowState, FlowStep


def test_flow_step_from_dict_round_trip() -> None:
    step = FlowStep.from_dict(
        {
            "step_id": 1,
            "action": "move",
            "func_id": 108,
            "params": {"target_pose": {"x": 900.0}},
            "description": "approach",
        }
    )
    assert step.func_id == 108
    assert step.params == {"target_pose": {"x": 900.0}}
    assert step.spd_pct == 50  # default
    as_dict = step.to_dict()
    assert as_dict["func_id"] == 108
    assert as_dict["params"] == {"target_pose": {"x": 900.0}}


def test_flow_step_spd_pct_falls_back_to_speed_pct() -> None:
    step = FlowStep.from_dict({"step_id": 2, "action": "move", "func_id": 108, "speed_pct": 25})
    assert step.spd_pct == 25


def test_flow_entry_from_dict_with_steps() -> None:
    entry = FlowEntry.from_dict(
        {
            "name": "PickPlace",
            "steps": [
                {"step_id": 1, "action": "move", "func_id": 108},
                {"step_id": 2, "action": "delay", "func_id": 110, "params": {"seconds": 1}},
            ],
            "step_delay_ms": 500,
        }
    )
    assert entry.name == "PickPlace"
    assert len(entry.steps) == 2
    assert entry.steps[0].func_id == 108
    assert entry.steps[1].params == {"seconds": 1}
    assert entry.step_delay_ms == 500
    assert entry.state == FlowState.IDLE.value


def test_valid_transitions_allow_idle_to_ready() -> None:
    assert FlowState.READY in VALID_TRANSITIONS[FlowState.IDLE]
    assert FlowState.COMPLETED in VALID_TRANSITIONS[FlowState.RUNNING]
    # No direct jump from IDLE to RUNNING.
    assert FlowState.RUNNING not in VALID_TRANSITIONS[FlowState.IDLE]
