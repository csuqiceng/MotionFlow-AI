from __future__ import annotations

from robot_ai.models import RobotState


def test_cancel_latch_defaults_false() -> None:
    assert RobotState().cancel_latch is False


def test_cancel_latch_in_to_dict() -> None:
    assert RobotState(cancel_latch=True).to_dict()["cancel_latch"] is True


def test_joint_feedback_is_included_in_to_dict() -> None:
    state = RobotState(joints_deg=[1.0, -2.5, 3.0, 4.0, 5.0, 6.0])

    assert state.to_dict()["joints_deg"] == [1.0, -2.5, 3.0, 4.0, 5.0, 6.0]
