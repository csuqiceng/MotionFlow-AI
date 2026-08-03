"""Trusted automatic motion after a successful L1 safety plan.

The Agent Tool may request this use case, but it never receives or creates an
execution permit.  Permit issuance and dispatch remain owned by this injected
server-side Application service.
"""

from __future__ import annotations

import secrets
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from robot_platform.operation_control import current_operation_control

from .dry_run import RobotDryRunApplicationService
from .motion import (
    MOTION_COMMANDS,
    RobotMotionApplicationService,
    RobotMotionExecutionCommand,
)
from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotAutomaticMotionCommand:
    principal: AuthenticatedPrincipal
    command: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class RobotAutomaticMotionError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotAutomaticMotionResponse:
    payload: dict[str, Any] | None = None
    error: RobotAutomaticMotionError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotAutomaticMotionApplicationPort(Protocol):
    def execute(
        self, command: RobotAutomaticMotionCommand,
    ) -> RobotAutomaticMotionResponse: ...


class RobotAutomaticMotionApplicationService:
    """Stage, authorize and execute one motion inside the trusted server graph."""

    def __init__(
        self,
        planning: RobotDryRunApplicationService,
        pending_plans: Any,
        session_gates: Any,
        permits: Any,
        motion: RobotMotionApplicationService,
        *,
        robot_id: str,
        controller_id: str,
        product_profile_version: str,
        capability_version: str,
        deployment_instance_id: str,
        core_version: str,
    ) -> None:
        self._planning = planning
        self._pending_plans = pending_plans
        self._session_gates = session_gates
        self._permits = permits
        self._motion = motion
        self._robot_id = robot_id
        self._controller_id = controller_id
        self._product_profile_version = product_profile_version
        self._capability_version = capability_version
        self._deployment_instance_id = deployment_instance_id
        self._core_version = core_version

    def execute(
        self, command: RobotAutomaticMotionCommand,
    ) -> RobotAutomaticMotionResponse:
        if not isinstance(command, RobotAutomaticMotionCommand):
            return _failure("invalid_automatic_motion", "Motion request is invalid.")
        if command.command not in MOTION_COMMANDS:
            return _failure("invalid_automatic_motion", "Motion command is unsupported.")
        if command.principal.role not in {"operator", "engineer"}:
            return _failure("motion_forbidden", "Operator authentication is required.")

        staged = self._planning.stage_command(
            command.principal, command.command, deepcopy(command.parameters),
        )
        if not staged.ok or not isinstance(staged.payload, dict):
            error = staged.error
            return _failure(
                getattr(error, "code", "automatic_motion_safety_failed"),
                getattr(error, "message", "Automatic motion safety planning failed."),
            )
        if not staged.staged:
            # A completed L1 evaluation may legitimately return a structured
            # safety rejection. Preserve that exact result and never issue a
            # permit for it.
            return RobotAutomaticMotionResponse(payload=deepcopy(staged.payload))
        plan_id = str(staged.payload.get("plan_id") or "")
        plan = self._pending_plans.get(plan_id)
        if plan is None:
            return _failure("automatic_motion_plan_missing", "Motion plan is unavailable.")

        session_key = f"robot-server:{command.principal.session_id}"
        if not self._session_gates.confirm(session_key, plan_id):
            return _failure("automatic_motion_session_mismatch", "Motion session changed.")
        if not self._pending_plans.confirm(plan_id):
            return _failure("automatic_motion_plan_expired", "Motion plan expired.")

        # Local import avoids the application-package / permit-module bootstrap
        # cycle while keeping permit construction inside this trusted service.
        from robot_platform.execution.permit import ExecutionScope, UnresolvedExecutionError

        scope = ExecutionScope.for_payload(
            principal=command.principal,
            robot_id=self._robot_id,
            controller_id=self._controller_id,
            operation_type=plan.command,
            payload={"command": plan.command, "parameters": plan.parameters},
            payload_schema_version="1",
            product_profile_version=self._product_profile_version,
            capability_version=self._capability_version,
            deployment_instance_id=self._deployment_instance_id,
            core_version=self._core_version,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
        )
        control = current_operation_control()
        operation_id = str(
            getattr(control, "effect_operation_id", "") or secrets.token_urlsafe(18)
        )
        try:
            permit = self._permits.issue(
                scope,
                operation_id=operation_id,
                idempotency_key=plan_id,
            )
        except UnresolvedExecutionError:
            return _failure(
                "execution_outcome_unknown",
                "A prior controller execution needs safety recovery before a new motion.",
            )
        except ValueError as exc:
            return _failure("automatic_motion_permit_rejected", str(exc))
        receipt = self._pending_plans.authorize(
            plan_id, permit_handle=permit.handle,
        )
        if receipt is None:
            self._permits.skip_unstarted(
                permit.handle, reason="automatic_motion_authorization_failed",
            )
            return _failure(
                "automatic_motion_authorization_failed",
                "Automatic motion authorization failed.",
            )

        # Keep the session's exact confirmed plan stable until the synchronous
        # execution engine has reserved its permit and completed dispatch.
        # This closes the plan-replacement TOCTOU with concurrent HTTP calls.
        with self._session_gates.hold_confirmed_plan(
            session_key, plan_id,
        ) as claimed:
            if not claimed:
                self._permits.skip_unstarted(
                    permit.handle, reason="automatic_motion_session_changed",
                )
                return _failure(
                    "automatic_motion_session_mismatch", "Motion session changed.",
                )
            result = self._motion.execute(RobotMotionExecutionCommand(
                principal=command.principal,
                plan_id=plan_id,
                confirmation_receipt=receipt,
            ))
        if result.ok and isinstance(result.payload, dict):
            if result.payload.get("ok") is not True:
                return _failure(
                    "execution_outcome_unknown",
                    "Motion outcome is unknown; wait for controller recovery and complete execution recovery before retrying.",
                )
            return RobotAutomaticMotionResponse(payload=result.payload)
        error = result.error
        code = getattr(error, "code", "automatic_motion_failed")
        if code in {
            "motion_outcome_unknown", "motion_dispatch_outcome_unknown", "motion_commit_failed",
        }:
            return _failure(
                "execution_outcome_unknown",
                "Motion outcome is unknown; wait for controller recovery and complete execution recovery before retrying.",
            )
        return _failure(
            code,
            getattr(error, "message", "Automatic motion did not complete."),
        )


def _failure(code: str, message: str) -> RobotAutomaticMotionResponse:
    return RobotAutomaticMotionResponse(
        error=RobotAutomaticMotionError(str(code), str(message)),
    )
