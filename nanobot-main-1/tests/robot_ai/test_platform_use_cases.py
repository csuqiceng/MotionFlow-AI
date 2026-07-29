from __future__ import annotations

from robot_ai.models import RobotState, ToolResult
from robot_ai.platform import RobotPlatform
from robot_ai.tools.robot_tools import RobotToolFacade

from robot_platform.application import AuthenticatedPrincipal
from robot_platform.execution import ExecutionPermitStore, ExecutionScope


class _Backend:
    def get_state(self) -> RobotState:
        return RobotState(mode="idle")

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        return ToolResult.success(state="moved")

    def home(self) -> ToolResult:
        return ToolResult.success(state="home")

    def stop(self) -> ToolResult:
        return ToolResult.success(state="stopped")


def test_status_is_available_without_an_execution_adapter() -> None:
    platform = RobotPlatform(facade=RobotToolFacade(backend=_Backend()))

    result = platform.get_status()

    assert result["ok"] is True
    assert result["data"]["robot_state"]["mode"] == "idle"


def test_plan_motion_never_marks_request_as_real_execution() -> None:
    received = []

    def runner(*, request):
        received.append(request)
        return ToolResult.success(state="planned").to_dict()

    platform = RobotPlatform(operator_runner=runner)
    result = platform.plan_motion("linear_move", {"target_pose": {}})

    assert result["ok"] is True
    assert received[0].execute_real is False


def test_platform_io_policy_cannot_be_extended_by_request_payload() -> None:
    received = []

    def runner(*, request):
        received.append(request)
        return ToolResult.success(state="planned").to_dict()

    platform = RobotPlatform(
        operator_runner=runner, allowed_io_output_channels=(8, 3),
    )

    accepted = platform.plan_motion(
        "io",
        {
            "io_number": 3,
            "enabled": True,
            "allowed_io_channels": [3, 999],
        },
    )
    rejected = platform.plan_motion(
        "io",
        {
            "io_number": 999,
            "enabled": True,
            "allowed_io_channels": [999],
        },
    )

    assert accepted["ok"] is True
    assert received[0].parameters == {
        "io_number": 3,
        "enabled": True,
        "allowed_io_channels": [3, 8],
    }
    assert rejected["state"] == "io_channel_not_allowed"
    assert len(received) == 1


def test_confirmed_execution_refuses_missing_confirmation_before_runner() -> None:
    called = False

    def runner(*, request):
        nonlocal called
        called = True
        return ToolResult.success(state="executed").to_dict()

    result = RobotPlatform(operator_runner=runner).execute_confirmed_plan(
        "linear_move", {}, confirmation_code="", confirm_work_area_clear=True, confirm_estop_ready=True
    )

    assert result["state"] == "confirmation_required"
    assert called is False


def test_server_side_permit_is_forwarded_to_the_controller_gate() -> None:
    received = []

    def runner(*, request, permit_verifier):
        received.append(request)
        assert permit_verifier is store
        return ToolResult.success(state="executed").to_dict()

    payload = {"command": "linear_move", "parameters": {}}
    scope = ExecutionScope.for_payload(
        principal=AuthenticatedPrincipal("operator", "operator", "session", "test"),
        robot_id="robot", controller_id="controller", operation_type="linear_move",
        payload=payload, payload_schema_version="1", product_profile_version="1",
        capability_version="1", deployment_instance_id="deployment", core_version="1",
        plan_id="plan-1", plan_version="1",
    )
    store = ExecutionPermitStore()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="plan-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)

    result = RobotPlatform(operator_runner=runner).execute_confirmed_plan(
        "linear_move", {}, execution_permit_handle=permit.handle,
        execution_scope=scope, permit_verifier=store,
        execution_operation_type="linear_move", execution_payload=payload,
        execution_dispatch_id="plan-1:0",
        confirm_work_area_clear=True, confirm_estop_ready=True,
    )

    assert result["ok"] is True
    assert received[0].execution_permit_handle == permit.handle
    assert received[0].execution_scope == scope


def test_legacy_emergency_stop_confirmation_fails_closed() -> None:
    received = []

    def runner(*, request):
        received.append(request)
        return ToolResult.success(state="estopped").to_dict()

    result = RobotPlatform(operator_runner=runner).emergency_stop(
        confirmation_code="proof", confirm_work_area_clear=True, confirm_estop_ready=True
    )

    assert result["state"] == "confirmation_required"
    assert received == []
