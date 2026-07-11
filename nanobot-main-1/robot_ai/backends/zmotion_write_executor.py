from __future__ import annotations

import time
from typing import Protocol

from robot_ai.backends.zmotion_backend import (
    STATUS_ALARM_BIT,
    STATUS_ESTOP_BIT,
    STATUS_PAUSED_BIT,
    STATUS_READY_BIT,
    ModbusReadRequest,
)
from robot_ai.backends.zmotion_sdk import ModbusWriteRequest, ZMotionSdkError
from robot_ai.backends.zmotion_write_plan import ZMotionCommandPlan, ZMotionWriteDraft
from robot_ai.models import ToolResult


class ZMotionPlanWriteClient(Protocol):
    def write_modbus_float(
        self,
        request: ModbusWriteRequest,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> None: ...

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]: ...

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]: ...


class ZMotionWriteExecutor:
    """Verifies and submits one restricted plan through the guarded SDK client."""

    def __init__(
        self,
        client: ZMotionPlanWriteClient,
        *,
        echo_tolerance: float = 1e-4,
        pose_tolerance: float = 0.1,
        completion_poll_interval_sec: float = 0.05,
        completion_poll_attempts: int = 3600,
        pose_convergence_attempts: int = 600,
    ) -> None:
        self._client = client
        self._echo_tolerance = max(float(echo_tolerance), 0.0)
        self._pose_tolerance = max(float(pose_tolerance), 0.0)
        self._completion_poll_interval_sec = max(
            float(completion_poll_interval_sec),
            0.0,
        )
        self._completion_poll_attempts = max(int(completion_poll_attempts), 1)
        # The controller's function-DONE bit can fire before physical motion
        # completes (long/slow moves). After DONE, poll the feedback pose until
        # it converges to the target for two consecutive reads, or this budget
        # is exhausted (then it's a real pose_mismatch).
        self._pose_convergence_attempts = max(int(pose_convergence_attempts), 2)

    def execute(
        self,
        plan: ZMotionCommandPlan,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict:
        blocked = self._runtime_gate_result(
            plan,
            allow_real_motion_writes=allow_real_motion_writes,
            confirmed_real_motion=confirmed_real_motion,
        )
        if blocked is not None:
            return blocked

        submitted_count = 0
        current_write: ZMotionWriteDraft | None = None
        try:
            for current_write in plan.parameter_writes:
                self._submit_float(
                    current_write,
                    allow_real_motion_writes=allow_real_motion_writes,
                    confirmed_real_motion=confirmed_real_motion,
                )
                submitted_count += 1
        except ZMotionSdkError as exc:
            return ToolResult.failure(
                state="real_motion_write_failed",
                message=str(exc),
                errors=[{"type": exc.__class__.__name__, "message": str(exc)}],
                data={
                    "action": plan.action,
                    "failed_vr": current_write.vr if current_write is not None else None,
                    "submitted_count": submitted_count,
                    "trigger_submitted": False,
                },
            ).to_dict()

        verification = self._verify_before_trigger(plan)
        if not verification["ok"]:
            return verification

        try:
            self._submit_float(
                plan.trigger_write,
                allow_real_motion_writes=allow_real_motion_writes,
                confirmed_real_motion=confirmed_real_motion,
            )
        except ZMotionSdkError as exc:
            return ToolResult.failure(
                state="real_motion_write_failed",
                message=str(exc),
                errors=[{"type": exc.__class__.__name__, "message": str(exc)}],
                data={
                    "action": plan.action,
                    "failed_vr": plan.trigger_write.vr,
                    "submitted_count": submitted_count,
                    "trigger_submitted": False,
                },
            ).to_dict()

        completion = self._wait_for_completion(plan)
        if not completion["ok"]:
            return completion

        verification_data = verification["data"]
        completion_data = completion["data"]
        return ToolResult.success(
            state="real_motion_command_completed",
            message="The verified ZMotion command completed.",
            data={
                "action": plan.action,
                "function_code": plan.function_code,
                "parameter_write_count": submitted_count,
                "write_count": submitted_count + 1,
                "echo_count": len(plan.expected_echoes),
                "trigger_vr": plan.trigger_write.vr,
                "trigger_submitted": True,
                **verification_data,
                **completion_data,
            },
        ).to_dict()

    @staticmethod
    def _runtime_gate_result(
        plan: ZMotionCommandPlan,
        *,
        allow_real_motion_writes: bool,
        confirmed_real_motion: bool,
    ) -> dict | None:
        if not plan.executable or plan.blockers:
            return ToolResult.failure(
                state="real_motion_plan_blocked",
                message="The ZMotion write plan is blocked and was not submitted.",
                data={"action": plan.action, "blockers": list(plan.blockers)},
            ).to_dict()
        if not allow_real_motion_writes:
            return ToolResult.failure(
                state="real_motion_execution_disabled",
                message="Real ZMotion plan execution is disabled.",
                data={"action": plan.action},
            ).to_dict()
        if not confirmed_real_motion:
            return ToolResult.failure(
                state="real_motion_confirmation_required",
                message="Runtime operator confirmation is required before plan execution.",
                data={"action": plan.action},
            ).to_dict()
        return None

    def _verify_before_trigger(self, plan: ZMotionCommandPlan) -> dict:
        current_vr: int | None = None
        try:
            for current_vr, expected in plan.expected_echoes.items():
                actual = self._read_float(current_vr)
                if abs(actual - expected) > self._echo_tolerance:
                    return ToolResult.failure(
                        state="real_motion_echo_mismatch",
                        message=f"ZMotion command echo mismatch at IEEE({current_vr}).",
                        data={
                            "action": plan.action,
                            "echo_vr": current_vr,
                            "expected": expected,
                            "actual": actual,
                            "trigger_submitted": False,
                        },
                    ).to_dict()

            current_vr = plan.accept_vr
            accept = self._read_float(plan.accept_vr)
            current_vr = 34
            status = self._read_long(34)
            current_vr = 36
            system_state = self._read_long(36)
            current_vr = 38
            alarm = self._read_long(38)
        except Exception as exc:
            return ToolResult.failure(
                state="real_motion_verification_failed",
                message=str(exc),
                errors=[{"type": exc.__class__.__name__, "message": str(exc)}],
                data={
                    "action": plan.action,
                    "failed_vr": current_vr,
                    "trigger_submitted": False,
                },
            ).to_dict()

        state_data = {
            "accept": accept,
            "status": status,
            "system_state": system_state,
            "alarm": alarm,
        }
        if plan.function_code != 104 and self._unsafe_state(
            accept=accept,
            status=status,
            system_state=system_state,
            alarm=alarm,
        ):
            return ToolResult.failure(
                state="real_motion_pretrigger_unsafe",
                message="Controller state changed before the ZMotion trigger.",
                data={
                    "action": plan.action,
                    "trigger_submitted": False,
                    **state_data,
                },
            ).to_dict()

        return ToolResult.success(
            state="real_motion_pretrigger_verified",
            data=state_data,
        ).to_dict()

    def _wait_for_completion(self, plan: ZMotionCommandPlan) -> dict:
        saw_executing = False
        last_data: dict = {}
        current_vr: int | None = None

        for attempt in range(1, self._completion_poll_attempts + 1):
            try:
                current_vr = plan.accept_vr
                accept = self._read_float(plan.accept_vr)
                current_vr = 34
                status = self._read_long(34)
                current_vr = 36
                system_state = self._read_long(36)
                current_vr = 38
                alarm = self._read_long(38)
                current_vr = 324
                current_function = self._read_float(324)
                current_vr = 56
                motion_state = self._read_float(56)
            except Exception as exc:
                return ToolResult.failure(
                    state="real_motion_completion_failed",
                    message=str(exc),
                    errors=[{"type": exc.__class__.__name__, "message": str(exc)}],
                    data={
                        "action": plan.action,
                        "failed_vr": current_vr,
                        "trigger_submitted": True,
                    },
                ).to_dict()

            completion_state = _function_state(status, plan.function_code)
            saw_executing = saw_executing or completion_state == 1
            last_data = {
                "accept": accept,
                "status": status,
                "system_state": system_state,
                "alarm": alarm,
                "current_function": current_function,
                "motion_state": motion_state,
                "completion_state": completion_state,
                "completion_attempts": attempt,
                "saw_executing": saw_executing,
                "trigger_submitted": True,
            }

            # Release actions (release_emergency_stop / release_cancel) only
            # clear the host's e-stop/cancel REQUEST — the actual alarm/
            # estop_flag stays until alarm_reset runs the full reset routine
            # (which gates on host_estop == 0). The Func104 completion byte is
            # not a meaningful success signal for a release: the controller may
            # leave it pending (0), set DONE (2), or report error (3) with the
            # lingering alarm, and the ESTOP/cancel status bit only clears
            # after alarm_reset. The parameter echoes were already verified
            # before the trigger, and the controller sets host_estop /
            # host_cancel -> 0 in its 1ms loop, so once the trigger is submitted
            # and the first poll returns (controller responsive), the release
            # has taken effect. Return success on the first responsive poll;
            # the operator must still run alarm_reset to clear the remaining
            # alarm (the status panel shows it). Real failures (write/echo/
            # read errors) are caught elsewhere.
            if plan.action in _RELEASE_ACTIONS:
                return ToolResult.success(
                    state="real_motion_command_completed",
                    data=last_data,
                ).to_dict()

            if completion_state == 3:
                return ToolResult.failure(
                    state="real_motion_command_failed",
                    message="The controller reported a command error.",
                    data={"action": plan.action, **last_data},
                ).to_dict()

            if plan.function_code == 104:
                if int(accept) == 0 and _system_action_reached(
                    action=plan.action,
                    status=status,
                ):
                    return ToolResult.success(
                        state="real_motion_command_completed",
                        data=last_data,
                    ).to_dict()
            else:
                unsafe_mask = (
                    (1 << STATUS_ALARM_BIT)
                    | (1 << STATUS_ESTOP_BIT)
                    | (1 << STATUS_PAUSED_BIT)
                )
                if int(alarm) != 0 or (int(status) & unsafe_mask) != 0:
                    return ToolResult.failure(
                        state="real_motion_command_failed",
                        message="The controller reported an unsafe command state.",
                        data={"action": plan.action, **last_data},
                    ).to_dict()
                if int(accept) == 0 and completion_state == 2:
                    if plan.function_code == 108:
                        pose_result = self._verify_func108_pose(plan, last_data)
                        if pose_result is not None:
                            return pose_result
                    return ToolResult.success(
                        state="real_motion_command_completed",
                        data=last_data,
                    ).to_dict()

            if (
                attempt < self._completion_poll_attempts
                and self._completion_poll_interval_sec > 0.0
            ):
                time.sleep(self._completion_poll_interval_sec)

        return ToolResult.failure(
            state="real_motion_completion_timeout",
            message="Timed out waiting for the ZMotion command to complete.",
            data={"action": plan.action, **last_data},
        ).to_dict()

    def _verify_func108_pose(
        self,
        plan: ZMotionCommandPlan,
        completion_data: dict,
    ) -> dict | None:
        values_by_vr = {write.vr: write.value for write in plan.parameter_writes}
        expected_pose = [float(values_by_vr[vr]) for vr in range(2, 14, 2)]
        # DONE can fire before physical motion completes; poll the feedback pose
        # until it stabilises at the target (two consecutive within-tolerance
        # reads) or the convergence budget is exhausted.
        consecutive = 0
        actual_pose: list[float] = []
        for attempt in range(1, self._pose_convergence_attempts + 1):
            try:
                actual_pose = self._read_floats(1612, 6)
            except Exception as exc:
                return ToolResult.failure(
                    state="real_motion_completion_failed",
                    message=str(exc),
                    errors=[{"type": exc.__class__.__name__, "message": str(exc)}],
                    data={
                        "action": plan.action,
                        "failed_vr": 1612,
                        **completion_data,
                    },
                ).to_dict()
            if all(
                abs(actual - expected) <= self._pose_tolerance
                for actual, expected in zip(actual_pose, expected_pose, strict=True)
            ):
                consecutive += 1
                if consecutive >= 2:
                    completion_data["expected_pose"] = expected_pose
                    completion_data["actual_pose"] = actual_pose
                    completion_data["pose_convergence_attempts"] = attempt
                    return None
            else:
                consecutive = 0
            if (
                attempt < self._pose_convergence_attempts
                and self._completion_poll_interval_sec > 0.0
            ):
                time.sleep(self._completion_poll_interval_sec)

        completion_data["expected_pose"] = expected_pose
        completion_data["actual_pose"] = actual_pose
        completion_data["pose_convergence_attempts"] = self._pose_convergence_attempts
        return ToolResult.failure(
            state="real_motion_pose_mismatch",
            message="Func108 DONE set but the feedback pose did not converge to the target.",
            data={
                "action": plan.action,
                "expected_pose": expected_pose,
                "actual_pose": actual_pose,
                **completion_data,
            },
        ).to_dict()

    @staticmethod
    def _unsafe_state(
        *,
        accept: float,
        status: int,
        system_state: int,
        alarm: int,
    ) -> bool:
        # LONG(34) bits 24/25/26 (alarm/estop/paused) are the authoritative
        # unsafe indicators. system_state (LONG(36)) is diagnostic only — its
        # bit5 cancel-latch is benign history and must not block motion (the
        # legacy project's precheck does not gate on system_state either).
        del system_state  # kept in the signature for diagnostic data reporting
        unsafe_mask = (
            (1 << STATUS_ALARM_BIT)
            | (1 << STATUS_ESTOP_BIT)
            | (1 << STATUS_PAUSED_BIT)
        )
        return (
            int(accept) != 0
            or int(alarm) != 0
            or (int(status) & unsafe_mask) != 0
            or (int(status) & (1 << STATUS_READY_BIT)) == 0
        )

    def _read_float(self, vr: int) -> float:
        values = self._client.read_modbus_float(
            ModbusReadRequest(start_vr=vr, count=1)
        )
        if not values:
            raise ZMotionSdkError(f"Empty ZMotion float read at VR {vr}")
        return float(values[0])

    def _read_long(self, vr: int) -> int:
        values = self._client.read_modbus_long(
            ModbusReadRequest(start_vr=vr, count=1)
        )
        if not values:
            raise ZMotionSdkError(f"Empty ZMotion long read at VR {vr}")
        return int(values[0])

    def _read_floats(self, vr: int, count: int) -> list[float]:
        values = self._client.read_modbus_float(
            ModbusReadRequest(start_vr=vr, count=count)
        )
        if len(values) < count:
            raise ZMotionSdkError(
                f"Incomplete ZMotion float read at VR {vr}: "
                f"expected {count}, got {len(values)}"
            )
        return [float(value) for value in values[:count]]

    def _submit_float(
        self,
        write: ZMotionWriteDraft,
        *,
        allow_real_motion_writes: bool,
        confirmed_real_motion: bool,
    ) -> None:
        if write.kind != "float":
            raise ZMotionSdkError(f"Unsupported ZMotion write kind: {write.kind}")
        self._client.write_modbus_float(
            ModbusWriteRequest(start_vr=write.vr, values=[write.value]),
            allow_real_motion_writes=allow_real_motion_writes,
            confirmed_real_motion=confirmed_real_motion,
        )


_FUNCTION_STATE_FIELDS: dict[int, tuple[int, int]] = {
    104: (0, 0x00000003),
    108: (6, 0x000000C0),
    110: (10, 0x00000C00),
    120: (18, 0x000C0000),
}


def _function_state(status: int, function_code: int) -> int:
    shift, mask = _FUNCTION_STATE_FIELDS[function_code]
    return (int(status) & mask) >> shift


# Release actions clear only the host's e-stop/cancel REQUEST. The alarm/
# estop_flag persists until alarm_reset, so in alarm state Func104 reports
# completion_state==3 (error) even though the release write took effect —
# treat that as success (see ZMotionWriteExecutor._wait_for_completion).
_RELEASE_ACTIONS = frozenset({"release_emergency_stop", "release_cancel"})


def _system_action_reached(*, action: str, status: int) -> bool:
    bit_expectations = {
        "emergency_stop": (STATUS_ESTOP_BIT, True),
        "release_emergency_stop": (STATUS_ESTOP_BIT, False),
        "pause": (STATUS_PAUSED_BIT, True),
        "resume": (STATUS_PAUSED_BIT, False),
        "stop_current": (27, True),
        "release_cancel": (27, False),
        "alarm_reset": (STATUS_ALARM_BIT, False),
    }
    bit, expected = bit_expectations[action]
    return ((int(status) & (1 << bit)) != 0) is expected
