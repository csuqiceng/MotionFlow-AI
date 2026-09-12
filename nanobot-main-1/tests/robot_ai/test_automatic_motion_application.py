from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from ai_runtime.robot_tools.robot_arm import RobotArmTool
from ai_runtime.robot_tools.loader import LegacyRobotToolAdapter
from ai_runtime.tool_catalog import PRODUCT_TOOL_MANIFESTS_BY_ID
from ai_runtime.tool_contracts import ToolContext, ToolInvocation
from ai_runtime.tool_operation_store import InMemoryToolOperationStore
from ai_runtime.tool_runtime import ProductToolRuntime, ToolAuditEvent
from ai_runtime.identity import issue_verified_principal
from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotAutomaticMotionApplicationService,
    RobotAutomaticMotionCommand,
    RobotAutomaticMotionResponse,
    RobotDryRunApplicationService,
    RobotMotionApplicationService,
)
from robot_platform.execution import ExecutionPermitStore, ExecutionScope, PendingPlanStore, SessionGateStore


@dataclass
class _Audit:
    events: list[ToolAuditEvent] = field(default_factory=list)

    def append(self, event: ToolAuditEvent) -> None:
        self.events.append(event)


class _Platform:
    allowed_io_output_channels = ()

    def __init__(self) -> None:
        self.planned: list[tuple[str, dict]] = []
        self.executed: list[tuple[str, dict, dict]] = []

    def plan_motion(self, command: str, parameters: dict) -> dict:
        self.planned.append((command, parameters))
        return {
            "ok": True,
            "state": "zmotion_operator_dry_run",
            "message": "L1 safety passed.",
            "data": {"real_execution": False},
            "errors": [],
        }

    def execute_confirmed_plan(self, command: str, parameters: dict, **kwargs) -> dict:
        self.executed.append((command, parameters, kwargs))
        assert kwargs["permit_verifier"].claim_dispatch(
            kwargs["execution_permit_handle"],
            kwargs["execution_scope"],
            dispatch_id=kwargs["execution_dispatch_id"],
            operation_type=kwargs["execution_operation_type"],
            payload=kwargs["execution_payload"],
        )
        return {
            "ok": True,
            "state": "executed",
            "message": "Robot motion completed.",
            "data": {"real_execution": True},
            "errors": [],
        }


class _UnsafePlatform(_Platform):
    def plan_motion(self, command: str, parameters: dict) -> dict:
        self.planned.append((command, parameters))
        return {
            "ok": False,
            "state": "safety_rejected",
            "message": "Emergency stop is active.",
            "data": {},
            "errors": [{"code": "estop_active"}],
        }


class _UnknownOutcomePlatform(_Platform):
    def execute_confirmed_plan(self, command: str, parameters: dict, **kwargs) -> dict:
        self.executed.append((command, parameters, kwargs))
        assert kwargs["permit_verifier"].claim_dispatch(
            kwargs["execution_permit_handle"], kwargs["execution_scope"],
            dispatch_id=kwargs["execution_dispatch_id"],
            operation_type=kwargs["execution_operation_type"],
            payload=kwargs["execution_payload"],
        )
        return {
            "ok": False, "state": "controller_completion_timeout",
            "message": "controller did not answer", "errors": [{"code": "controller_completion_timeout"}],
            "data": {"completion_attempts": 3},
        }


class _RaisingOutcomePlatform(_Platform):
    def execute_confirmed_plan(self, command: str, parameters: dict, **kwargs) -> dict:
        self.executed.append((command, parameters, kwargs))
        assert kwargs["permit_verifier"].claim_dispatch(
            kwargs["execution_permit_handle"], kwargs["execution_scope"],
            dispatch_id=kwargs["execution_dispatch_id"],
            operation_type=kwargs["execution_operation_type"],
            payload=kwargs["execution_payload"],
        )
        raise TimeoutError("controller connection lost")

def _principal(role: str = "operator") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        actor_id="operator-1", role=role, session_id="session-1",
        auth_source="webui-session",
    )


def _service(platform: _Platform) -> RobotAutomaticMotionApplicationService:
    pending = PendingPlanStore()
    sessions = SessionGateStore()
    permits = ExecutionPermitStore()
    planning = RobotDryRunApplicationService(
        platform, pending, sessions,
        product_profile_version="profile-1",
        capability_version="capability-1",
        core_version="core-1",
    )
    motion = RobotMotionApplicationService(
        platform, pending, sessions, permits,
        robot_id="robot-1",
        controller_id="controller-1",
        product_profile_version="profile-1",
        capability_version="capability-1",
        deployment_instance_id="deployment-1",
        core_version="core-1",
    )
    return RobotAutomaticMotionApplicationService(
        planning, pending, sessions, permits, motion,
        robot_id="robot-1",
        controller_id="controller-1",
        product_profile_version="profile-1",
        capability_version="capability-1",
        deployment_instance_id="deployment-1",
        core_version="core-1",
    )


def test_trusted_auto_motion_runs_safety_plan_before_real_dispatch() -> None:
    platform = _Platform()
    response = _service(platform).execute(RobotAutomaticMotionCommand(
        principal=_principal(),
        command="linear_move",
        parameters={
            "target_pose": {
                "x": 1000.0, "y": 0.0, "z": 800.0,
                "rx": 0.0, "ry": 90.0, "rz": 0.0,
            },
            "speed_pct": 5.0,
            "acceleration_pct": 5.0,
            "deceleration_pct": 5.0,
            "r_min": 200.0,
            "r_max": 1800.0,
            "z_min": 0.0,
            "z_max": 2500.0,
        },
    ))

    assert response.ok is True
    assert response.payload["data"]["real_execution"] is True
    assert len(platform.planned) == 1
    assert len(platform.executed) == 1
    _, _, execution = platform.executed[0]
    assert execution["confirm_work_area_clear"] is True
    assert execution["confirm_estop_ready"] is True
    assert execution["execution_permit_handle"]
    assert execution["permit_verifier"] is not None


def test_auto_motion_rejects_untrusted_principal_before_planning() -> None:
    platform = _Platform()
    response = _service(platform).execute(RobotAutomaticMotionCommand(
        principal=_principal("untrusted"), command="linear_move", parameters={},
    ))

    assert response.ok is False
    assert response.error.code == "motion_forbidden"
    assert platform.planned == []
    assert platform.executed == []


def test_auto_motion_preserves_l1_rejection_and_never_dispatches() -> None:
    platform = _UnsafePlatform()
    response = _service(platform).execute(RobotAutomaticMotionCommand(
        principal=_principal(), command="linear_move", parameters={},
    ))

    assert response.ok is True
    assert response.payload["ok"] is False
    assert response.payload["state"] == "safety_rejected"
    assert platform.executed == []


def test_auto_motion_returns_stable_recovery_code_for_an_unresolved_controller() -> None:
    platform = _Platform()
    service = _service(platform)
    scope = ExecutionScope.for_payload(
        principal=_principal(), robot_id="robot-1", controller_id="controller-1",
        operation_type="linear_move", payload={"old": True}, payload_schema_version="1",
        product_profile_version="profile-1", capability_version="capability-1",
        deployment_instance_id="deployment-1", core_version="core-1",
        plan_id="old-plan", plan_version="1",
    )
    old = service._permits.issue(scope, operation_id="robot-operation:old", idempotency_key="old-plan")
    assert service._permits.reserve(old.handle, scope)
    assert service._permits.mark_executing(old.handle)
    assert service._permits.mark_outcome_unknown(old.handle, reason="controller_timeout")

    response = service.execute(RobotAutomaticMotionCommand(
        principal=_principal(), command="linear_move", parameters={},
    ))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "execution_outcome_unknown"
    assert platform.executed == []


def test_auto_motion_converts_a_new_non_definite_result_to_recovery_code() -> None:
    platform = _UnknownOutcomePlatform()

    response = _service(platform).execute(RobotAutomaticMotionCommand(
        principal=_principal(), command="linear_move", parameters={
            "target_pose": {"x": 1000.0, "y": 0.0, "z": 800.0, "rx": 0.0, "ry": 90.0, "rz": 0.0},
        },
    ))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "execution_outcome_unknown"
    assert len(platform.executed) == 1


def test_auto_motion_converts_a_dispatch_exception_to_recovery_code() -> None:
    response = _service(_RaisingOutcomePlatform()).execute(RobotAutomaticMotionCommand(
        principal=_principal(), command="linear_move", parameters={},
    ))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "execution_outcome_unknown"


def test_robot_arm_auto_mode_uses_only_injected_trusted_application(monkeypatch) -> None:
    monkeypatch.setattr(
        "ai_runtime.robot_tools.robot_arm.get_robot_execution_mode",
        lambda: "auto_after_safety_check",
    )
    captured = []

    class AutomaticApplication:
        def execute(self, command):
            captured.append(command)
            return RobotAutomaticMotionResponse(payload={
                "ok": True, "state": "executed", "message": "done",
                "data": {"real_execution": True}, "errors": [],
            })

    result = json.loads(asyncio.run(RobotArmTool(
        automatic_motion_application=AutomaticApplication(),
    ).execute(
        action="linear_move",
        target_pose={
            "x": 1000.0, "y": 0.0, "z": 800.0,
            "rx": 0.0, "ry": 90.0, "rz": 0.0,
        },
    )))

    assert result["ok"] is True
    assert result["data"]["real_execution"] is True
    assert len(captured) == 1
    assert captured[0].parameters["speed_pct"] == 50.0
    assert captured[0].parameters["acceleration_pct"] == 50.0
    assert captured[0].parameters["deceleration_pct"] == 50.0


@pytest.mark.asyncio
async def test_governed_auto_motion_is_audited_and_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(
        "ai_runtime.robot_tools.robot_arm.get_robot_execution_mode",
        lambda: "auto_after_safety_check",
    )
    platform = _Platform()
    audit = _Audit()
    operation_store = InMemoryToolOperationStore(durable=True)
    manifest = PRODUCT_TOOL_MANIFESTS_BY_ID["robot_arm"]
    runtime = ProductToolRuntime(
        capabilities={"supports_state_read": True},
        enabled_tool_ids=["robot_arm"],
        audit=audit,
        target_device_id="controller-1",
        operation_store=operation_store,
    )
    runtime.register(LegacyRobotToolAdapter(RobotArmTool(
        automatic_motion_application=_service(platform),
    ), manifest=manifest), manifest)
    principal = issue_verified_principal(
        actor_id="operator-1", role="operator", session_id="session-1",
        auth_source="webui-session",
    )
    context = ToolContext(principal=principal, session_key="session-1")
    invocation = ToolInvocation(
        "robot_arm",
        {
            "action": "linear_move",
            "target_pose": {
                "x": 1000.0, "y": 0.0, "z": 800.0,
                "rx": 0.0, "ry": 90.0, "rz": 0.0,
            },
        },
        idempotency_key="request-1",
    )

    first = await runtime.execute(context, invocation)
    replay = await runtime.execute(context, invocation)

    assert first.ok is True
    assert replay.to_contract_dict() == first.to_contract_dict()
    assert len(platform.planned) == 1
    assert len(platform.executed) == 1
    record = operation_store.get("robot_arm", "request-1")
    assert record is not None and record.state == "completed"
    assert any(event.event == "tool_started" for event in audit.events)
    assert any(event.event == "tool_completed" for event in audit.events)
