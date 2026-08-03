"""Trusted automatic Flow execution after the L1 safety plan succeeds.

Tool and library callers may request automatic execution, but neither receives
nor constructs a controller credential.  The existing staged Flow application
continues to own immutable snapshots, one-use permits and real dispatch.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotAutomaticFlowCommand:
    principal: AuthenticatedPrincipal
    flow_name: str
    alias: str = ""
    inputs: dict[str, Any] | None = None
    expected_snapshot_hash: str = ""


@dataclass(frozen=True)
class RobotAutomaticFlowError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotAutomaticFlowResponse:
    payload: dict[str, Any] | None = None
    error: RobotAutomaticFlowError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotAutomaticFlowApplicationPort(Protocol):
    def execute(
        self, command: RobotAutomaticFlowCommand,
    ) -> RobotAutomaticFlowResponse: ...

    def execute_entry(
        self,
        principal: AuthenticatedPrincipal,
        entry: Any,
        *,
        selection_name: str,
    ) -> RobotAutomaticFlowResponse: ...


class RobotAutomaticFlowApplicationService:
    """Drive the existing Flow plan-confirm-execute lifecycle in-process."""

    def __init__(self, flow_execution: Any) -> None:
        self._flow_execution = flow_execution

    def execute(
        self, command: RobotAutomaticFlowCommand,
    ) -> RobotAutomaticFlowResponse:
        if not isinstance(command, RobotAutomaticFlowCommand):
            return _failure("invalid_automatic_flow", "Flow request is invalid.")
        if command.principal.role not in {"operator", "engineer"}:
            return _failure("flow_forbidden", "Operator authentication is required.")
        if not isinstance(command.flow_name, str) or not command.flow_name.strip():
            return _failure("invalid_automatic_flow", "Flow name is required.")
        if not isinstance(command.alias, str):
            return _failure("invalid_automatic_flow", "Flow alias is invalid.")
        if command.inputs is not None and not isinstance(command.inputs, dict):
            return _failure("invalid_automatic_flow", "Flow inputs must be an object.")
        if not isinstance(command.expected_snapshot_hash, str):
            return _failure("invalid_automatic_flow", "Flow snapshot hash is invalid.")
        body = {
            "flow_name": command.flow_name.strip(),
            "alias": command.alias.strip(),
            "inputs": deepcopy(command.inputs or {}),
        }
        if command.expected_snapshot_hash:
            body["expected_snapshot_hash"] = command.expected_snapshot_hash
        staged = self._flow_execution.plan(command.principal, body)
        return self._complete(command.principal, staged)

    def execute_entry(
        self,
        principal: AuthenticatedPrincipal,
        entry: Any,
        *,
        selection_name: str,
    ) -> RobotAutomaticFlowResponse:
        """Execute a trusted library snapshot, never a client-supplied entry."""
        if principal.role not in {"operator", "engineer"}:
            return _failure("flow_forbidden", "Operator authentication is required.")
        if not isinstance(selection_name, str) or not selection_name.strip():
            return _failure("invalid_automatic_flow", "Flow name is required.")
        plan_entry = getattr(self._flow_execution, "plan_entry", None)
        if not callable(plan_entry):
            return _failure("flow_unavailable", "Flow service is unavailable.")
        staged = plan_entry(principal, entry, selection_name=selection_name.strip())
        return self._complete(principal, staged)

    def _complete(
        self, principal: AuthenticatedPrincipal, staged: Any,
    ) -> RobotAutomaticFlowResponse:
        if not getattr(staged, "ok", False):
            return _from_response(staged, "automatic_flow_safety_failed")
        if not getattr(staged, "staged", False):
            # Preserve a structured L1 safety rejection and never issue a permit.
            payload = getattr(staged, "payload", None)
            if isinstance(payload, dict):
                return RobotAutomaticFlowResponse(payload=deepcopy(payload))
            return _failure("automatic_flow_safety_failed", "Flow safety planning failed.")
        payload = getattr(staged, "payload", None)
        plan_id = str(payload.get("plan_id") or "") if isinstance(payload, dict) else ""
        if not plan_id:
            return _failure("automatic_flow_plan_missing", "Flow plan is unavailable.")
        confirmed = self._flow_execution.confirm(principal, plan_id, {
            "confirm_work_area_clear": True,
            "confirm_estop_ready": True,
            # HumanApproval nodes remain explicit; automatic runs never add IDs.
            "approved_node_ids": [],
        })
        if not getattr(confirmed, "ok", False):
            return _from_response(confirmed, "automatic_flow_confirmation_failed")
        confirmed_payload = getattr(confirmed, "payload", None)
        receipt = (
            str(confirmed_payload.get("confirm_code") or "")
            if isinstance(confirmed_payload, dict) else ""
        )
        if not receipt:
            return _failure(
                "automatic_flow_confirmation_failed", "Flow confirmation is unavailable.",
            )
        executed = self._flow_execution.execute(
            principal, plan_id, {"confirm_code": receipt},
        )
        if not getattr(executed, "ok", False):
            return _from_response(executed, "automatic_flow_failed")
        result = getattr(executed, "payload", None)
        if not isinstance(result, dict):
            return _failure("execution_outcome_unknown", "Flow outcome is unknown.")
        if result.get("ok") is not True:
            return _failure("execution_outcome_unknown", "Flow outcome is unknown.")
        return RobotAutomaticFlowResponse(payload=deepcopy(result))


def _from_response(response: Any, fallback: str) -> RobotAutomaticFlowResponse:
    error = getattr(response, "error", None)
    code = str(getattr(error, "code", fallback))
    message = str(getattr(error, "message", "Automatic Flow did not complete."))
    if code in {"flow_outcome_unknown", "flow_commit_failed"}:
        return _failure("execution_outcome_unknown", "Flow outcome is unknown; complete execution recovery before retrying.")
    return _failure(code, message)


def _failure(code: str, message: str) -> RobotAutomaticFlowResponse:
    return RobotAutomaticFlowResponse(
        error=RobotAutomaticFlowError(str(code), str(message)),
    )
