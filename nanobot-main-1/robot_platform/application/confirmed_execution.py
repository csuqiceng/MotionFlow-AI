"""Shared fail-closed engine for confirmed, single-command execution."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol

from .principal import AuthenticatedPrincipal

if TYPE_CHECKING:
    from robot_platform.execution.permit import ExecutionScope


class ConfirmedPendingPlanPort(Protocol):
    def get(self, plan_id: str) -> Any: ...
    def verify_confirmation(self, plan_id: str, receipt: str) -> bool: ...


class ConfirmedSessionGatePort(Protocol):
    def is_confirmed(self, session_key: str | None, plan_id: str) -> bool: ...


class ConfirmedPermitStorePort(Protocol):
    def definite_result_for_exact_execution(
        self, handle: str, idempotency_key: str, expected_scope: ExecutionScope,
    ) -> dict[str, Any] | None: ...
    def get(self, handle: str) -> Any: ...
    def reserve(self, handle: str, scope: ExecutionScope) -> bool: ...
    def mark_executing(self, handle: str) -> bool: ...
    def abort_before_dispatch(self, handle: str, *, reason: str) -> bool: ...
    def complete(self, handle: str, result: dict[str, Any]) -> bool: ...
    def mark_outcome_unknown(self, handle: str, *, reason: str) -> bool: ...


class ConfirmedExecutionPlatformPort(Protocol):
    def execute_confirmed_plan(
        self, command: str, parameters: dict[str, Any], **kwargs: Any,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ConfirmedExecutionPolicy:
    """Use-case policy kept outside the reusable execution state machine."""

    family: str
    title: str
    subject: str
    plan_description: str
    allowed_commands: frozenset[str]
    validate_parameters: Callable[[str, dict[str, Any]], bool]
    public_data: Callable[[str, dict[str, Any], Any], dict[str, Any]]
    success_message: str
    failure_message: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,31}", self.family) is None:
            raise ValueError("confirmed execution policy requires a safe family")
        if not self.allowed_commands:
            raise ValueError("confirmed execution policy requires allowed commands")


@dataclass(frozen=True)
class ConfirmedExecutionOutcome:
    payload: dict[str, Any] | None = None
    error_key: str | None = None
    error_message: str | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error_key is None):
            raise ValueError("confirmed execution outcome requires payload or error")
        if self.error_key is not None and (
            not self.error_message or self.replayed
        ):
            raise ValueError("invalid confirmed execution error")


class ConfirmedPlanExecutionEngine:
    """Own the common confirmation, permit, dispatch and replay state machine."""

    def __init__(
        self,
        platform: ConfirmedExecutionPlatformPort,
        pending_plans: ConfirmedPendingPlanPort,
        session_gates: ConfirmedSessionGatePort,
        permits: ConfirmedPermitStorePort,
        *,
        robot_id: str,
        controller_id: str,
        product_profile_version: str,
        capability_version: str,
        deployment_instance_id: str,
        core_version: str,
    ) -> None:
        self.platform = platform
        self.pending_plans = pending_plans
        self.session_gates = session_gates
        self.permits = permits
        self.robot_id = str(robot_id)
        self.controller_id = str(controller_id)
        self.product_profile_version = str(product_profile_version)
        self.capability_version = str(capability_version)
        self.deployment_instance_id = str(deployment_instance_id)
        self.core_version = str(core_version)
        if not all(value.strip() for value in (
            self.robot_id, self.controller_id, self.product_profile_version,
            self.capability_version, self.deployment_instance_id, self.core_version,
        )):
            raise ValueError("ConfirmedPlanExecutionEngine requires execution identity")

    def execute(
        self,
        *,
        principal: AuthenticatedPrincipal,
        plan_id: str,
        confirmation_receipt: str,
        policy: ConfirmedExecutionPolicy,
    ) -> ConfirmedExecutionOutcome:
        if principal.role not in {"operator", "engineer"}:
            return self._failure(
                "forbidden", f"Operator role is required for {policy.subject}.",
            )
        reservation_attempted = False
        permit_handle = ""
        try:
            plan = self.pending_plans.get(plan_id)
        except Exception:
            return self._unavailable(policy)
        if plan is None:
            return self._failure(
                "plan_not_found", f"Pending {policy.subject} plan was not found.",
            )
        try:
            plan_command = getattr(plan, "command", None)
        except Exception:
            return self._unavailable(policy)
        if not isinstance(plan_command, str):
            return self._unavailable(policy)
        if plan_command not in policy.allowed_commands:
            return self._failure(
                "unsupported_plan", f"Plan is not {policy.plan_description}.",
            )
        try:
            stored_plan_id = str(getattr(plan, "plan_id", ""))
            permit_handle = str(getattr(plan, "permit_handle", ""))
        except Exception:
            return self._unavailable(policy)
        if stored_plan_id != plan_id:
            return self._unavailable(policy)
        try:
            parameters = deepcopy(getattr(plan, "parameters"))
            if not isinstance(parameters, dict):
                raise TypeError("plan parameters are invalid")
            if not policy.validate_parameters(plan_command, parameters):
                return self._failure(
                    "plan_invalid", f"Pending {policy.subject} plan is invalid.",
                )
            session_key = f"robot-server:{principal.session_id}"
            if not self.session_gates.is_confirmed(session_key, stored_plan_id):
                return self._failure(
                    "session_not_confirmed",
                    f"Session has no matching confirmed {policy.subject} plan.",
                )
            if not self.pending_plans.verify_confirmation(
                stored_plan_id, confirmation_receipt,
            ):
                return self._failure(
                    "confirmation_invalid",
                    f"{policy.title} confirmation is invalid or expired.",
                )
            if not permit_handle:
                return self._failure(
                    "permit_missing", f"{policy.title} permit is missing.",
                )
            record = self.permits.get(permit_handle)
            if record is None:
                return self._failure(
                    "permit_missing", f"{policy.title} permit is missing.",
                )
            scope = self._scope(plan, principal, parameters)
            if (
                str(getattr(record, "handle", "")) != permit_handle
                or str(getattr(record, "idempotency_key", "")) != stored_plan_id
                or str(getattr(record, "scope_hash", "")) != scope.scope_hash
                or str(getattr(record, "execution_identity_hash", ""))
                != scope.execution_identity_hash
            ):
                return self._failure(
                    "permit_scope_mismatch",
                    f"{policy.title} permit does not match the current execution identity.",
                )
            replay = self._replay(
                permit_handle, stored_plan_id, scope, plan_command, parameters, policy,
            )
            if replay is not None:
                return replay
            state = getattr(
                getattr(record, "state", None), "value", getattr(record, "state", ""),
            )
            if state == "outcome_unknown":
                return self._failure(
                    "outcome_unknown",
                    f"{policy.title} outcome is unknown; reconcile before retrying.",
                )
            reservation_attempted = True
            if not self.permits.reserve(permit_handle, scope):
                replay = self._replay(
                    permit_handle, stored_plan_id, scope, plan_command, parameters, policy,
                )
                return replay or self._failure(
                    "permit_not_reservable",
                    f"{policy.title} permit is not reservable.",
                )
            if not self.permits.mark_executing(permit_handle):
                self._abort_reservation(
                    permit_handle, "execution_permit_expired_before_dispatch",
                )
                replay = self._replay(
                    permit_handle, stored_plan_id, scope, plan_command, parameters, policy,
                )
                return replay or self._failure(
                    "permit_expired",
                    f"{policy.title} permit expired before dispatch.",
                )
        except Exception:
            if reservation_attempted:
                self._finish_failed_start(permit_handle)
            return self._unavailable(policy)

        try:
            raw = self.platform.execute_confirmed_plan(
                plan_command,
                deepcopy(parameters),
                confirm_work_area_clear=True,
                confirm_estop_ready=True,
                execution_permit_handle=permit_handle,
                execution_scope=scope,
                permit_verifier=self.permits,
                execution_operation_type=scope.operation_type,
                execution_payload={
                    "command": plan_command, "parameters": deepcopy(parameters),
                },
                execution_dispatch_id=f"{stored_plan_id}:0",
            )
            result = normalize_confirmed_result(
                raw, command=plan_command, parameters=parameters, policy=policy,
            )
        except Exception:
            self._mark_unknown(permit_handle, "platform_raised_after_execution_started")
            return self._failure(
                "dispatch_outcome_unknown",
                f"{policy.title} outcome is unknown; reconcile controller state.",
            )
        if result["ok"] is True:
            try:
                committed = self.permits.complete(permit_handle, result)
            except Exception:
                committed = False
            if committed:
                return ConfirmedExecutionOutcome(payload=result)
            self._mark_unknown(permit_handle, "successful_result_could_not_be_committed")
            return self._failure(
                "commit_failed", f"{policy.title} result could not be committed.",
            )
        if not self._mark_unknown(
            permit_handle, "platform_returned_non_definite_failure",
        ):
            return self._failure(
                "commit_failed", f"{policy.title} uncertainty could not be recorded.",
            )
        return ConfirmedExecutionOutcome(payload=result)

    def _scope(
        self, plan: Any, principal: AuthenticatedPrincipal, parameters: dict[str, Any],
    ) -> ExecutionScope:
        from robot_platform.execution.permit import ExecutionScope

        return ExecutionScope.for_payload(
            principal=principal,
            robot_id=self.robot_id,
            controller_id=self.controller_id,
            operation_type=str(plan.command),
            payload={"command": str(plan.command), "parameters": parameters},
            payload_schema_version="1",
            product_profile_version=self.product_profile_version,
            capability_version=self.capability_version,
            deployment_instance_id=self.deployment_instance_id,
            core_version=self.core_version,
            plan_id=str(plan.plan_id),
            plan_version=str(plan.plan_version),
        )

    def _replay(
        self,
        permit_handle: str,
        plan_id: str,
        scope: ExecutionScope,
        command: str,
        parameters: dict[str, Any],
        policy: ConfirmedExecutionPolicy,
    ) -> ConfirmedExecutionOutcome | None:
        result = self.permits.definite_result_for_exact_execution(
            permit_handle, plan_id, scope,
        )
        if result is None:
            return None
        try:
            return ConfirmedExecutionOutcome(
                payload=normalize_confirmed_result(
                    result, command=command, parameters=parameters, policy=policy,
                ),
                replayed=True,
            )
        except Exception:
            return self._unavailable(policy)

    def _mark_unknown(self, handle: str, reason: str) -> bool:
        try:
            return self.permits.mark_outcome_unknown(handle, reason=reason)
        except Exception:
            return False

    def _finish_failed_start(self, handle: str) -> None:
        if self._mark_unknown(handle, "execution_start_state_uncertain"):
            return
        self._abort_reservation(handle, "execution_start_failed_before_dispatch")

    def _abort_reservation(self, handle: str, reason: str) -> bool:
        try:
            return self.permits.abort_before_dispatch(handle, reason=reason)
        except Exception:
            return False

    @staticmethod
    def _failure(key: str, message: str) -> ConfirmedExecutionOutcome:
        return ConfirmedExecutionOutcome(error_key=key, error_message=message)

    def _unavailable(
        self, policy: ConfirmedExecutionPolicy,
    ) -> ConfirmedExecutionOutcome:
        return self._failure(
            "state_unavailable", f"{policy.title} state is unavailable.",
        )


def normalize_confirmed_result(
    raw: Any,
    *,
    command: str,
    parameters: dict[str, Any],
    policy: ConfirmedExecutionPolicy,
) -> dict[str, Any]:
    """Return the only representation allowed in HTTP, persistence and replay."""
    if not isinstance(raw, dict) or not isinstance(raw.get("ok"), bool):
        raise ValueError("invalid confirmed execution result")
    state = raw.get("state")
    if not isinstance(state, str) or re.fullmatch(
        r"[a-z][a-z0-9_]{0,95}", state.strip(),
    ) is None:
        raise ValueError("invalid confirmed execution state")
    ok = raw["ok"] is True
    result: dict[str, Any] = {"ok": ok, "state": state.strip()}
    if "message" in raw:
        result["message"] = policy.success_message if ok else policy.failure_message
    public_data = policy.public_data(command, parameters, raw.get("data"))
    if public_data:
        result["data"] = public_data
    if not ok:
        result.setdefault("message", policy.failure_message)
        result["errors"] = [{"code": state.strip()}]
    return result


def public_execution_metadata(raw: Any) -> dict[str, Any]:
    """Whitelist backend-neutral execution evidence shared by command families."""
    if not isinstance(raw, dict):
        return {}
    public: dict[str, Any] = {}
    action = raw.get("action")
    if isinstance(action, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action):
        public["action"] = action
    for key in (
        "function_code", "parameter_write_count", "write_count", "echo_count",
        "trigger_vr", "completion_attempts", "pose_convergence_attempts",
        "segment_count", "completed_segments",
    ):
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            public[key] = value
    for key in ("trigger_submitted", "saw_executing", "real_execution"):
        value = raw.get(key)
        if isinstance(value, bool):
            public[key] = value
    return public
