from __future__ import annotations

from robot_ai.models import RobotState


def test_cancel_latch_defaults_false() -> None:
    assert RobotState().cancel_latch is False


def test_cancel_latch_in_to_dict() -> None:
    assert RobotState(cancel_latch=True).to_dict()["cancel_latch"] is True
