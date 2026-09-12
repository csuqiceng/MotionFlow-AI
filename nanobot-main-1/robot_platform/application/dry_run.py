"""Unified command and Flow dry-run planning use cases."""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from robot_platform.io_policy import (
    normalize_io_output_channels,
    valid_io_channel,
)

from .principal import AuthenticatedPrincipal

if TYPE_CHECKING:
    from robot_platform.flow import FlowEntry, FlowExecutionSnapshot


@dataclass(frozen=True)
class RobotDryRunError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("RobotDryRunError requires code and message")


@dataclass(frozen=True)
class RobotDryRunResponse:
    payload: dict[str, Any] | None = None
    error: RobotDryRunError | None = None
    staged: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotDryRunResponse requires exactly one of payload or error")
        if self.payload is not None and not isinstance(self.payload, dict):
            raise TypeError("RobotDryRunResponse payload must be a dict")
        if self.error is not None and self.staged:
            raise ValueError("failed dry-run response cannot be staged")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotDryRunPlatformPort(Protocol):
    def plan_motion(self, command: str, parameters: dict[str, Any]) -> dict[str, Any]: ...
    def resolve_flow(self, name: str, *, alias: str | None = None) -> FlowEntry | None: ...
    def run_flow_entry(self, flow: Any, *, execute_real: bool = False, **kwargs: Any) -> dict[str, Any]: ...
    def run_flow(self, name: str, *, alias: str | None = None, execute_real: bool = False, **kwargs: Any) -> dict[str, Any]: ...


class PendingPlanPort(Protocol):
    def create(
        self, *, command: str, parameters: dict[str, Any], dry_run_result: dict[str, Any],
    ) -> Any: ...
    def discard(self, plan_id: str) -> bool: ...


class SessionGatePort(Protocol):
    def set_pending_plan(self, session_key: str | None, plan_id: str) -> None: ...
    def clear_pending_plan(self, session_key: str | None, plan_id: str) -> bool: ...
    def snapshot(self, session_key: str | None) -> Any: ...
    def restore_if_current(
        self, session_key: str | None, failed_plan_id: str, previous: Any,
    ) -> bool: ...


class RobotDryRunApplicationPort(Protocol):
    def preview_command(self, command: str, parameters: dict[str, Any]) -> RobotDryRunResponse: ...
    def preview_flow_entry(
        self,
        flow: FlowEntry | FlowExecutionSnapshot,
        *,
        on_step: Any = None,
        before_step: Any = None,
    ) -> RobotDryRunResponse: ...
    def stage_flow_entry(
        self,
        principal: AuthenticatedPrincipal,
        flow: FlowEntry,
        *,
        selection_name: str,
        alias: str | None = None,
        execution_inputs: dict[str, Any] | None = None,
    ) -> RobotDryRunResponse: ...


class RobotDryRunApplicationService:
    def __init__(
        self,
        platform: RobotDryRunPlatformPort,
        pending_plans: PendingPlanPort | None,
        session_gates: SessionGatePort | None,
        *,
        product_profile_version: str,
        capability_version: str,
        core_version: str,
        allowed_io_output_channels: Collection[int] | None = None,
    ) -> None:
        self._platform = platform
        self._pending_plans = pending_plans
        self._session_gates = session_gates
        self._product_profile_version = product_profile_version
        self._capability_version = capability_version
        self._core_version = core_version
        configured_io = allowed_io_output_channels
        if configured_io is None:
            candidate = getattr(platform, "allowed_io_output_channels", ())
            configured_io = candidate if isinstance(
                candidate, Collection,
            ) and not isinstance(candidate, (str, bytes, dict)) else ()
        self._allowed_io_output_channels = normalize_io_output_channels(
            configured_io
        )

    def preview_command(
        self, command: str, parameters: dict[str, Any],
    ) -> RobotDryRunResponse:
        if not isinstance(command, str) or not command:
            return _failure("invalid_request", "command is required")
        if not isinstance(parameters, dict):
            return _failure("invalid_request", "parameters must be an object")
        try:
            frozen_parameters = self._freeze_command_parameters(command, parameters)
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        except Exception:
            return _failure("dry_run_unavailable", "Robot dry-run is unavailable.")
        return self._preview_command_snapshot(command, frozen_parameters)

    def _preview_command_snapshot(
        self, command: str, frozen_parameters: dict[str, Any],
    ) -> RobotDryRunResponse:
        try:
            result = self._platform.plan_motion(
                command, deepcopy(frozen_parameters),
            )
            return RobotDryRunResponse(payload=deepcopy(result))
        except Exception:
            return _failure("dry_run_unavailable", "Robot dry-run is unavailable.")

    def stage_command(
        self,
        principal: AuthenticatedPrincipal,
        command: str,
        parameters: dict[str, Any],
    ) -> RobotDryRunResponse:
        if not isinstance(principal, AuthenticatedPrincipal):
            return _failure("invalid_principal", "Authenticated principal required.")
        if not isinstance(command, str) or not command:
            return _failure("invalid_request", "command is required")
        if not isinstance(parameters, dict):
            return _failure("invalid_request", "parameters must be an object")
        try:
            frozen_parameters = self._freeze_command_parameters(command, parameters)
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        except Exception:
            return _failure("dry_run_unavailable", "Robot dry-run is unavailable.")
        preview = self._preview_command_snapshot(command, frozen_parameters)
        if not preview.ok or preview.payload.get("ok") is not True:
            return preview
        if self._pending_plans is None or self._session_gates is None:
            return _failure("planning_state_unavailable", "Pending plan store is unavailable.")
        plan = None
        session_key = _session_key(principal)
        try:
            previous_session = self._session_gates.snapshot(session_key)
            plan = self._pending_plans.create(
                command=command,
                parameters=deepcopy(frozen_parameters),
                dry_run_result=preview.payload,
            )
            self._session_gates.set_pending_plan(session_key, plan.plan_id)
            return RobotDryRunResponse(payload={
                "plan_id": plan.plan_id,
                "plan": deepcopy(preview.payload),
                "param_hash": plan.param_hash,
                "expires_at": plan.expires_at,
            }, staged=True)
        except Exception:
            if plan is not None:
                _rollback_stage(
                    self._pending_plans, self._session_gates,
                    session_key, plan.plan_id, previous_session,
                )
            return _failure("planning_state_unavailable", "Pending plan could not be stored.")

    def preview_flow_entry(
        self,
        flow: FlowEntry | FlowExecutionSnapshot,
        *,
        on_step: Any = None,
        before_step: Any = None,
    ) -> RobotDryRunResponse:
        try:
            result = self._platform.run_flow_entry(
                deepcopy(flow), execute_real=False, on_step=on_step,
                before_step=before_step,
                # Preview simulates approval traversal only. Real execution
                # receives a one-use server-owned approval receipt.
                approval_checker=lambda _node: True,
            )
            return RobotDryRunResponse(payload=deepcopy(result))
        except Exception:
            return _failure("dry_run_unavailable", "Robot dry-run is unavailable.")

    def stage_flow(
        self,
        principal: AuthenticatedPrincipal,
        name: str,
        *,
        alias: str | None = None,
    ) -> RobotDryRunResponse:
        if not isinstance(principal, AuthenticatedPrincipal):
            return _failure("invalid_principal", "Authenticated principal required.")
        from robot_platform.flow import FlowEntry

        try:
            resolved = self._platform.resolve_flow(name, alias=alias)
        except Exception:
            return _failure("dry_run_unavailable", "Robot dry-run is unavailable.")
        if not isinstance(resolved, FlowEntry):
            return _failure("not_found", "published flow or alias not found")
        return self.stage_flow_entry(
            principal, resolved, selection_name=name, alias=alias,
        )

    def stage_flow_entry(
        self,
        principal: AuthenticatedPrincipal,
        flow: FlowEntry,
        *,
        selection_name: str,
        alias: str | None = None,
        execution_inputs: dict[str, Any] | None = None,
    ) -> RobotDryRunResponse:
        if not isinstance(principal, AuthenticatedPrincipal):
            return _failure("invalid_principal", "Authenticated principal required.")
        from robot_platform.flow import FlowEntry, FlowExecutionSnapshot

        if not isinstance(flow, FlowEntry):
            return _failure("not_found", "published flow or alias not found")
        try:
            snapshot = FlowExecutionSnapshot.create(
                deepcopy(flow),
                product_profile_version=self._product_profile_version,
                capability_version=self._capability_version,
                core_version=self._core_version,
                resolved_alias=alias or "",
                execution_inputs=execution_inputs,
            )
        except ValueError:
            return _failure("conflict", "Flow snapshot is invalid.")
        except Exception:
            return _failure("dry_run_unavailable", "Robot dry-run is unavailable.")
        preview = self.preview_flow_entry(snapshot)
        if not preview.ok or preview.payload.get("ok") is not True:
            return preview
        if self._pending_plans is None or self._session_gates is None:
            return _failure("planning_state_unavailable", "Pending plan store is unavailable.")
        parameters = {
            "selection": {"name": selection_name, "alias": alias},
            "snapshot": snapshot.to_dict(),
        }
        plan = None
        session_key = _session_key(principal)
        try:
            previous_session = self._session_gates.snapshot(session_key)
            plan = self._pending_plans.create(
                command="flow_run", parameters=parameters,
                dry_run_result=preview.payload,
            )
            self._session_gates.set_pending_plan(session_key, plan.plan_id)
            return RobotDryRunResponse(payload={
                "plan_id": plan.plan_id,
                "flow_name": snapshot.flow_name,
                "flow_id": snapshot.flow_id,
                "flow_version": snapshot.published_version,
                "content_hash": snapshot.content_hash,
                "dry_run_result": deepcopy(preview.payload),
                "param_hash": plan.param_hash,
                "expires_at": plan.expires_at,
            }, staged=True)
        except Exception:
            if plan is not None:
                _rollback_stage(
                    self._pending_plans, self._session_gates,
                    session_key, plan.plan_id, previous_session,
                )
            return _failure("planning_state_unavailable", "Pending plan could not be stored.")

    def _freeze_command_parameters(
        self, command: str, parameters: dict[str, Any],
    ) -> dict[str, Any]:
        frozen = deepcopy(parameters)
        if command != "io":
            return frozen
        if set(frozen) != {"io_number", "enabled"}:
            raise ValueError(
                "IO parameters accept only io_number and enabled; channel policy is server-owned."
            )
        io_number = frozen.get("io_number")
        enabled = frozen.get("enabled")
        if not valid_io_channel(io_number) or not isinstance(enabled, bool):
            raise ValueError("IO channel and enabled value are invalid.")
        if io_number not in self._allowed_io_output_channels:
            raise ValueError("IO channel is not allowed by the product profile.")
        return {
            "io_number": io_number,
            "enabled": enabled,
            "allowed_io_channels": list(self._allowed_io_output_channels),
        }


def _session_key(principal: AuthenticatedPrincipal) -> str:
    return f"robot-server:{principal.session_id}"


def _failure(code: str, message: str) -> RobotDryRunResponse:
    return RobotDryRunResponse(error=RobotDryRunError(code=code, message=message))


def _rollback_stage(
    plans: PendingPlanPort,
    sessions: SessionGatePort,
    session_key: str,
    plan_id: str,
    previous_session: Any,
) -> None:
    try:
        sessions.restore_if_current(session_key, plan_id, previous_session)
    except Exception:
        pass
    try:
        plans.discard(plan_id)
    except Exception:
        pass
