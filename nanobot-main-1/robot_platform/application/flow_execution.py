"""Immutable staged Flow planning, authorization, and execution."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Protocol

from .dry_run import RobotDryRunApplicationPort, RobotDryRunResponse
from .flow import RobotFlowApplicationPort, RobotFlowQuery
from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotFlowExecutionError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotFlowExecutionResponse:
    payload: dict[str, Any] | None = None
    error: RobotFlowExecutionError | None = None
    staged: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotFlowExecutionResponse requires payload or error")
        if self.error is not None and self.staged:
            raise ValueError("Failed Flow response cannot be staged")
        if self.payload is not None and not isinstance(self.payload, dict):
            raise TypeError("Flow execution payload must be a dict")

    @property
    def ok(self) -> bool:
        return self.error is None


class FlowPendingPlanPort(Protocol):
    def get(self, plan_id: str) -> Any: ...
    def confirm(self, plan_id: str) -> bool: ...
    def authorize(
        self,
        plan_id: str,
        *,
        permit_handle: str,
        child_permit_handles: tuple[str, ...] = (),
        node_approval_receipts: dict[str, str] | None = None,
    ) -> str | None: ...
    def verify_confirmation(self, plan_id: str, receipt: str) -> bool: ...


class FlowSessionGatePort(Protocol):
    def confirm(self, session_key: str, plan_id: str) -> bool: ...
    def is_confirmed(self, session_key: str, plan_id: str) -> bool: ...


class FlowPermitStorePort(Protocol):
    def issue(self, scope: Any, **kwargs: Any) -> Any: ...
    def reserve(self, handle: str, scope: Any) -> bool: ...
    def mark_executing(self, handle: str) -> bool: ...
    def complete(self, handle: str, result: dict[str, Any]) -> bool: ...
    def skip_unstarted(self, handle: str, *, reason: str) -> bool: ...
    def mark_outcome_unknown(self, handle: str, *, reason: str) -> bool: ...
    def get(self, handle: str) -> Any: ...
    def definite_result_for_exact_execution(
        self, handle: str, idempotency_key: str, expected_scope: Any,
    ) -> dict[str, Any] | None: ...


class FlowExecutionPlatformPort(Protocol):
    def run_flow_entry(self, flow: Any, **kwargs: Any) -> dict[str, Any]: ...


class FlowEventSinkPort(Protocol):
    def append(self, event: Any) -> None: ...


class RobotFlowExecutionApplicationPort(Protocol):
    def plan(
        self, principal: AuthenticatedPrincipal, body: Any,
    ) -> RobotFlowExecutionResponse: ...
    def plan_entry(
        self, principal: AuthenticatedPrincipal, entry: Any, *,
        selection_name: str, alias: str | None = None,
        execution_inputs: dict[str, Any] | None = None,
    ) -> RobotFlowExecutionResponse: ...
    def confirm(
        self, principal: AuthenticatedPrincipal, plan_id: str, body: Any,
    ) -> RobotFlowExecutionResponse: ...
    def execute(
        self, principal: AuthenticatedPrincipal, plan_id: str, body: Any,
    ) -> RobotFlowExecutionResponse: ...
    def preview(
        self, principal: AuthenticatedPrincipal, body: Any,
    ) -> RobotFlowExecutionResponse: ...


def _fail_closed(method: Callable[..., RobotFlowExecutionResponse]):
    @wraps(method)
    def wrapped(*args: Any, **kwargs: Any) -> RobotFlowExecutionResponse:
        try:
            return method(*args, **kwargs)
        except Exception:
            return _failure(
                "flow_state_unavailable", "Flow state is unavailable.",
            )

    return wrapped


class RobotFlowExecutionApplicationService:
    def __init__(
        self,
        platform: FlowExecutionPlatformPort,
        pending_plans: FlowPendingPlanPort,
        session_gates: FlowSessionGatePort,
        permits: FlowPermitStorePort,
        planning: RobotDryRunApplicationPort,
        flows: RobotFlowApplicationPort,
        *,
        robot_id: str,
        controller_id: str,
        product_profile_version: str,
        capability_version: str,
        deployment_instance_id: str,
        core_version: str,
        event_sink: FlowEventSinkPort | None = None,
        approval_store: Any | None = None,
    ) -> None:
        self._platform = platform
        self._pending_plans = pending_plans
        self._session_gates = session_gates
        self._permits = permits
        self._planning = planning
        self._flows = flows
        self.robot_id = robot_id
        self.controller_id = controller_id
        self.product_profile_version = product_profile_version
        self.capability_version = capability_version
        self.deployment_instance_id = deployment_instance_id
        self.core_version = core_version
        self._event_sink = event_sink
        self._approval_store = approval_store

    @_fail_closed
    def plan(
        self, principal: AuthenticatedPrincipal, body: Any,
    ) -> RobotFlowExecutionResponse:
        forbidden = _authorize(principal)
        if forbidden is not None:
            return forbidden
        if not isinstance(body, dict):
            return _failure("invalid_flow_request", "Request body must be an object.")
        name = body.get("flow_name", body.get("name"))
        alias = body.get("alias")
        if not isinstance(name, str) or not name.strip():
            return _failure("invalid_flow_request", "flow_name is required.")
        if alias is not None and not isinstance(alias, str):
            return _failure("invalid_flow_request", "alias must be a string.")
        execution_inputs = body.get("inputs", {})
        if not isinstance(execution_inputs, dict):
            return _failure("invalid_flow_request", "inputs must be an object.")
        expected_snapshot_hash = body.get("expected_snapshot_hash", "")
        if not isinstance(expected_snapshot_hash, str):
            return _failure(
                "invalid_flow_request", "expected_snapshot_hash must be a string.",
            )
        selected_alias = (
            alias.strip() if isinstance(alias, str) and alias.strip() else ""
        )
        resolved = self._flows.query(RobotFlowQuery(
            principal, "get", name.strip(), selected_alias,
            expected_snapshot_hash=expected_snapshot_hash,
        ))
        if not resolved.ok or not isinstance(resolved.payload, dict):
            error = resolved.error
            return _failure(
                getattr(error, "code", "flow_not_found"),
                getattr(error, "message", "Flow was not found."),
            )
        public_flow = resolved.payload.get("flow")
        if not isinstance(public_flow, dict):
            return _failure("flow_state_unavailable", "Flow state is unavailable.")
        from robot_platform.flow.models import FlowEntry

        try:
            entry = FlowEntry.from_dict(public_flow)
        except (TypeError, ValueError):
            return _failure("flow_snapshot_invalid", "Flow snapshot is invalid.")
        return self.plan_entry(
            principal, entry, selection_name=name.strip(),
            alias=selected_alias or None, execution_inputs=execution_inputs,
        )

    @_fail_closed
    def plan_entry(
        self,
        principal: AuthenticatedPrincipal,
        entry: Any,
        *,
        selection_name: str,
        alias: str | None = None,
        execution_inputs: dict[str, Any] | None = None,
    ) -> RobotFlowExecutionResponse:
        """Stage an immutable entry supplied only by a trusted server adapter."""
        forbidden = _authorize(principal)
        if forbidden is not None:
            return forbidden
        from robot_platform.flow.models import FlowEntry

        if not isinstance(entry, FlowEntry):
            return _failure("flow_snapshot_invalid", "Flow snapshot is invalid.")
        if not isinstance(selection_name, str) or not selection_name.strip():
            return _failure("invalid_flow_request", "flow_name is required.")
        if alias is not None and not isinstance(alias, str):
            return _failure("invalid_flow_request", "alias must be a string.")
        if execution_inputs is not None and not isinstance(execution_inputs, dict):
            return _failure("invalid_flow_request", "inputs must be an object.")
        outcome = self._planning.stage_flow_entry(
            principal,
            deepcopy(entry),
            selection_name=selection_name.strip(),
            alias=alias.strip() if isinstance(alias, str) and alias.strip() else None,
            execution_inputs=deepcopy(execution_inputs or {}),
        )
        return _planning_response(outcome)

    @_fail_closed
    def preview(
        self, principal: AuthenticatedPrincipal, body: Any,
    ) -> RobotFlowExecutionResponse:
        forbidden = _authorize(principal)
        if forbidden is not None:
            return forbidden
        if not isinstance(body, dict):
            return _failure("invalid_flow_request", "Request body must be an object.")
        if bool(body.get("execute_real")):
            return _failure(
                "staged_execution_required",
                "Real execution requires the staged flow plan endpoints.",
            )
        name = body.get("name")
        alias = body.get("alias")
        if not isinstance(name, str) or not name.strip():
            return _failure("invalid_flow_request", "name is required.")
        if alias is not None and not isinstance(alias, str):
            return _failure("invalid_flow_request", "alias must be a string.")
        response = self._flows.query(RobotFlowQuery(
            principal,
            "preview",
            name.strip(),
            alias.strip() if isinstance(alias, str) else "",
        ))
        if not response.ok or not isinstance(response.payload, dict):
            error = response.error
            return _failure(
                getattr(error, "code", "flow_state_unavailable"),
                getattr(error, "message", "Flow state is unavailable."),
            )
        result = response.payload.get("result")
        if not isinstance(result, dict):
            return _failure("flow_state_unavailable", "Flow state is unavailable.")
        try:
            return RobotFlowExecutionResponse(payload=_public_result(result))
        except Exception:
            return _failure("flow_state_unavailable", "Flow state is unavailable.")

    @_fail_closed
    def confirm(
        self, principal: AuthenticatedPrincipal, plan_id: str, body: Any,
    ) -> RobotFlowExecutionResponse:
        forbidden = _authorize(principal)
        if forbidden is not None:
            return forbidden
        if not isinstance(body, dict):
            return _failure("invalid_flow_request", "Request body must be an object.")
        if not bool(body.get("confirm_work_area_clear")) or not bool(
            body.get("confirm_estop_ready")
        ):
            return _failure(
                "flow_confirmation_required", "Both safety confirmations are required.",
            )
        requested_approvals = body.get("approved_node_ids", [])
        if not isinstance(requested_approvals, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in requested_approvals
        ):
            return _failure(
                "invalid_flow_request", "approved_node_ids must contain node IDs.",
            )
        plan = self._pending_plans.get(plan_id)
        if plan is None or plan.command != "flow_run":
            return _failure("flow_plan_not_found", "Pending Flow plan was not found.")
        if not self._session_gates.confirm(_session_key(principal), plan_id):
            return _failure("flow_session_not_confirmed", "Flow session does not match.")
        if not self._pending_plans.confirm(plan_id):
            return _failure("flow_confirmation_invalid", "Flow plan cannot be confirmed.")
        from robot_platform.execution.permit import UnresolvedExecutionError

        try:
            from robot_platform.flow.snapshot import FlowExecutionSnapshot
            from robot_platform.flow.nodes import HumanApprovalNode, iter_nodes

            snapshot = FlowExecutionSnapshot.from_dict(plan.parameters["snapshot"])
            required_approvals = {
                node.node_id for node in iter_nodes(snapshot.root_node)
                if isinstance(node, HumanApprovalNode)
            }
            if set(requested_approvals) != required_approvals:
                return _failure(
                    "flow_node_approval_required",
                    "Every HumanApproval node requires explicit authenticated approval.",
                )
            if required_approvals and self._approval_store is None:
                return _failure(
                    "flow_node_approval_unavailable", "Flow approval service is unavailable.",
                )
            approval_receipts = {
                node_id: self._approval_store.issue(
                    plan_id=plan_id,
                    node_id=node_id,
                    snapshot_hash=snapshot.content_hash,
                    principal=principal,
                )
                for node_id in required_approvals
            }
            from robot_platform.operation_control import current_operation_control

            control = current_operation_control()
            operation_id = str(
                getattr(control, "effect_operation_id", "")
                or f"robot-operation:{plan_id}"
            )
            parent = self._permits.issue_flow_parent(
                self._scope(plan, principal),
                operation_id=operation_id,
                idempotency_key=plan_id,
            )
            child_handles = tuple(
                self._permits.issue_flow_child(
                    self._step_scope(plan, snapshot, step, principal),
                    parent_handle=parent.handle,
                    operation_id=f"robot-flow:{plan_id}:step:{step.index}",
                    idempotency_key=f"{plan_id}:step:{step.index}",
                ).handle
                for step in snapshot.steps
            )
        except UnresolvedExecutionError:
            return _failure(
                "execution_outcome_unknown",
                "A prior controller execution needs safety recovery before a new Flow.",
            )
        except (KeyError, TypeError, ValueError):
            return _failure("flow_snapshot_invalid", "Flow snapshot cannot be authorized.")
        receipt = self._pending_plans.authorize(
            plan_id,
            permit_handle=parent.handle,
            child_permit_handles=child_handles,
            node_approval_receipts=approval_receipts,
        )
        if receipt is None:
            return _failure("flow_confirmation_invalid", "Flow plan cannot be authorized.")
        return RobotFlowExecutionResponse(payload={"confirm_code": receipt})

    @_fail_closed
    def execute(
        self, principal: AuthenticatedPrincipal, plan_id: str, body: Any,
    ) -> RobotFlowExecutionResponse:
        forbidden = _authorize(principal)
        if forbidden is not None:
            return forbidden
        if not isinstance(body, dict):
            return _failure("invalid_flow_request", "Request body must be an object.")
        receipt = body.get("confirm_code")
        if not isinstance(receipt, str) or not receipt:
            return _failure("invalid_flow_request", "confirm_code is required.")
        plan = self._pending_plans.get(plan_id)
        if plan is None or plan.command != "flow_run":
            return _failure("flow_plan_not_found", "Pending Flow plan was not found.")
        try:
            from robot_platform.flow.snapshot import FlowExecutionSnapshot

            snapshot = FlowExecutionSnapshot.from_dict(plan.parameters["snapshot"])
        except (KeyError, TypeError, ValueError):
            return _failure("flow_snapshot_invalid", "Flow snapshot is invalid.")
        if (
            snapshot.product_profile_version != self.product_profile_version
            or snapshot.capability_version != self.capability_version
            or snapshot.core_version != self.core_version
        ):
            return _failure(
                "flow_dependencies_changed",
                "Flow snapshot dependencies changed; create a new plan.",
            )
        if len(plan.child_permit_handles) != len(snapshot.steps):
            return _failure("flow_snapshot_invalid", "Flow child permits are incomplete.")
        parent_handle, early = self._begin(plan, principal, receipt)
        if early is not None:
            return early
        assert parent_handle is not None
        from robot_platform.execution.permit import FlowStepExecutionGrant

        grants = tuple(
            FlowStepExecutionGrant(
                permit_handle=handle,
                scope=self._step_scope(plan, snapshot, step, principal),
                dispatch_id=f"{plan_id}:step:{step.index}:dispatch",
            )
            for handle, step in zip(
                plan.child_permit_handles, snapshot.steps, strict=True,
            )
        )
        active_step = 0
        from robot_platform.application.flow_execution_hooks import (
            current_flow_execution_hooks,
        )

        hooks = current_flow_execution_hooks()

        def before_step(index: int) -> bool:
            nonlocal active_step
            if hooks is not None and hooks.before_step is not None:
                try:
                    if not hooks.before_step(index):
                        return False
                except Exception:
                    return False
            grant = grants[index - 1]
            if not self._permits.reserve(grant.permit_handle, grant.scope):
                return False
            if not self._permits.mark_executing(grant.permit_handle):
                return False
            active_step = index
            return True

        def on_step(
            index: int, status: str, step_result: dict[str, Any] | None,
        ) -> None:
            nonlocal active_step
            if status == "running" or step_result is None:
                if hooks is not None and hooks.on_step is not None:
                    try:
                        hooks.on_step(index, status, step_result)
                    except Exception:
                        pass
                return
            grant = grants[index - 1]
            if status == "succeeded" and step_result.get("ok") is True:
                try:
                    public_step = _public_result(step_result)
                except Exception:
                    self._permits.mark_outcome_unknown(
                        grant.permit_handle, reason="flow_step_result_invalid",
                    )
                else:
                    if not self._permits.complete(grant.permit_handle, public_step):
                        self._permits.mark_outcome_unknown(
                            grant.permit_handle,
                            reason="flow_step_result_commit_failed",
                        )
            else:
                self._permits.mark_outcome_unknown(
                    grant.permit_handle,
                    reason="flow_step_returned_non_definite_failure",
                )
            active_step = 0
            if hooks is not None and hooks.on_step is not None:
                try:
                    hooks.on_step(index, status, step_result)
                except Exception:
                    pass

        try:
            run_options: dict[str, Any] = dict(
                execute_real=True,
                confirm_work_area_clear=True,
                confirm_estop_ready=True,
                permit_verifier=self._permits,
                flow_step_grants=grants,
                before_step=before_step,
                on_step=on_step,
            )
            if self._event_sink is not None:
                run_options["execution_id"] = plan_id
                run_options["on_event"] = self._event_sink.append
            if plan.node_approval_receipts:
                if self._approval_store is None:
                    raise RuntimeError("Flow approval service is unavailable")

                def approval_checker(node: Any) -> bool:
                    return self._approval_store.claim(
                        plan.node_approval_receipts.get(str(node.node_id), ""),
                        plan_id=plan_id,
                        node_id=str(node.node_id),
                        snapshot_hash=snapshot.content_hash,
                        principal=principal,
                    )

                run_options["approval_checker"] = approval_checker
            raw = self._platform.run_flow_entry(snapshot, **run_options)
            if self._approval_store is not None:
                self._approval_store.revoke_plan(plan_id)
        except Exception:
            if self._approval_store is not None:
                self._approval_store.revoke_plan(plan_id)
            if active_step:
                self._permits.mark_outcome_unknown(
                    grants[active_step - 1].permit_handle,
                    reason="flow_platform_raised_after_step_started",
                )
            self._permits.mark_outcome_unknown(
                parent_handle, reason="flow_platform_raised_after_execution_started",
            )
            return _failure("flow_outcome_unknown", "Flow outcome is unknown.")
        try:
            result = _public_result(raw)
            if not isinstance(result, dict):
                raise TypeError("Flow result is invalid")
        except Exception:
            self._permits.mark_outcome_unknown(
                parent_handle, reason="flow_result_invalid",
            )
            return _failure("flow_outcome_unknown", "Flow outcome is unknown.")
        from robot_platform.execution.permit import ExecutionPermitState

        if result.get("ok") is True:
            # Branch/compensation actions that were not selected must lose
            # their dispatch authority before the parent can be committed.
            # ``skip_unstarted`` is an atomic ISSUED -> SKIPPED transition;
            # an already consumed child simply fails that transition and is
            # verified below.
            for grant in grants:
                self._permits.skip_unstarted(
                    grant.permit_handle,
                    reason="flow_node_not_selected",
                )
            if any(
                (record := self._permits.get(grant.permit_handle)) is None
                or record.state not in {
                    ExecutionPermitState.CONSUMED,
                    ExecutionPermitState.SKIPPED,
                }
                for grant in grants
            ):
                self._permits.mark_outcome_unknown(
                    parent_handle,
                    reason="flow_completed_without_terminal_child_results",
                )
                return _failure(
                    "flow_commit_failed", "Flow child results were not committed.",
                )
            if not self._permits.complete(parent_handle, result):
                self._permits.mark_outcome_unknown(
                    parent_handle, reason="successful_result_could_not_be_committed",
                )
                return _failure("flow_commit_failed", "Flow result was not committed.")
        else:
            self._permits.mark_outcome_unknown(
                parent_handle, reason="flow_returned_non_definite_failure",
            )
        return RobotFlowExecutionResponse(payload=result)

    def _begin(
        self, plan: Any, principal: AuthenticatedPrincipal, receipt: str,
    ) -> tuple[str | None, RobotFlowExecutionResponse | None]:
        if not self._session_gates.is_confirmed(_session_key(principal), plan.plan_id):
            return None, _failure("flow_session_not_confirmed", "Flow session does not match.")
        if not self._pending_plans.verify_confirmation(plan.plan_id, receipt):
            return None, _failure("flow_confirmation_invalid", "Flow confirmation is invalid.")
        if not plan.permit_handle:
            return None, _failure("flow_permit_missing", "Flow permit is missing.")
        scope = self._scope(plan, principal)
        definite = self._permits.definite_result_for_exact_execution(
            plan.permit_handle, plan.plan_id, scope,
        )
        if definite is not None:
            try:
                public = _public_result(definite)
                if not isinstance(public, dict):
                    raise TypeError("Flow result is invalid")
                return None, RobotFlowExecutionResponse(payload=public)
            except Exception:
                return None, _failure("flow_state_unavailable", "Flow state is unavailable.")
        record = self._permits.get(plan.permit_handle)
        if record is None:
            return None, _failure("flow_permit_missing", "Flow permit is missing.")
        if (
            str(getattr(record, "handle", "")) != plan.permit_handle
            or str(getattr(record, "idempotency_key", "")) != plan.plan_id
            or str(getattr(record, "scope_hash", "")) != scope.scope_hash
            or str(getattr(record, "execution_identity_hash", ""))
            != scope.execution_identity_hash
        ):
            return None, _failure(
                "flow_permit_scope_mismatch",
                "Flow permit does not match the current execution identity.",
            )
        from robot_platform.execution.permit import ExecutionPermitState

        if record.state is ExecutionPermitState.OUTCOME_UNKNOWN:
            return None, _failure("flow_outcome_unknown", "Flow outcome is unknown.")
        if not self._permits.reserve(plan.permit_handle, scope):
            return None, _failure("flow_permit_not_reservable", "Flow permit is not reservable.")
        if not self._permits.mark_executing(plan.permit_handle):
            return None, _failure("flow_permit_expired", "Flow permit expired.")
        return plan.permit_handle, None

    def _scope(self, plan: Any, principal: AuthenticatedPrincipal) -> Any:
        from robot_platform.execution.permit import ExecutionScope

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

    def _step_scope(
        self, plan: Any, snapshot: Any, step: Any, principal: AuthenticatedPrincipal,
    ) -> Any:
        from robot_platform.execution.permit import ExecutionScope

        return ExecutionScope.for_payload(
            principal=principal,
            robot_id=self.robot_id,
            controller_id=self.controller_id,
            operation_type=step.command,
            payload={"command": step.command, "parameters": step.parameters},
            payload_schema_version="1",
            product_profile_version=snapshot.product_profile_version,
            capability_version=snapshot.capability_version,
            deployment_instance_id=self.deployment_instance_id,
            core_version=snapshot.core_version,
            plan_id=f"{plan.plan_id}:step:{step.index}",
            plan_version=f"{plan.plan_version}:{snapshot.content_hash}",
        )


_SENSITIVE_KEY_PARTS = (
    "password", "secret", "token", "permit", "scope", "sdk", "path",
    "host", "controller", "config", "credential",
)


def _public_result(value: Any, *, depth: int = 0) -> Any:
    if depth > 10:
        raise ValueError("Flow result is too deep")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_public_result(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        public: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Flow result key is invalid")
            lowered = key.casefold()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                continue
            public[key] = _public_result(item, depth=depth + 1)
        return public
    raise TypeError("Flow result is invalid")


def _planning_response(outcome: RobotDryRunResponse) -> RobotFlowExecutionResponse:
    if outcome.ok and isinstance(outcome.payload, dict):
        return RobotFlowExecutionResponse(
            payload=deepcopy(outcome.payload), staged=outcome.staged,
        )
    error = outcome.error
    return _failure(
        getattr(error, "code", "dry_run_unavailable"),
        getattr(error, "message", "Robot dry-run is unavailable."),
    )


def _authorize(principal: Any) -> RobotFlowExecutionResponse | None:
    if not isinstance(principal, AuthenticatedPrincipal):
        return _failure("invalid_flow_request", "Authenticated principal is required.")
    if principal.role not in {"operator", "engineer"}:
        return _failure("flow_forbidden", "Operator role is required.")
    return None


def _session_key(principal: AuthenticatedPrincipal) -> str:
    return f"robot-server:{principal.session_id}"


def _failure(code: str, message: str) -> RobotFlowExecutionResponse:
    return RobotFlowExecutionResponse(error=RobotFlowExecutionError(code, message))
