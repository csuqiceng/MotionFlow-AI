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
        allowed_io_output_channels=(2, 3, 4),
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


def _run_real(command: str, parameters: dict, **kwargs):
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    from robot_platform.application import AuthenticatedPrincipal
    from robot_platform.execution import ExecutionPermitStore, ExecutionScope

    payload = {"command": command, "parameters": parameters}
    scope = ExecutionScope.for_payload(
        principal=AuthenticatedPrincipal("operator", "operator", "session", "test"),
        robot_id="robot", controller_id="controller", operation_type=command,
        payload=payload, payload_schema_version="1", product_profile_version="1",
        capability_version="1", deployment_instance_id="deployment", core_version="1",
        plan_id=f"plan-{id(parameters)}", plan_version="1",
    )
    store = ExecutionPermitStore()
    permit = store.issue(scope, operation_id="operation", idempotency_key=scope.plan_id)
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    request = ZMotionOperatorRequest(
        command=command,
        parameters=parameters,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        execution_permit_handle=permit.handle,
        execution_scope=scope,
        execution_dispatch_id=f"{scope.plan_id}:0",
    )
    return run_zmotion_operator_command(
        request=request, permit_verifier=store, **kwargs
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


def test_normal_execution_permit_never_authorizes_emergency_stop() -> None:
    from robot_ai.zmotion_operator_control import ZMotionOperatorRequest

    from robot_platform.backends.zmotion_adapter import _is_confirmed
    from robot_platform.models import RobotState

    class Permit:
        def claim_dispatch(self, *args, **kwargs):
            raise AssertionError("normal permit must not be consulted for emergency stop")

    request = ZMotionOperatorRequest(
        command="system",
        parameters={"action": "emergency_stop"},
        execution_permit_handle="normal-permit",
        execution_scope=object(),
        execution_dispatch_id="dispatch",
    )

    assert _is_confirmed(
        request, RobotState(), permit_verifier=Permit(),
        emergency_stop_verifier=None,
    ) is False


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
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    fields = {
        "execute_real": True,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
        "confirmation_code": "legacy-static-credential",
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

    result = _run_real(
        "linear_move", _linear_parameters(),
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
            _linear_parameters(speed_pct=101.0),
            "zmotion_operator_safety_blocked",
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

    result = _run_real(
        "linear_move", parameters,
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

    result = _run_real(
        "io",
        {
                "io_number": 9,
                "enabled": True,
                "allowed_io_channels": [1, 2],
            },
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["state"] == "io_channel_not_allowed"
    assert executor.calls == []


def test_operator_linear_path_reaches_sequence_runner_with_func108_plans() -> None:
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    client = FakeOperatorClient()
    executor = FakeExecutor()

    result = _run_real(
        "linear_path", _linear_path_parameters(),
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
        ("system", {"action": "pause"}, 104),
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

    result = _run_real(
        command, parameters,
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

    result = _run_real(
        "delay", {"seconds": 0.25},
        config=_config(),
        client_factory=lambda _config: client,
        executor_factory=lambda _client: executor,
    )

    assert result["state"] == "real_motion_echo_mismatch"
    assert client.disconnect_calls == 1


# --- operator shared-client mode (ROBOT_AI_SHARED_CLIENT=1) ------------------
# The gateway unifies status + motion onto one ZAux connection via the shared
# singleton client. These cover the operator (motion) side of that: it must draw
# from shared.get() without connecting/disconnecting its own client, reset the
# shared connection only on SDK errors, and configure the shared client once.


def test_operator_shared_mode_uses_shared_client_without_connect_disconnect(
    monkeypatch,
) -> None:
    """In shared mode the operator draws its client from shared.get() and must
    NOT call connect()/disconnect() on it — the shared connection is owned by
    the singleton, not the operator."""
    monkeypatch.setenv("ROBOT_AI_SHARED_CLIENT", "1")
    from robot_ai.backends import zmotion_shared_client as shared
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    client = FakeOperatorClient()
    shared.set_override(client)
    try:
        result = run_zmotion_operator_command(
            request=ZMotionOperatorRequest(
                command="linear_move",
                parameters=_linear_parameters(),
            ),
            config=_config(),
            executor_factory=lambda _c: FakeExecutor(),
            # no client_factory → shared mode (client_factory is None + env set)
        )

        assert result["ok"] is True
        assert result["state"] == "zmotion_operator_dry_run"
        assert client.connect_calls == 0, "shared client must not be connected by the operator"
        assert client.disconnect_calls == 0, "shared client must not be disconnected by the operator"
    finally:
        shared.set_override(None)


def test_operator_shared_mode_resets_shared_client_on_sdk_error(monkeypatch) -> None:
    """A ZMotionSdkError during the operator's read is a (likely) dead connection
    → shared.reset() must fire so the next consumer reconnects."""
    monkeypatch.setenv("ROBOT_AI_SHARED_CLIENT", "1")
    from robot_ai.backends import zmotion_shared_client as shared
    from robot_ai.backends.zmotion_sdk import ZMotionSdkError
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    class DeadClient(FakeOperatorClient):
        def read_modbus_float(self, request: ModbusReadRequest) -> list[float]:
            raise ZMotionSdkError("connect(10.168.3.21) failed with code 3402")

    shared.set_override(DeadClient())
    resets: list[int] = []
    monkeypatch.setattr(shared, "reset", lambda: resets.append(1))
    try:
        result = run_zmotion_operator_command(
            request=ZMotionOperatorRequest(
                command="linear_move",
                parameters=_linear_parameters(),
            ),
            config=_config(),
        )

        assert result["ok"] is False
        assert len(resets) == 1, "ZMotionSdkError must trigger shared.reset()"
    finally:
        shared.set_override(None)


def test_operator_shared_mode_skips_reset_on_non_sdk_error(monkeypatch) -> None:
    """A non-SDK error (planning bug, executor raising) leaves the connection
    healthy → shared.reset() must NOT fire (avoids a spurious status blip)."""
    monkeypatch.setenv("ROBOT_AI_SHARED_CLIENT", "1")
    from robot_ai.backends import zmotion_shared_client as shared
    from robot_ai.zmotion_operator_control import run_zmotion_operator_command

    shared.set_override(FakeOperatorClient())
    resets: list[int] = []
    monkeypatch.setattr(shared, "reset", lambda: resets.append(1))

    class RaisingExecutor:
        def execute(self, plan, *, allow_real_motion_writes=False, confirmed_real_motion=False):
            raise RuntimeError("planning bug: bad segment")

    try:
        result = _run_real(
            "linear_move", _linear_parameters(),
            config=_config(),
            executor_factory=lambda _c: RaisingExecutor(),
        )

        assert result["ok"] is False
        assert "planning bug" in result["message"]
        assert len(resets) == 0, "non-SDK error must NOT reset the shared connection"
    finally:
        shared.set_override(None)


def test_operator_shared_mode_configures_shared_client_once(monkeypatch) -> None:
    """shared.configure() should run at most once across commands — the status
    backend already configured it at gateway startup, so a second motion command
    must skip reconfigure (is_configured gate)."""
    monkeypatch.setenv("ROBOT_AI_SHARED_CLIENT", "1")
    from robot_ai.backends import zmotion_shared_client as shared
    from robot_ai.zmotion_operator_control import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    shared.set_override(FakeOperatorClient())
    configures: list[int] = []
    real_configure = shared.configure

    def spy_configure(host, sdk_config):
        configures.append(1)
        real_configure(host, sdk_config)

    monkeypatch.setattr(shared, "configure", spy_configure)
    try:
        for _ in range(2):
            run_zmotion_operator_command(
                request=ZMotionOperatorRequest(
                    command="linear_move",
                    parameters=_linear_parameters(),
                ),
                config=_config(),
                executor_factory=lambda _c: FakeExecutor(),
            )

        assert len(configures) == 1, "shared.configure() must run once, not per command"
    finally:
        shared.set_override(None)
