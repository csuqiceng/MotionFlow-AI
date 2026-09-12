from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Collection

from robot_platform.models import AXIS_NAMES, RobotState


ZMOTION_COMMAND_PARAM_START = 0
ZMOTION_PARAMETER_VRS = tuple(range(0, 32, 2))
ZMOTION_TRIGGER_VR = 32
ZMOTION_ECHO_START = 280
ZMOTION_ACCEPT_VR = 312
ZMOTION_SUPPORTED_FUNCTIONS = frozenset({104, 108, 110, 120})

_SYSTEM_CONTROL_VALUES: dict[str, tuple[int, int, int, int]] = {
    # (estop_ctrl@IEEE2, pause_ctrl@IEEE4, cancel_ctrl@IEEE6, alarm_reset@IEEE8)
    "emergency_stop": (1, 0, 0, 0),
    "release_emergency_stop": (2, 0, 0, 0),
    "pause": (0, 1, 0, 0),
    "resume": (0, 2, 0, 0),
    "stop_current": (0, 0, 1, 0),
    "release_cancel": (0, 0, 2, 0),
    "alarm_reset": (0, 0, 0, 1),
}


@dataclass(frozen=True)
class ZMotionWriteDraft:
    kind: str
    vr: int
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "vr": self.vr, "value": self.value}


@dataclass(frozen=True)
class ZMotionCommandPlan:
    action: str
    function_code: int
    executable: bool
    blockers: list[str]
    parameter_writes: list[ZMotionWriteDraft]
    expected_echoes: dict[int, float]
    trigger_write: ZMotionWriteDraft
    echo_start_vr: int
    accept_vr: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "function_code": self.function_code,
            "executable": self.executable,
            "blockers": list(self.blockers),
            "parameter_writes": [write.to_dict() for write in self.parameter_writes],
            "expected_echoes": dict(self.expected_echoes),
            "trigger_write": self.trigger_write.to_dict(),
            "echo_start_vr": self.echo_start_vr,
            "accept_vr": self.accept_vr,
            "write_execution": "disabled_by_default",
        }


# Compatibility for the executor while its protocol is migrated separately.
ZMotionMotionWritePlan = ZMotionCommandPlan


class ZMotionWritePlanner:
    """Builds the restricted legacy ZMotion command set without controller IO."""

    def plan_linear_move(
        self,
        *,
        target_pose: dict[str, float],
        robot_state: RobotState,
        speed_pct: float = 5.0,
        acceleration_pct: float = 5.0,
        deceleration_pct: float = 5.0,
        motion_percent_limit: float = 100.0,
        confirmed_real_motion: bool = False,
        allow_real_motion_writes: bool = False,
    ) -> ZMotionCommandPlan:
        return self._plan_linear_move(
            action="linear_move",
            target_pose=target_pose,
            robot_state=robot_state,
            speed_pct=speed_pct,
            acceleration_pct=acceleration_pct,
            deceleration_pct=deceleration_pct,
            motion_percent_limit=motion_percent_limit,
            confirmed_real_motion=confirmed_real_motion,
            allow_real_motion_writes=allow_real_motion_writes,
            extra_blockers=[],
        )

    def plan_system_control(
        self,
        *,
        action: str,
        robot_state: RobotState,
        confirmed_real_motion: bool = False,
        allow_real_motion_writes: bool = False,
    ) -> ZMotionCommandPlan:
        blockers = self._gate_blockers(
            robot_state=robot_state,
            confirmed_real_motion=confirmed_real_motion,
            allow_real_motion_writes=allow_real_motion_writes,
            require_safe_state=False,
        )
        values = _SYSTEM_CONTROL_VALUES.get(action)
        if values is None:
            blockers.append("unsupported_system_action")
            writes: list[ZMotionWriteDraft] = []
        else:
            estop_ctrl, pause_ctrl, cancel_ctrl, reset_ctrl = values
            writes = _float_writes(
                [
                    (0, 104),
                    (2, estop_ctrl),
                    (4, pause_ctrl),
                    (6, cancel_ctrl),
                    (8, reset_ctrl),
                ]
            )
        return _command_plan(
            action=action,
            function_code=104,
            blockers=blockers,
            writes=writes,
        )

    def plan_delay(
        self,
        *,
        seconds: float,
        robot_state: RobotState,
        confirmed_real_motion: bool = False,
        allow_real_motion_writes: bool = False,
    ) -> ZMotionCommandPlan:
        blockers = self._gate_blockers(
            robot_state=robot_state,
            confirmed_real_motion=confirmed_real_motion,
            allow_real_motion_writes=allow_real_motion_writes,
            require_safe_state=True,
        )
        if not _is_finite(seconds) or float(seconds) <= 0.0:
            blockers.append("invalid_delay")
        writes = _float_writes([(0, 110), (6, seconds if _is_finite(seconds) else 0.0)])
        return _command_plan(
            action="delay",
            function_code=110,
            blockers=blockers,
            writes=writes,
        )

    def plan_io(
        self,
        *,
        io_number: int,
        enabled: bool,
        allowed_io_channels: Collection[int],
        robot_state: RobotState,
        confirmed_real_motion: bool = False,
        allow_real_motion_writes: bool = False,
    ) -> ZMotionCommandPlan:
        blockers = self._gate_blockers(
            robot_state=robot_state,
            confirmed_real_motion=confirmed_real_motion,
            allow_real_motion_writes=allow_real_motion_writes,
            require_safe_state=True,
        )
        if io_number not in allowed_io_channels:
            blockers.append("io_channel_not_allowed")
        writes = _float_writes([(0, 120), (2, io_number), (4, int(bool(enabled)))])
        return _command_plan(
            action="io",
            function_code=120,
            blockers=blockers,
            writes=writes,
        )

    def _plan_linear_move(
        self,
        *,
        action: str,
        target_pose: dict[str, float],
        robot_state: RobotState,
        speed_pct: float,
        acceleration_pct: float,
        deceleration_pct: float,
        motion_percent_limit: float,
        confirmed_real_motion: bool,
        allow_real_motion_writes: bool,
        extra_blockers: list[str],
    ) -> ZMotionCommandPlan:
        blockers = self._gate_blockers(
            robot_state=robot_state,
            confirmed_real_motion=confirmed_real_motion,
            allow_real_motion_writes=allow_real_motion_writes,
            require_safe_state=True,
        )
        blockers.extend(extra_blockers)

        pose_values: list[float] = []
        if set(target_pose) != set(AXIS_NAMES):
            blockers.append("invalid_target_pose")
        for axis in AXIS_NAMES:
            value = target_pose.get(axis, 0.0)
            if not _is_finite(value):
                blockers.append("invalid_target_pose")
            pose_values.append(float(value) if _is_finite(value) else 0.0)

        percentages = (speed_pct, acceleration_pct, deceleration_pct)
        if (
            not _is_finite(motion_percent_limit)
            or float(motion_percent_limit) <= 0.0
            or any(
                not _is_finite(value)
                or float(value) <= 0.0
                or float(value) > float(motion_percent_limit)
                for value in percentages
            )
        ):
            blockers.append("invalid_motion_percent")

        values = [
            108.0,
            *pose_values,
            float(speed_pct) if _is_finite(speed_pct) else 0.0,
            float(acceleration_pct) if _is_finite(acceleration_pct) else 0.0,
            float(deceleration_pct) if _is_finite(deceleration_pct) else 0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ]
        writes = _float_writes(list(zip(ZMOTION_PARAMETER_VRS, values, strict=True)))
        return _command_plan(
            action=action,
            function_code=108,
            blockers=_unique(blockers),
            writes=writes,
        )

    @staticmethod
    def _gate_blockers(
        *,
        robot_state: RobotState,
        confirmed_real_motion: bool,
        allow_real_motion_writes: bool,
        require_safe_state: bool,
    ) -> list[str]:
        blockers: list[str] = []
        if not confirmed_real_motion:
            blockers.append("operator_confirmation_missing")
        if not allow_real_motion_writes:
            blockers.append("real_motion_writes_disabled")
        if not robot_state.connected_real_device:
            blockers.append("real_device_not_connected")
        if require_safe_state:
            if robot_state.mode != "idle":
                blockers.append("controller_not_idle")
            if robot_state.alarms:
                blockers.append("controller_alarm_active")
        return blockers


def _command_plan(
    *,
    action: str,
    function_code: int,
    blockers: list[str],
    writes: list[ZMotionWriteDraft],
) -> ZMotionCommandPlan:
    normalized_blockers = _unique(blockers)
    return ZMotionCommandPlan(
        action=action,
        function_code=function_code,
        executable=not normalized_blockers,
        blockers=normalized_blockers,
        parameter_writes=writes,
        expected_echoes={
            ZMOTION_ECHO_START + write.vr: write.value for write in writes
        },
        trigger_write=ZMotionWriteDraft("float", ZMOTION_TRIGGER_VR, 1.0),
        echo_start_vr=ZMOTION_ECHO_START,
        accept_vr=ZMOTION_ACCEPT_VR,
    )


def _float_writes(values: list[tuple[int, float | int]]) -> list[ZMotionWriteDraft]:
    return [
        ZMotionWriteDraft("float", int(vr), float(value))
        for vr, value in values
    ]


def _is_finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
