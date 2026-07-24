from __future__ import annotations

from robot_ai.models import RobotState, ToolResult
from robot_ai.platform import RobotPlatform
from robot_ai.tools.robot_tools import RobotToolFacade


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


def test_pending_plan_confirmation_is_forwarded_to_the_controller_gate() -> None:
    received = []

    def runner(*, request):
        received.append(request)
        return ToolResult.success(state="executed").to_dict()

    result = RobotPlatform(operator_runner=runner).execute_confirmed_plan(
        "linear_move", {}, pending_plan_id="plan-1", confirm_code="RC-proof",
        confirm_work_area_clear=True, confirm_estop_ready=True,
    )

    assert result["ok"] is True
    assert received[0].pending_plan_id == "plan-1"
    assert received[0].confirm_code == "RC-proof"


def test_emergency_stop_uses_confirmed_execution_boundary() -> None:
    received = []

    def runner(*, request):
        received.append(request)
        return ToolResult.success(state="estopped").to_dict()

    result = RobotPlatform(operator_runner=runner).emergency_stop(
        confirmation_code="proof", confirm_work_area_clear=True, confirm_estop_ready=True
    )

    assert result["ok"] is True
    assert received[0].command == "system"
    assert received[0].parameters == {"action": "emergency_stop"}
    assert received[0].execute_real is True
