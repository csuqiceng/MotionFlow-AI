from __future__ import annotations

from pathlib import Path

import pytest

from robot_ai.backends.factory import RobotBackendConfig
from robot_ai.backends.zmotion_backend import ModbusReadRequest
from robot_ai.backends.zmotion_sdk import ModbusWriteRequest
from robot_ai.models import ToolResult
from robot_ai.safety import SafetyLimits, SafetyServices


SAFE_STATUS = 268435584  # bit 28 (READY) set -> idle (matches the real controller)
ESTOP_STATUS = 1 << 25   # bit 25 (ESTOP) set -> stopped + emergency_stop alarm


class FakeClient:
    def __init__(self, status: int = SAFE_STATUS) -> None:
        self.connected = False
        self.status = status
        self.float_writes: list[ModbusWriteRequest] = []

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]:
        if request.start_vr == 1612:
            return [900.0, 0.0, 1000.0, 0.0, 0.0, 0.0]
        if request.start_vr == 56:
            return [270.0]
        return [0.0] * request.count

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]:
        if request.start_vr == 34:
            return [self.status]
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
    def __init__(self) -> None:
        self.calls: list[object] = []

    def execute(
        self,
        plan,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict:
        self.calls.append(plan)
        return ToolResult.success(state="real_motion_command_completed").to_dict()


def _config() -> RobotBackendConfig:
    return RobotBackendConfig(
        mode="zmotion_readonly",
        controller_host="10.168.3.21",
        zmotion_wrapper_path=str(Path("vendor/zauxdllPython.py")),
        zmotion_dll_dir=str(Path("vendor/dll")),
    )


def _linear_parameters(**overrides) -> dict:
    values = {
        "target_pose": {"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
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


def test_estop_state_blocks_dry_run_before_any_write() -> None:
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    client = FakeClient(status=ESTOP_STATUS)
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=ZMotionOperatorRequest(command="linear_move", parameters=_linear_parameters()),
        config=_config(),
        client_factory=lambda _c: client,
        executor_factory=lambda _c: executor,
    )

    assert result["ok"] is False
    assert result["state"] == "zmotion_operator_safety_blocked"
    assert result["errors"][0]["code"] == "safety_precheck_failed"
    # The gate fired before the planner/executor and before any Modbus write.
    assert executor.calls == []
    assert client.float_writes == []


def test_estop_state_blocks_real_execution_before_executor() -> None:
    from robot_platform.application import AuthenticatedPrincipal
    from robot_platform.execution import ExecutionPermitStore, ExecutionScope
    from robot_ai.zmotion_operator_control import ZMotionOperatorRequest, run_zmotion_operator_command

    client = FakeClient(status=ESTOP_STATUS)
    executor = FakeExecutor()

    parameters = _linear_parameters()
    payload = {"command": "linear_move", "parameters": parameters}
    scope = ExecutionScope.for_payload(
        principal=AuthenticatedPrincipal("operator", "operator", "session", "test"),
        robot_id="robot", controller_id="controller", operation_type="linear_move",
        payload=payload, payload_schema_version="1", product_profile_version="1",
        capability_version="1", deployment_instance_id="deployment", core_version="1",
        plan_id="plan-estop", plan_version="1",
    )
    store = ExecutionPermitStore()
    permit = store.issue(scope, operation_id="operation", idempotency_key="plan-estop")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    result = run_zmotion_operator_command(
        request=ZMotionOperatorRequest(
            command="linear_move",
            parameters=parameters,
            execute_real=True,
            confirm_work_area_clear=True,
            confirm_estop_ready=True,
            execution_permit_handle=permit.handle,
            execution_scope=scope,
            execution_dispatch_id="plan-estop:0",
        ),
        config=_config(),
        client_factory=lambda _c: client,
        executor_factory=lambda _c: executor,
        permit_verifier=store,
    )

    assert result["state"] == "zmotion_operator_safety_blocked"
    assert executor.calls == []


def test_injected_tight_limits_block_target_before_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from robot_ai import zmotion_operator_control as module
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    tight = SafetyLimits(x=(899.0, 901.0))  # narrow X soft limit; rest default
    monkeypatch.setattr(module, "_safety_services_factory", lambda: SafetyServices.from_limits(tight))

    client = FakeClient(status=SAFE_STATUS)
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=ZMotionOperatorRequest(
            command="linear_move",
            parameters=_linear_parameters(
                target_pose={"x": 902.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}
            ),
        ),
        config=_config(),
        client_factory=lambda _c: client,
        executor_factory=lambda _c: executor,
    )

    assert result["state"] == "zmotion_operator_safety_blocked"
    failed = {
        item["id"]
        for item in result["data"]["items"]
        if item["status"] == "fail"
    }
    assert "target_x_range" in failed
    assert executor.calls == []
    assert client.float_writes == []


def test_clean_state_dry_run_passes_safety_gate() -> None:
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    client = FakeClient(status=SAFE_STATUS)
    executor = FakeExecutor()

    result = run_zmotion_operator_command(
        request=ZMotionOperatorRequest(command="linear_move", parameters=_linear_parameters()),
        config=_config(),
        client_factory=lambda _c: client,
        executor_factory=lambda _c: executor,
    )

    assert result["ok"] is True
    assert result["state"] == "zmotion_operator_dry_run"
    assert executor.calls == []
