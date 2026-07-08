from __future__ import annotations

from robot_ai.backends.zmotion_backend import ModbusReadRequest
from robot_ai.backends.zmotion_sdk import ModbusWriteRequest, ZMotionSdkError
from robot_ai.backends.zmotion_write_plan import ZMOTION_TRIGGER_VR, ZMotionWritePlanner
from robot_ai.models import RobotState


SAFE_STATUS = 268435584


class FakePlanWriteClient:
    def __init__(
        self,
        *,
        float_values: dict[int, float] | None = None,
        float_blocks: dict[int, list[float]] | None = None,
        long_values: dict[int, int] | None = None,
        long_sequences: dict[int, list[int]] | None = None,
        fail_write_vr: int | None = None,
        fail_read_vr: int | None = None,
    ) -> None:
        self.float_values = dict(float_values or {})
        self.float_blocks = dict(float_blocks or {})
        self.long_values = {34: SAFE_STATUS, 36: 0, 38: 0, **(long_values or {})}
        self.long_sequences = {
            vr: list(values) for vr, values in (long_sequences or {}).items()
        }
        self.fail_write_vr = fail_write_vr
        self.fail_read_vr = fail_read_vr
        self.events: list[tuple[str, int, list[float] | None, bool, bool]] = []

    def write_modbus_float(
        self,
        request: ModbusWriteRequest,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> None:
        self.events.append(
            (
                "write_float",
                request.start_vr,
                [float(value) for value in request.values],
                allow_real_motion_writes,
                confirmed_real_motion,
            )
        )
        if request.start_vr == self.fail_write_vr:
            raise ZMotionSdkError(f"fake write failure at VR {request.start_vr}")

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]:
        self.events.append(("read_float", request.start_vr, None, False, False))
        if request.start_vr == self.fail_read_vr:
            raise ZMotionSdkError(f"fake read failure at VR {request.start_vr}")
        if request.start_vr in self.float_blocks:
            return list(self.float_blocks[request.start_vr])[: request.count]
        return [float(self.float_values.get(request.start_vr, 0.0))]

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]:
        self.events.append(("read_long", request.start_vr, None, False, False))
        if request.start_vr == self.fail_read_vr:
            raise ZMotionSdkError(f"fake read failure at VR {request.start_vr}")
        sequence = self.long_sequences.get(request.start_vr)
        if sequence:
            value = sequence.pop(0) if len(sequence) > 1 else sequence[0]
            return [int(value)]
        return [int(self.long_values.get(request.start_vr, 0))]


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


def _executable_plan():
    return ZMotionWritePlanner().plan_linear_move(
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
        confirmed_real_motion=True,
        allow_real_motion_writes=True,
    )


def _client_for_plan(plan, **kwargs) -> FakePlanWriteClient:
    target_pose = [write.value for write in plan.parameter_writes[1:7]]
    return FakePlanWriteClient(
        float_values={**plan.expected_echoes, plan.accept_vr: 0.0},
        float_blocks={1612: target_pose},
        **kwargs,
    )


def test_executor_rejects_blocked_plan_without_io() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    client = FakePlanWriteClient()
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

    result = ZMotionWriteExecutor(client).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_plan_blocked"
    assert client.events == []


def test_executor_runtime_gates_produce_no_io() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    disabled = FakePlanWriteClient()
    unconfirmed = FakePlanWriteClient()

    disabled_result = ZMotionWriteExecutor(disabled).execute(plan)
    unconfirmed_result = ZMotionWriteExecutor(unconfirmed).execute(
        plan,
        allow_real_motion_writes=True,
    )

    assert disabled_result["state"] == "real_motion_execution_disabled"
    assert unconfirmed_result["state"] == "real_motion_confirmation_required"
    assert disabled.events == []
    assert unconfirmed.events == []


def test_executor_verifies_echo_and_state_before_triggering_last() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    client = _client_for_plan(plan)

    result = ZMotionWriteExecutor(client).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_command_completed"
    assert result["data"]["parameter_write_count"] == 16
    assert result["data"]["echo_count"] == 16
    event_pairs = [(event[0], event[1]) for event in client.events]
    assert event_pairs[:16] == [
        ("write_float", vr) for vr in range(0, 32, 2)
    ]
    assert event_pairs[16:32] == [
        ("read_float", vr) for vr in range(280, 312, 2)
    ]
    assert event_pairs[32:36] == [
        ("read_float", 312),
        ("read_long", 34),
        ("read_long", 36),
        ("read_long", 38),
    ]
    assert event_pairs[36] == ("write_float", ZMOTION_TRIGGER_VR)
    assert client.events[36][3:] == (True, True)
    assert event_pairs[37:43] == [
        ("read_float", 312),
        ("read_long", 34),
        ("read_long", 36),
        ("read_long", 38),
        ("read_float", 324),
        ("read_float", 56),
    ]
    assert event_pairs[-1] == ("read_float", 1612)
    assert result["data"]["completion_state"] == 2
    assert result["data"]["actual_pose"] == [900.0, 0.0, 999.0, 0.0, 0.0, 0.0]


def test_executor_blocks_trigger_on_echo_mismatch() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    client = _client_for_plan(plan)
    client.float_values[286] = 998.0

    result = ZMotionWriteExecutor(client).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_echo_mismatch"
    assert result["data"]["echo_vr"] == 286
    assert result["data"]["expected"] == 999.0
    assert result["data"]["actual"] == 998.0
    assert ("write_float", ZMOTION_TRIGGER_VR) not in [
        (event[0], event[1]) for event in client.events
    ]


def test_executor_blocks_trigger_on_unsafe_pretrigger_state() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    client = _client_for_plan(plan, long_values={38: 7})

    result = ZMotionWriteExecutor(client).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_pretrigger_unsafe"
    assert result["data"]["alarm"] == 7
    assert result["data"]["trigger_submitted"] is False


def test_executor_stops_before_verification_when_parameter_write_fails() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    client = _client_for_plan(plan, fail_write_vr=4)

    result = ZMotionWriteExecutor(client).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_write_failed"
    assert [(event[0], event[1]) for event in client.events] == [
        ("write_float", 0),
        ("write_float", 2),
        ("write_float", 4),
    ]
    assert result["data"]["failed_vr"] == 4


def test_executor_blocks_trigger_when_verification_read_fails() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    client = _client_for_plan(plan, fail_read_vr=284)

    result = ZMotionWriteExecutor(client).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_verification_failed"
    assert result["data"]["failed_vr"] == 284
    assert result["data"]["trigger_submitted"] is False


def test_executor_waits_for_func108_execution_then_completion() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    ready = 1 << 28
    client = _client_for_plan(
        plan,
        long_sequences={34: [SAFE_STATUS, ready | (1 << 6), ready | (2 << 6)]},
    )

    result = ZMotionWriteExecutor(
        client,
        completion_poll_interval_sec=0.0,
        completion_poll_attempts=3,
    ).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_command_completed"
    assert result["data"]["saw_executing"] is True
    assert [
        event[:2] for event in client.events if event[:2] == ("read_long", 34)
    ] == [("read_long", 34), ("read_long", 34), ("read_long", 34)]


def test_executor_reports_completion_timeout_without_another_trigger() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    executing = (1 << 28) | (1 << 6)
    client = _client_for_plan(
        plan,
        long_sequences={34: [SAFE_STATUS, executing]},
    )

    result = ZMotionWriteExecutor(
        client,
        completion_poll_interval_sec=0.0,
        completion_poll_attempts=2,
    ).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_completion_timeout"
    assert result["data"]["trigger_submitted"] is True
    assert [event[:2] for event in client.events].count(
        ("write_float", ZMOTION_TRIGGER_VR)
    ) == 1


def test_executor_verifies_func104_emergency_stop_post_state() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = ZMotionWritePlanner().plan_system_control(
        action="emergency_stop",
        robot_state=RobotState(mode="moving", connected_real_device=True),
        confirmed_real_motion=True,
        allow_real_motion_writes=True,
    )
    client = _client_for_plan(
        plan,
        long_sequences={34: [SAFE_STATUS, 1 << 25]},
    )

    result = ZMotionWriteExecutor(
        client,
        completion_poll_interval_sec=0.0,
        completion_poll_attempts=2,
    ).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_command_completed"
    assert result["data"]["action"] == "emergency_stop"


def test_executor_blocks_sequence_progress_on_final_pose_mismatch() -> None:
    from robot_ai.backends.zmotion_write_executor import ZMotionWriteExecutor

    plan = _executable_plan()
    client = _client_for_plan(plan)
    client.float_blocks[1612] = [900.0, 0.0, 995.0, 0.0, 0.0, 0.0]

    result = ZMotionWriteExecutor(
        client, pose_convergence_attempts=3, completion_poll_interval_sec=0.0
    ).execute(
        plan,
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert result["state"] == "real_motion_pose_mismatch"
    assert result["data"]["expected_pose"][2] == 999.0
    assert result["data"]["actual_pose"][2] == 995.0
