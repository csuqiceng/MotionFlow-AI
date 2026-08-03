"""Standard JSON robot API backed only by public RobotPlatform use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from robot_platform import PendingPlanStore, RobotPlatform, SessionGateStore
from robot_platform.application import (
    IO_COMMANDS,
    MOTION_COMMANDS,
    AuthenticatedPrincipal,
    EmergencyStopApplicationService,
    RobotDryRunApplicationService,
    RobotDryRunResponse,
    RobotEmergencyStopCommand,
    RobotFlowExecutionApplicationService,
    RobotFlowExecutionResponse,
    RobotIOApplicationService,
    RobotIOExecutionCommand,
    RobotIOResponse,
    RobotMotionApplicationService,
    RobotMotionExecutionCommand,
    RobotMotionResponse,
)
from robot_platform.execution.permit import (
    ExecutionPermitState,
    ExecutionPermitStore,
    ExecutionScope,
    UnresolvedExecutionError,
)
from robot_server.execution_recovery import ExecutionRecoveryService


@dataclass
class RobotOperationService:
    """Own the HTTP-facing pending-plan lifecycle without a gateway dependency."""

    platform: RobotPlatform
    pending_plans: PendingPlanStore
    session_gates: SessionGateStore
    execution_permits: ExecutionPermitStore
    robot_id: str
    controller_id: str
    product_profile_version: str
    capability_version: str
    deployment_instance_id: str
    core_version: str
    emergency_stop_application: EmergencyStopApplicationService
    planning_application: RobotDryRunApplicationService
    motion_application: RobotMotionApplicationService
    io_application: RobotIOApplicationService
    flow_execution_application: RobotFlowExecutionApplicationService
    execution_recovery: ExecutionRecoveryService | None = None

    def unresolved_executions(
        self, *, principal: AuthenticatedPrincipal,
    ) -> tuple[int, dict[str, Any]]:
        if self.execution_recovery is None:
            return _error(503, "execution recovery is unavailable")
        return self.execution_recovery.list_unresolved(principal)

    def reconcile_execution(
        self, body: Any, *, principal: AuthenticatedPrincipal,
    ) -> tuple[int, dict[str, Any]]:
        if self.execution_recovery is None:
            return _error(503, "execution recovery is unavailable")
        return self.execution_recovery.reconcile(body, principal=principal)

    def plan(
        self, body: Any, *, principal: AuthenticatedPrincipal
    ) -> tuple[int, dict[str, Any]]:
        parsed = _command_body(body)
        if isinstance(parsed[0], int):
            return parsed
        command, parameters = parsed
        return _planning_result(self.planning_application.stage_command(
            principal, command, parameters,
        ))

    def confirm(
        self, plan_id: str, body: Any, *, principal: AuthenticatedPrincipal
    ) -> tuple[int, dict[str, Any]]:
        existing = self.pending_plans.get(plan_id)
        if existing is not None and existing.command == "flow_run":
            return _flow_result(self.flow_execution_application.confirm(
                principal, plan_id, body,
            ))
        parsed = _confirmation_body(body, principal)
        if isinstance(parsed[0], int):
            return parsed
        session_key, work_area_clear, estop_ready = parsed
        if not work_area_clear or not estop_ready:
            return _error(400, "both safety confirmations must be true")
        plan = self.pending_plans.get(plan_id)
        if plan is None:
            return _error(404, "pending plan not found or expired")
        if not self.session_gates.confirm(session_key, plan_id):
            return _error(409, "session has no matching pending plan")
        if not self.pending_plans.confirm(plan_id):
            return _error(409, "pending plan cannot be confirmed")
        try:
            permit = self.execution_permits.issue(
                self._execution_scope(plan, principal),
                operation_id=f"robot-operation:{plan_id}",
                idempotency_key=plan_id,
                requires_dispatch_claim=plan.command != "flow_run",
            )
        except UnresolvedExecutionError:
            return _execution_outcome_unknown_error()
        except ValueError as exc:
            return _error(409, str(exc))
        receipt = self.pending_plans.authorize(
            plan_id,
            permit_handle=permit.handle,
        )
        if receipt is None:
            return _error(409, "pending plan cannot be authorized")
        return 200, {"confirm_code": receipt}

    def execute(
        self, plan_id: str, body: Any, *, principal: AuthenticatedPrincipal
    ) -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            return _error(400, "request body must be a JSON object")
        confirm_code = body.get("confirm_code")
        if not isinstance(confirm_code, str) or not confirm_code:
            return _error(400, "confirm_code is required")
        plan = self.pending_plans.get(plan_id)
        if plan is None:
            return _error(404, "pending plan not found or expired")
        if plan.command == "flow_run":
            return _flow_result(self.flow_execution_application.execute(
                principal, plan_id, body,
            ))
        if plan.command in MOTION_COMMANDS:
            return _motion_result(self.motion_application.execute(
                RobotMotionExecutionCommand(
                    principal=principal,
                    plan_id=plan_id,
                    confirmation_receipt=confirm_code,
                )
            ))
        if plan.command in IO_COMMANDS:
            return _io_result(self.io_application.execute(
                RobotIOExecutionCommand(
                    principal=principal,
                    plan_id=plan_id,
                    confirmation_receipt=confirm_code,
                )
            ))
        permit_handle, early_result = self._begin_execution(
            plan, principal=principal, confirmation_receipt=confirm_code
        )
        if early_result is not None:
            return early_result
        assert permit_handle is not None
        scope = self._execution_scope(plan, principal)
        # Do not accept command/parameters from execute: only the immutable
        # dry-run plan may be executed.
        try:
            result = self.platform.execute_confirmed_plan(
                plan.command,
                plan.parameters,
                confirm_work_area_clear=True,
                confirm_estop_ready=True,
                execution_permit_handle=permit_handle,
                execution_scope=scope,
                permit_verifier=self.execution_permits,
                execution_operation_type=scope.operation_type,
                execution_payload={"command": plan.command, "parameters": plan.parameters},
                execution_dispatch_id=f"{plan_id}:0",
            )
        except Exception:
            self.execution_permits.mark_outcome_unknown(
                permit_handle, reason="platform_raised_after_execution_started"
            )
            raise
        commit_error = self._commit_result(
            permit_handle, result, unknown_reason="platform_returned_non_definite_failure"
        )
        if commit_error is not None:
            return commit_error
        return 200, result

    def emergency_stop(
        self, body: Any, *, principal: AuthenticatedPrincipal
    ) -> tuple[int, dict[str, Any]]:
        del body
        response = self.emergency_stop_application.execute(
            RobotEmergencyStopCommand(principal)
        )
        if response.ok and isinstance(response.payload, dict):
            return (200 if response.payload.get("ok") is True else 503), response.payload
        error = response.error
        return 503, {"error": {
            "code": getattr(error, "code", "emergency_stop_outcome_unknown"),
            "message": getattr(
                error, "message",
                "Emergency stop outcome is unknown; use the physical emergency stop.",
            ),
        }}

    def plan_flow(
        self, body: Any, *, principal: AuthenticatedPrincipal
    ) -> tuple[int, dict[str, Any]]:
        return _flow_result(self.flow_execution_application.plan(principal, body))

    def execute_flow(
        self, plan_id: str, body: Any, *, principal: AuthenticatedPrincipal
    ) -> tuple[int, dict[str, Any]]:
        # Compatibility fields remain mutable for embedded/test hosts; the
        # Application owns the check and receives the current facade values.
        self.flow_execution_application.product_profile_version = (
            self.product_profile_version
        )
        self.flow_execution_application.capability_version = self.capability_version
        self.flow_execution_application.core_version = self.core_version
        return _flow_result(self.flow_execution_application.execute(
            principal, plan_id, body,
        ))

    def run_flow(
        self, body: Any, *, principal: AuthenticatedPrincipal
    ) -> tuple[int, dict[str, Any]]:
        return _flow_result(self.flow_execution_application.preview(principal, body))

    def _execution_scope(
        self, plan: Any, principal: AuthenticatedPrincipal
    ) -> ExecutionScope:
        return ExecutionScope.for_payload(
            principal=principal,
            robot_id=self.robot_id,
            controller_id=self.controller_id,
            operation_type=plan.command,
            payload={"command": plan.command, "parameters": plan.parameters},
            payload_schema_version="1",
            product_profile_version=self.product_profile_version,
            capability_version=self.capability_version,
            deployment_instance_id=self.deployment_instance_id,
            core_version=self.core_version,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
        )

    def _begin_execution(
        self,
        plan: Any,
        *,
        principal: AuthenticatedPrincipal,
        confirmation_receipt: str,
    ) -> tuple[str | None, tuple[int, dict[str, Any]] | None]:
        if not self.session_gates.is_confirmed(
            _principal_session_key(principal), plan.plan_id
        ):
            return None, _error(409, "session has no matching confirmed plan")
        if not self.pending_plans.verify_confirmation(
            plan.plan_id, confirmation_receipt
        ):
            return None, _error(409, "confirmation receipt is invalid or expired")
        if not plan.permit_handle:
            return None, _error(409, "pending plan has no execution permit")
        definite = self.execution_permits.definite_result_for_idempotency_key(
            plan.plan_id
        )
        if definite is not None:
            return None, (200, definite)
        record = self.execution_permits.get(plan.permit_handle)
        if record is None:
            return None, _error(409, "execution permit is missing")
        if record.state is ExecutionPermitState.OUTCOME_UNKNOWN:
            return None, _execution_outcome_unknown_error()
        scope = self._execution_scope(plan, principal)
        if not self.execution_permits.reserve(plan.permit_handle, scope):
            return None, _error(409, "execution permit is not reservable")
        if not self.execution_permits.mark_executing(plan.permit_handle):
            return None, _error(409, "execution permit expired before dispatch")
        return plan.permit_handle, None

    def _commit_result(
        self,
        permit_handle: str,
        result: dict[str, Any],
        *,
        unknown_reason: str,
    ) -> tuple[int, dict[str, Any]] | None:
        if result.get("ok") is True:
            if self.execution_permits.complete(permit_handle, result):
                return None
            self.execution_permits.mark_outcome_unknown(
                permit_handle, reason="successful_result_could_not_be_committed"
            )
            return _error(500, "execution result could not be committed")
        if not self.execution_permits.mark_outcome_unknown(
            permit_handle, reason=unknown_reason
        ):
            return _error(500, "uncertain execution result could not be recorded")
        return None


def _command_body(
    body: Any,
) -> tuple[str, dict[str, Any]] | tuple[int, dict[str, Any]]:
    if not isinstance(body, dict):
        return _error(400, "request body must be a JSON object")
    command = body.get("command")
    parameters = body.get("parameters")
    if not isinstance(command, str) or not command:
        return _error(400, "command is required")
    if not isinstance(parameters, dict):
        return _error(400, "parameters must be an object")
    return command, parameters


def _confirmation_body(
    body: Any, principal: AuthenticatedPrincipal
) -> tuple[str, bool, bool] | tuple[int, dict[str, Any]]:
    if not isinstance(body, dict):
        return _error(400, "request body must be a JSON object")
    return (
        _principal_session_key(principal),
        bool(body.get("confirm_work_area_clear")),
        bool(body.get("confirm_estop_ready")),
    )


def _principal_session_key(principal: AuthenticatedPrincipal) -> str:
    return f"robot-server:{principal.session_id}"


def _execution_outcome_unknown_error() -> tuple[int, dict[str, Any]]:
    return _error(
        409,
        "A previous controller execution needs safety recovery before another command.",
        code="execution_outcome_unknown",
    )


def _error(
    status: int, message: str, *, code: str | int | None = None,
) -> tuple[int, dict[str, Any]]:
    return status, {"error": {"code": status if code is None else code, "message": message}}


def _planning_result(
    outcome: RobotDryRunResponse,
) -> tuple[int, dict[str, Any]]:
    if outcome.ok and isinstance(outcome.payload, dict):
        return (201 if outcome.staged else 200), outcome.payload
    error = getattr(outcome, "error", None)
    code = getattr(error, "code", "dry_run_unavailable")
    message = getattr(error, "message", "Robot dry-run is unavailable.")
    status = {
        "invalid_request": 400,
        "invalid_principal": 403,
        "not_found": 404,
        "conflict": 409,
        "planning_state_unavailable": 503,
        "dry_run_unavailable": 503,
    }.get(code, 503)
    return _error(status, message)


def _flow_result(
    response: RobotFlowExecutionResponse,
) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        return (201 if response.staged else 200), response.payload
    error = response.error
    code = getattr(error, "code", "flow_state_unavailable")
    message = getattr(error, "message", "Flow service is unavailable.")
    status = {
        "invalid_flow_request": 400,
        "flow_forbidden": 403,
        "invalid_principal": 403,
        "flow_plan_not_found": 404,
        "flow_not_found": 404,
        "flow_alias_not_found": 404,
        "flow_confirmation_required": 400,
        "flow_session_not_confirmed": 409,
        "flow_confirmation_invalid": 409,
        "flow_snapshot_invalid": 409,
        "flow_dependencies_changed": 409,
        "flow_permit_missing": 409,
        "flow_permit_scope_mismatch": 409,
        "flow_permit_not_reservable": 409,
        "flow_permit_expired": 409,
        "flow_outcome_unknown": 409,
        "staged_execution_required": 409,
        "flow_commit_failed": 500,
        "planning_state_unavailable": 503,
        "dry_run_unavailable": 503,
        "flow_state_unavailable": 503,
    }.get(code, 503)
    return status, {"error": {"code": code, "message": message}}


def _motion_result(response: RobotMotionResponse) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        if response.payload.get("ok") is False:
            return _execution_outcome_unknown_error()
        return 200, response.payload
    error = response.error
    code = getattr(error, "code", "motion_state_unavailable")
    message = getattr(error, "message", "Motion service is unavailable.")
    if code in {
        "motion_outcome_unknown", "motion_dispatch_outcome_unknown", "motion_commit_failed",
    }:
        return _execution_outcome_unknown_error()
    status = {
        "invalid_motion_request": 400,
        "motion_forbidden": 403,
        "motion_plan_not_found": 404,
        "unsupported_motion_plan": 409,
        "motion_session_not_confirmed": 409,
        "motion_confirmation_invalid": 409,
        "motion_permit_missing": 409,
        "motion_permit_scope_mismatch": 409,
        "motion_permit_not_reservable": 409,
        "motion_permit_expired": 409,
        "motion_state_unavailable": 503,
    }.get(code, 503)
    return status, {"error": {"code": code, "message": message}}


def _io_result(response: RobotIOResponse) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        if response.payload.get("ok") is False:
            return _execution_outcome_unknown_error()
        return 200, response.payload
    error = response.error
    code = getattr(error, "code", "io_state_unavailable")
    message = getattr(error, "message", "IO service is unavailable.")
    if code in {
        "io_outcome_unknown", "io_dispatch_outcome_unknown", "io_commit_failed",
    }:
        return _execution_outcome_unknown_error()
    status = {
        "invalid_io_request": 400,
        "io_forbidden": 403,
        "io_plan_not_found": 404,
        "unsupported_io_plan": 409,
        "io_plan_invalid": 409,
        "io_session_not_confirmed": 409,
        "io_confirmation_invalid": 409,
        "io_permit_missing": 409,
        "io_permit_scope_mismatch": 409,
        "io_permit_not_reservable": 409,
        "io_permit_expired": 409,
        "io_state_unavailable": 503,
    }.get(code, 503)
    return status, {"error": {"code": code, "message": message}}
