from __future__ import annotations

from pathlib import Path

import pytest

from robot_ai.backends.factory import RobotBackendConfig
from robot_ai.backends.zmotion_backend import ModbusReadRequest
from robot_ai.backends.zmotion_sdk import ModbusWriteRequest
from robot_ai.models import ToolResult


SAFE_STATUS = 268435584


class FakeOperatorClient:
    def __init__(self) -> None:
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.float_writes: list[ModbusWriteRequest] = []

    def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]:
        if request.start_vr == 1612:
            return [900.0, 0.0, 1000.0, 0.0, 0.0, 0.0]
        if request.start_vr == 56:
            return [270.0]
        return [0.0] * request.count

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]:
        if request.start_vr == 34:
            return [SAFE_STATUS]
        if request.start_vr == 38:
            return [0]
        return [0] * request.count

    def write_modbus_float(
        self,
        request: ModbusWriteRequest,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> None:
        self.float_writes.append(request)


class FakeExecutor:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result or ToolResult.success(
            state="real_motion_command_completed"
        ).to_dict()
        self.calls: list[tuple[object, bool, bool]] = []

    def execute(
        self,
        plan,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict:
        self.calls.append(
            (plan, allow_real_motion_writes, confirmed_real_motion)
        )
        return self.result


def _config() -> RobotBackendConfig:
    return RobotBackendConfig(
        mode="zmotion_readonly",
        controller_host="10.168.3.21",
        zmotion_wrapper_path=str(Path("vendor/zauxdllPython.py")),
        zmotion_dll_dir=str(Path("vendor/dll")),
    )


def _linear_parameters(**overrides) -> dict:
    values = {
        "target_pose": {
            "x": 900.0,
            "y": 0.0,
            "z": 999.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        },
        "speed_pct": 5.0,
        "acceleration_pct": 5.0,
        "deceleration_pct": 5.0,
        "r_min": 800.0,
        "r_max": 1000.0,
        "z_min": 900.0,
        "z_max": 1100.0,
    }
    values.update(overrides)
    return values


def _linear_path_parameters(**overrides) -> dict:
    base = _linear_parameters()
    values = {
        **base,
        "target_poses": [
            dict(base["target_pose"]),
            {**base["target_pose"], "z": 998.0},
        ],
    }
    del values["target_pose"]
    values.update(overrides)
    return values


def _real_request(command: str, parameters: dict):
    from robot_ai.zmotion_operator_control import (
        REAL_EXECUTION_CONFIRMATION_CODE,
        ZMotionOperatorRequest,
    )

    return ZMotionOperatorRequest(
        command=command,
        parameters=parameters,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE,
    )


def test_operator_default_dry_run_reads_state_without_writes() -> None:
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    client = FakeOperatorClient()
    executor_created = False

    def executor_factory(_client):
        nonlocal executor_created
        executor_created = True
        return FakeExecutor()

    result = run_zmotion_operator_command(
        request=ZMotionOperatorRequest(
            command="linear_move",
            parameters=_linear_parameters(),
        ),
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=executor_factory,
    )

    assert result["ok"] is True
    assert result["state"] == "zmotion_operator_dry_run"
    assert result["data"]["plan"]["function_code"] == 108
    assert result["data"]["plan"]["write_execution"] == "disabled_by_default"
    assert client.connect_calls == 1
    assert client.disconnect_calls == 1
    assert client.float_writes == []
    assert executor_created is False


def test_operator_missing_configuration_fails_before_client_creation() -> None:
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    created = False

    def client_factory(_config):
        nonlocal created
        created = True
        return FakeOperatorClient()

    result = run_zmotion_operator_command(
        request=ZMotionOperatorRequest(
            command="system",
            parameters={"action": "emergency_stop"},
        ),
        config=RobotBackendConfig(controller_host="10.168.3.21"),
        client_factory=client_factory,
    )

    assert result["state"] == "zmotion_operator_configuration_missing"
    assert created is False


@pytest.mark.parametrize(
    "request_overrides",
    [
        {"execute_real": False},
        {"confirm_work_area_clear": False},
        {"confirm_estop_ready": False},
        {"confirmation_code": "WRONG"},
    ],
)
def test_operator_real_execution_requires_every_confirmation(
    request_overrides: dict,
) -> None:
    from robot_ai.zmotion_operator_control import (
        REAL_EXECUTION_CONFIRMATION_CODE,
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    fields = {
        "execute_real": True,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
        "confirmation_code": REAL_EXECUTION_CONFIRMATION_CODE,
        **request_overrides,
    }
    created = False

    def client_factory(_config):
        nonlocal created
        created = True
        return FakeOperatorClient()

    result = run_zmotion_operator_command(
        request=ZMotionOperatorRequest(
            command="system",
            parameters={"action": "pause"},
            **fields,
        ),
        config=_config(),
        client_factory=client_factory,
    )

    assert result["state"] == "zmotion_operator_confirmation_required"
    assert created is False


def test_operator_real_linear_move_reaches_executor_with_func108_plan() -> None:
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    client = FakeOperatorClient()
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=_real_request("linear_move", _linear_parameters()),
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["state"] == "real_motion_command_completed"
    assert len(executor.calls) == 1
    plan, allow, confirmed = executor.calls[0]
    assert plan.function_code == 108
    assert plan.parameter_writes[3].value == 999.0
    assert (allow, confirmed) == (True, True)
    assert client.disconnect_calls == 1


@pytest.mark.parametrize(
    ("parameters", "expected_state"),
    [
        (
            _linear_parameters(r_min=1000.0, r_max=800.0),
            "zmotion_operator_workspace_invalid",
        ),
        (
            _linear_parameters(r_min=100.0, r_max=800.0),
            "zmotion_operator_target_outside_workspace",
        ),
        (
            _linear_parameters(
                target_pose={
                    "x": 900.0,
                    "y": 0.0,
                    "z": 994.0,
                    "rx": 0.0,
                    "ry": 0.0,
                    "rz": 0.0,
                }
            ),
            "zmotion_operator_first_test_limit_exceeded",
        ),
        (
            _linear_parameters(speed_pct=6.0),
            "zmotion_operator_first_test_limit_exceeded",
        ),
    ],
)
def test_operator_motion_safety_rejections_happen_before_executor(
    parameters: dict,
    expected_state: str,
) -> None:
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    client = FakeOperatorClient()
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=_real_request("linear_move", parameters),
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["state"] == expected_state
    assert executor.calls == []
    assert client.disconnect_calls == 1


def test_operator_disallowed_io_returns_blocked_plan_without_executor() -> None:
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    client = FakeOperatorClient()
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=_real_request(
            "io",
            {
                "io_number": 9,
                "enabled": True,
                "allowed_io_channels": [1, 2],
            },
        ),
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["state"] == "zmotion_operator_plan_blocked"
    assert "io_channel_not_allowed" in result["data"]["blockers"]
    assert executor.calls == []


def test_operator_linear_path_reaches_sequence_runner_with_func108_plans() -> None:
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    client = FakeOperatorClient()
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=_real_request("linear_path", _linear_path_parameters()),
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["state"] == "real_motion_sequence_submitted"
    assert [call[0].function_code for call in executor.calls] == [108, 108]
    assert [call[0].parameter_writes[3].value for call in executor.calls] == [999.0, 998.0]
    assert all(call[1:] == (True, True) for call in executor.calls)


@pytest.mark.parametrize(
    ("command", "parameters", "function_code"),
    [
        ("system", {"action": "emergency_stop"}, 104),
        ("delay", {"seconds": 0.25}, 110),
        (
            "io",
            {
                "io_number": 3,
                "enabled": False,
                "allowed_io_channels": [2, 3, 4],
            },
            120,
        ),
    ],
)
def test_operator_supported_non_motion_commands_reach_executor(
    command: str,
    parameters: dict,
    function_code: int,
) -> None:
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    client = FakeOperatorClient()
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=_real_request(command, parameters),
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["ok"] is True
    assert executor.calls[0][0].function_code == function_code
    assert client.disconnect_calls == 1


def test_operator_disconnects_when_executor_returns_failure() -> None:
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    client = FakeOperatorClient()
    executor = FakeExecutor(
        ToolResult.failure(
            state="real_motion_echo_mismatch",
            message="echo mismatch",
        ).to_dict()
    )

    result = run_zmotion_operator_command(
        request=_real_request("delay", {"seconds": 0.25}),
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["state"] == "real_motion_echo_mismatch"
    assert client.disconnect_calls == 1
