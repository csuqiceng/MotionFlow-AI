from __future__ import annotations

import pytest

from robot_ai.backends.zmotion_write_plan import (
    ZMOTION_ACCEPT_VR,
    ZMOTION_ECHO_START,
    ZMOTION_TRIGGER_VR,
    ZMotionWritePlanner,
)
from robot_ai.models import AXIS_NAMES, RobotState


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


def _unlocked() -> dict[str, bool]:
    return {
        "confirmed_real_motion": True,
        "allow_real_motion_writes": True,
    }


def test_func108_linear_plan_uses_complete_absolute_pose_at_even_vrs() -> None:
    plan = ZMotionWritePlanner().plan_linear_move(
        target_pose={
            "x": 900.0,
            "y": 0.0,
            "z": 999.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        },
        robot_state=_safe_state(),
        speed_pct=5.0,
        acceleration_pct=5.0,
        deceleration_pct=5.0,
        **_unlocked(),
    )

    assert plan.executable is True
    assert plan.action == "linear_move"
    assert plan.function_code == 108
    assert [write.vr for write in plan.parameter_writes] == list(range(0, 32, 2))
    assert [write.value for write in plan.parameter_writes] == [
        108.0,
        900.0,
        0.0,
        999.0,
        0.0,
        0.0,
        0.0,
        5.0,
        5.0,
        5.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    ]
    assert plan.expected_echoes == {
        ZMOTION_ECHO_START + write.vr: write.value for write in plan.parameter_writes
    }
    assert plan.expected_echoes[286] == 999.0
    assert plan.trigger_write.vr == ZMOTION_TRIGGER_VR
    assert plan.accept_vr == ZMOTION_ACCEPT_VR


def test_func108_plan_is_blocked_without_runtime_gates() -> None:
    plan = ZMotionWritePlanner().plan_linear_move(
        target_pose={
            "x": 905.0,
            "y": 0.0,
            "z": 1000.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        },
        robot_state=_safe_state(),
    )

    assert plan.executable is False
    assert "operator_confirmation_missing" in plan.blockers
    assert "real_motion_writes_disabled" in plan.blockers
    assert plan.to_dict()["executable"] is False
    assert plan.to_dict()["function_code"] == 108


def test_func108_plan_blocks_invalid_pose_values_and_unsafe_controller() -> None:
    planner = ZMotionWritePlanner()

    missing_axis = planner.plan_linear_move(
        target_pose={
            "x": 900.0,
            "y": 0.0,
            "z": 1000.0,
            "rx": 0.0,
            "ry": 0.0,
        },
        robot_state=_safe_state(),
        **_unlocked(),
    )
    invalid_number = planner.plan_linear_move(
        target_pose={
            "x": float("nan"),
            "y": 0.0,
            "z": 1000.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        },
        robot_state=_safe_state(),
        **_unlocked(),
    )
    alarm_state = RobotState(
        mode="alarm",
        axes_mm={axis: 0.0 for axis in AXIS_NAMES},
        connected_real_device=True,
        alarms=["controller_alarm"],
    )
    unsafe = planner.plan_linear_move(
        target_pose={axis: 0.0 for axis in AXIS_NAMES},
        robot_state=alarm_state,
        **_unlocked(),
    )

    assert "invalid_target_pose" in missing_axis.blockers
    assert "invalid_target_pose" in invalid_number.blockers
    assert "controller_not_idle" in unsafe.blockers
    assert "controller_alarm_active" in unsafe.blockers


def test_planner_no_longer_exposes_axis_increment_motion() -> None:
    planner = ZMotionWritePlanner()

    assert not hasattr(planner, "plan_move_axis")


@pytest.mark.parametrize(
    ("action", "expected_values"),
    [
        ("emergency_stop", [104.0, 1.0, 0.0, 0.0, 0.0]),
        ("release_emergency_stop", [104.0, 2.0, 0.0, 0.0, 0.0]),
        ("pause", [104.0, 0.0, 1.0, 0.0, 0.0]),
        ("resume", [104.0, 0.0, 2.0, 0.0, 0.0]),
        ("stop_current", [104.0, 0.0, 0.0, 1.0, 0.0]),
        ("release_cancel", [104.0, 0.0, 0.0, 2.0, 0.0]),
    ],
)
def test_func104_supports_only_requested_system_controls(
    action: str,
    expected_values: list[float],
) -> None:
    moving_alarm_state = RobotState(
        mode="moving",
        connected_real_device=True,
        alarms=["active_alarm"],
    )

    plan = ZMotionWritePlanner().plan_system_control(
        action=action,
        robot_state=moving_alarm_state,
        **_unlocked(),
    )

    assert plan.executable is True
    assert plan.function_code == 104
    assert [write.vr for write in plan.parameter_writes] == [0, 2, 4, 6, 8]
    assert [write.value for write in plan.parameter_writes] == expected_values


def test_func104_rejects_unrequested_system_control() -> None:
    plan = ZMotionWritePlanner().plan_system_control(
        action="reboot",
        robot_state=_safe_state(),
        **_unlocked(),
    )

    assert plan.executable is False
    assert plan.function_code == 104
    assert plan.parameter_writes == []
    assert "unsupported_system_action" in plan.blockers


def test_func104_alarm_reset_writes_ieee8() -> None:
    plan = ZMotionWritePlanner().plan_system_control(
        action="alarm_reset",
        robot_state=_safe_state(),
        **_unlocked(),
    )
    assert plan.executable is True
    assert plan.function_code == 104
    assert [(write.vr, write.value) for write in plan.parameter_writes] == [
        (0, 104.0),
        (2, 0.0),
        (4, 0.0),
        (6, 0.0),
        (8, 1.0),
    ]


def test_func110_delay_and_func120_io_use_confirmed_payloads() -> None:
    planner = ZMotionWritePlanner()

    delay = planner.plan_delay(
        seconds=0.25,
        robot_state=_safe_state(),
        **_unlocked(),
    )
    io = planner.plan_io(
        io_number=3,
        enabled=True,
        allowed_io_channels={2, 3, 4},
        robot_state=_safe_state(),
        **_unlocked(),
    )

    assert delay.function_code == 110
    assert [(write.vr, write.value) for write in delay.parameter_writes] == [
        (0, 110.0),
        (6, 0.25),
    ]
    assert io.function_code == 120
    assert [(write.vr, write.value) for write in io.parameter_writes] == [
        (0, 120.0),
        (2, 3.0),
        (4, 1.0),
    ]


def test_delay_and_io_validation_block_invalid_values() -> None:
    planner = ZMotionWritePlanner()

    delay = planner.plan_delay(
        seconds=0.0,
        robot_state=_safe_state(),
        **_unlocked(),
    )
    io = planner.plan_io(
        io_number=9,
        enabled=False,
        allowed_io_channels={1, 2},
        robot_state=_safe_state(),
        **_unlocked(),
    )

    assert delay.executable is False
    assert "invalid_delay" in delay.blockers
    assert io.executable is False
    assert "io_channel_not_allowed" in io.blockers
