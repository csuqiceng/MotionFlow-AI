from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json

from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotAutomaticFlowApplicationService,
    RobotAutomaticFlowCommand,
    RobotFlowExecutionResponse,
)


def _principal(role: str = "operator") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("operator-1", role, "session-1", "webui-session")


@dataclass
class _FlowExecution:
    planned: list[dict]
    confirmed: list[tuple[str, dict]]
    executed: list[tuple[str, dict]]
    result: RobotFlowExecutionResponse | None = None

    def plan(self, principal: AuthenticatedPrincipal, body: dict) -> RobotFlowExecutionResponse:
        del principal
        self.planned.append(body)
        return RobotFlowExecutionResponse(payload={"plan_id": "plan-1"}, staged=True)

    def confirm(self, principal: AuthenticatedPrincipal, plan_id: str, body: dict) -> RobotFlowExecutionResponse:
        del principal
        self.confirmed.append((plan_id, body))
        return RobotFlowExecutionResponse(payload={"confirm_code": "receipt-1"})

    def execute(self, principal: AuthenticatedPrincipal, plan_id: str, body: dict) -> RobotFlowExecutionResponse:
        del principal
        self.executed.append((plan_id, body))
        return self.result or RobotFlowExecutionResponse(payload={
            "ok": True, "state": "flow_completed", "data": {"real_execution": True},
        })


def test_automatic_flow_runs_the_existing_plan_permit_execute_lifecycle() -> None:
    port = _FlowExecution([], [], [])
    response = RobotAutomaticFlowApplicationService(port).execute(
        RobotAutomaticFlowCommand(principal=_principal(), flow_name="pick"),
    )

    assert response.ok
    assert response.payload["data"]["real_execution"] is True
    assert port.planned == [{"flow_name": "pick", "alias": "", "inputs": {}}]
    assert port.confirmed == [("plan-1", {
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
        "approved_node_ids": [],
    })]
    assert port.executed == [("plan-1", {"confirm_code": "receipt-1"})]


def test_automatic_flow_never_executes_when_l1_stage_rejects() -> None:
    class Rejected(_FlowExecution):
        def plan(self, principal: AuthenticatedPrincipal, body: dict) -> RobotFlowExecutionResponse:
            del principal
            self.planned.append(body)
            return RobotFlowExecutionResponse(payload={
                "ok": False, "state": "safety_rejected", "message": "E-stop active.",
            })

    port = Rejected([], [], [])
    response = RobotAutomaticFlowApplicationService(port).execute(
        RobotAutomaticFlowCommand(principal=_principal(), flow_name="pick"),
    )

    assert response.ok
    assert response.payload["state"] == "safety_rejected"
    assert port.confirmed == []
    assert port.executed == []


def test_automatic_flow_preserves_a_frozen_snapshot_mismatch_before_permit_issue() -> None:
    class Changed(_FlowExecution):
        def plan(self, principal: AuthenticatedPrincipal, body: dict) -> RobotFlowExecutionResponse:
            del principal
            self.planned.append(body)
            return RobotFlowExecutionResponse(error=type("Error", (), {
                "code": "flow_snapshot_changed",
                "message": "Flow changed.",
            })())

    port = Changed([], [], [])
    response = RobotAutomaticFlowApplicationService(port).execute(
        RobotAutomaticFlowCommand(
            principal=_principal(), flow_name="pick", expected_snapshot_hash="frozen",
        ),
    )

    assert not response.ok
    assert response.error.code == "flow_snapshot_changed"
    assert port.planned[0]["expected_snapshot_hash"] == "frozen"
    assert port.confirmed == []
    assert port.executed == []


def test_automatic_flow_does_not_auto_approve_human_approval_nodes() -> None:
    class RequiresApproval(_FlowExecution):
        def confirm(self, principal: AuthenticatedPrincipal, plan_id: str, body: dict) -> RobotFlowExecutionResponse:
            del principal
            self.confirmed.append((plan_id, body))
            return RobotFlowExecutionResponse(error=type("Error", (), {
                "code": "flow_node_approval_required",
                "message": "Human approval is required.",
            })())

    port = RequiresApproval([], [], [])
    response = RobotAutomaticFlowApplicationService(port).execute(
        RobotAutomaticFlowCommand(principal=_principal(), flow_name="pick"),
    )

    assert not response.ok
    assert response.error.code == "flow_node_approval_required"
    assert port.executed == []


def test_automatic_flow_requires_an_authenticated_operator_before_planning() -> None:
    port = _FlowExecution([], [], [])
    response = RobotAutomaticFlowApplicationService(port).execute(
        RobotAutomaticFlowCommand(principal=_principal("viewer"), flow_name="pick"),
    )

    assert not response.ok
    assert response.error.code == "flow_forbidden"
    assert port.planned == []


def test_robot_flow_tool_auto_mode_uses_only_the_trusted_application(monkeypatch) -> None:
    monkeypatch.setattr(
        "ai_runtime.robot_tools.robot_flow.get_robot_execution_mode",
        lambda: "auto_after_safety_check",
    )
    captured = []

    class Automatic:
        def execute(self, command):
            captured.append(command)
            return type("Response", (), {
                "ok": True,
                "payload": {"ok": True, "state": "flow_completed", "data": {"real_execution": True}},
            })()

    result = json.loads(asyncio.run(RobotFlowTool(
        automatic_flow_application=Automatic(),
    ).execute(action="run", name="pick")))

    assert result["ok"] is True
    assert result["data"]["real_execution"] is True
    assert len(captured) == 1
    assert captured[0].flow_name == "pick"
