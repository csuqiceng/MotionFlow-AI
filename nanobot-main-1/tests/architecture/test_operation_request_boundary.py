"""Vendor-neutral operation requests at the platform application boundary."""

from __future__ import annotations

from robot_platform.application.operations import RobotOperationRequest
from robot_platform.models import ToolResult
from robot_platform.platform import RobotPlatform


def test_platform_passes_a_vendor_neutral_operation_request_to_its_runner() -> None:
    received: list[RobotOperationRequest] = []

    def runner(*, request: RobotOperationRequest) -> dict:
        received.append(request)
        return ToolResult.success(state="planned").to_dict()

    result = RobotPlatform(operator_runner=runner).plan_motion(
        "linear_move", {"target_pose": {"x": 1.0}}
    )

    assert result["ok"] is True
    assert received == [
        RobotOperationRequest(
            command="linear_move",
            parameters={"target_pose": {"x": 1.0}},
            execute_real=False,
        )
    ]
