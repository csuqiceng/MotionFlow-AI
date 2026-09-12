"""Public, host-independent robot platform use cases.

AI tools, HTTP handlers and desktop code may parse their own input, but must
cross into controller code through this service. Product wiring supplies the
operation adapter, so a different backend can replace it without changing
these callers.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Collection
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from robot_platform.application.operations import RobotOperationRequest
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.lifecycle import BackendCallContext
from robot_platform.execution.permit import (
    ExecutionPermitVerifierPort,
    ExecutionScope,
    FlowStepExecutionGrant,
)
from robot_platform.flow import FlowEntry, FlowRegistry, run_flow
from robot_platform.flow.aliases import FlowAlias
from robot_platform.io_policy import (
    normalize_io_output_channels,
    valid_io_channel,
)
from robot_platform.models import ToolResult
from robot_platform.feature_policy import ProductFeaturePolicy
from robot_platform.runtime import get_robot_data_dir
from robot_platform.tools.robot_tools import RobotToolFacade

OperatorRunner = Callable[..., dict[str, Any]]
FlowRunner = Callable[..., dict[str, Any]]


class _UnavailableRobotFacade:
    """Fail-closed placeholder for isolated domain/unit use without composition."""

    @property
    def controller_capabilities(self) -> dict[str, object]:
        return {}

    def robot_get_status(self) -> dict[str, Any]:
        return ToolResult.failure(
            state="robot_backend_not_composed",
            message="Robot Backend was not injected by the composition root.",
            errors=[{"code": "robot_backend_not_composed"}],
        ).to_dict()

    def close(self) -> None:
        return None


class RobotPlatform:
    """The public command boundary for the mechanical-arm platform."""

    def __init__(
        self,
        *,
        facade: RobotToolFacade | None = None,
        operator_runner: OperatorRunner | None = None,
        flow_runner: FlowRunner = run_flow,
        backend_config: RobotBackendConfig | None = None,
        flows_path: str | Path | None = None,
        flow_aliases_path: str | Path | None = None,
        allowed_io_output_channels: Collection[int] | None = None,
        feature_policy: ProductFeaturePolicy | None = None,
    ) -> None:
        data_dir = get_robot_data_dir()
        self._facade = facade or _UnavailableRobotFacade()
        self._feature_policy = feature_policy or ProductFeaturePolicy()
        self._has_injected_operator_runner = operator_runner is not None
        self._operator_runner = operator_runner or _unavailable_operator_runner
        self._pass_backend_config = operator_runner is None or backend_config is not None
        self._flow_runner = flow_runner
        resolved_backend_config = backend_config or RobotBackendConfig.from_env()
        configured_io_channels = (
            resolved_backend_config.allowed_io_output_channels
            if allowed_io_output_channels is None
            else allowed_io_output_channels
        )
        self._allowed_io_output_channels = normalize_io_output_channels(
            configured_io_channels
        )
        self._backend_config = replace(
            resolved_backend_config,
            allowed_io_output_channels=self._allowed_io_output_channels,
        )
        self._flows_path = Path(
            flows_path or os.environ.get("ROBOT_AI_FLOWS_PATH") or data_dir / "flows.json"
        )
        self._flow_aliases_path = Path(
            flow_aliases_path
            or os.environ.get("ROBOT_AI_FLOW_ALIASES_PATH")
            or data_dir / "flow_aliases.json"
        )

    def get_status(self) -> dict[str, Any]:
        """Read controller state. This never writes to a controller."""
        self._feature_policy.require("robot_arm")
        return self._facade.robot_get_status()

    def execution_context(self) -> dict[str, str]:
        """Return the frozen backend identity used for plan/execute scoping."""
        config = self._backend_config
        canonical = f"{config.mode.strip().lower()}|{config.controller_host.strip()}"
        return {
            "backend_mode": config.mode.strip().lower(),
            "controller_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    @property
    def backend_config(self) -> RobotBackendConfig:
        """The one frozen Backend selection shared by all application ports."""
        return self._backend_config

    @property
    def feature_policy(self) -> ProductFeaturePolicy:
        return self._feature_policy

    @property
    def controller_capabilities(self) -> dict[str, object]:
        """Return the frozen vendor-neutral capabilities used by Tool policy."""
        return self._facade.controller_capabilities

    @property
    def allowed_io_output_channels(self) -> tuple[int, ...]:
        """Frozen deployment policy; request payloads cannot extend it."""
        return self._allowed_io_output_channels

    def close(self) -> None:
        """Release the Backend held by this platform's facade."""
        self._facade.close()

    def plan_motion(self, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Create and safety-check a dry-run plan; controller writes stay off."""
        self._feature_policy.require("robot_arm")
        if command == "io":
            trusted = self._trusted_io_parameters(parameters)
            if trusted is None:
                return _io_policy_rejected()
            parameters = trusted
        return self._run_operator(command, parameters, execute_real=False)

    def execute_confirmed_plan(
        self,
        command: str,
        parameters: dict[str, Any],
        *,
        confirm_work_area_clear: bool,
        confirm_estop_ready: bool,
        confirmation_code: str = "",
        pending_plan_id: str = "",
        confirm_code: str = "",
        execution_permit_handle: str = "",
        execution_scope: ExecutionScope | None = None,
        permit_verifier: ExecutionPermitVerifierPort | None = None,
        execution_operation_type: str = "",
        execution_payload: dict[str, Any] | None = None,
        execution_dispatch_id: str = "",
    ) -> dict[str, Any]:
        """Execute only when the caller carries an established confirmation proof.

        ``confirmation_code`` supports the explicit auto-execution path.  The
        Web/server path instead supplies a pending plan ID and backend-issued
        ``confirm_code``; the controller safety gate verifies both against its
        plan and session stores before any controller write.
        """
        self._feature_policy.require("robot_arm")
        has_confirmation = bool(
            execution_permit_handle
            and execution_scope is not None
            and permit_verifier is not None
            and execution_operation_type
            and execution_payload is not None
            and execution_dispatch_id
        )
        if not has_confirmation or not (confirm_work_area_clear and confirm_estop_ready):
            return ToolResult.failure(
                state="confirmation_required",
                message="Real execution requires confirmation code, clear work area and estop readiness.",
                errors=[{"code": "confirmation_required"}],
            ).to_dict()
        if command == "io":
            trusted = self._trusted_io_parameters(parameters)
            if trusted is None:
                return _io_policy_rejected()
            parameters = trusted
        return self._run_operator(
            command,
            parameters,
            execute_real=True,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            pending_plan_id=pending_plan_id,
            confirm_code=confirm_code,
            execution_permit_handle=execution_permit_handle,
            execution_scope=execution_scope,
            permit_verifier=permit_verifier,
            execution_operation_type=execution_operation_type,
            execution_payload=execution_payload,
            execution_dispatch_id=execution_dispatch_id,
        )

    def emergency_stop(
        self,
        *,
        confirmation_code: str,
        confirm_work_area_clear: bool,
        confirm_estop_ready: bool,
    ) -> dict[str, Any]:
        """Platform-level emergency-stop use case; backend owns device details."""
        return self.execute_confirmed_plan(
            "system",
            {"action": "emergency_stop"},
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
        )

    def run_flow(
        self,
        name: str,
        *,
        alias: str | None = None,
        execute_real: bool = False,
        confirmation_code: str = "",
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        execution_permit_handle: str = "",
        execution_scope: ExecutionScope | None = None,
        permit_verifier: ExecutionPermitVerifierPort | None = None,
        execution_operation_type: str = "",
        execution_payload: dict[str, Any] | None = None,
        execution_dispatch_id: str = "",
        flow_step_grants: tuple[FlowStepExecutionGrant, ...] = (),
    ) -> dict[str, Any]:
        """Resolve a persisted flow and run every step through the safety gate."""
        self._feature_policy.require("robot_flow")
        flow = self.resolve_flow(name, alias=alias)
        if flow is None:
            if alias and not FlowAlias(self._flow_aliases_path).resolve(alias):
                return ToolResult.failure(
                    state="flow_alias_not_found",
                    message=f"Flow alias '{alias}' does not match any alias.",
                    errors=[{"code": "flow_alias_not_found", "flow_alias": alias}],
                ).to_dict()
            return ToolResult.failure(
                state="flow_not_found",
                message=f"Flow '{name}' does not exist.",
                errors=[{"code": "flow_not_found", "name": name}],
            ).to_dict()
        return self.run_flow_entry(
            flow,
            execute_real=execute_real,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            execution_permit_handle=execution_permit_handle,
            execution_scope=execution_scope,
            permit_verifier=permit_verifier,
            execution_operation_type=execution_operation_type,
            execution_payload=execution_payload,
            execution_dispatch_id=execution_dispatch_id,
            flow_step_grants=flow_step_grants,
        )

    def resolve_flow(self, name: str, *, alias: str | None = None) -> FlowEntry | None:
        """Resolve a published Flow once so planning can freeze its exact content."""
        self._feature_policy.require("robot_flow")
        resolved_name = str(name or "")
        if alias:
            resolved_name = FlowAlias(self._flow_aliases_path).resolve(alias) or ""
        if not resolved_name:
            return None
        return FlowRegistry(self._flows_path).get(resolved_name)

    def run_flow_entry(
        self,
        flow: Any,
        *,
        execute_real: bool = False,
        confirmation_code: str = "",
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        execution_permit_handle: str = "",
        execution_scope: ExecutionScope | None = None,
        permit_verifier: ExecutionPermitVerifierPort | None = None,
        execution_operation_type: str = "",
        execution_payload: dict[str, Any] | None = None,
        execution_dispatch_id: str = "",
        flow_step_grants: tuple[FlowStepExecutionGrant, ...] = (),
        on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
        before_step: Callable[[int], bool] | None = None,
        execution_id: str = "",
        on_event: Callable[[Any], None] | None = None,
        approval_checker: Callable[[Any], bool] | None = None,
    ) -> dict[str, Any]:
        self._feature_policy.require("robot_flow")
        if execute_real:
            self._feature_policy.require("robot_arm")
        """Run a resolved published flow through the same platform safety boundary."""
        if execute_real and (
            permit_verifier is None
            or not flow_step_grants
            or not confirm_work_area_clear
            or not confirm_estop_ready
        ):
            return ToolResult.failure(
                state="confirmation_required",
                message="Real flow execution requires the established confirmation proof.",
                errors=[{"code": "confirmation_required"}],
            ).to_dict()
        runner_kwargs: dict[str, Any] = dict(
            config=self._backend_config,
            execute_real=execute_real,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            execution_permit_handle=execution_permit_handle,
            execution_scope=execution_scope,
            permit_verifier=permit_verifier,
            execution_operation_type=execution_operation_type,
            execution_payload=execution_payload,
            execution_dispatch_id=execution_dispatch_id,
            flow_step_grants=flow_step_grants,
            on_step=on_step,
            before_step=before_step,
            allowed_io_output_channels=self._allowed_io_output_channels,
        )
        # Dry-run keeps the executor's injectable preview runner.  A real run
        # is always routed back through this Platform's single operation
        # boundary so no second composition root can dispatch hardware work.
        if execute_real or self._has_injected_operator_runner:
            runner_kwargs["operator_runner"] = self._run_flow_operator
        if on_event is not None:
            runner_kwargs["execution_id"] = execution_id or "flow-execution"
            runner_kwargs["on_event"] = on_event
        if approval_checker is not None:
            runner_kwargs["approval_checker"] = approval_checker
        return self._flow_runner(flow, **runner_kwargs)

    def _run_flow_operator(
        self, *, request: RobotOperationRequest,
        permit_verifier: ExecutionPermitVerifierPort | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Adapt the Flow executor request back into the single operation boundary."""
        return self._run_operator(
            request.command,
            dict(request.parameters),
            execute_real=request.execute_real,
            confirmation_code=request.confirmation_code,
            confirm_work_area_clear=request.confirm_work_area_clear,
            confirm_estop_ready=request.confirm_estop_ready,
            execution_permit_handle=request.execution_permit_handle,
            execution_scope=request.execution_scope,
            permit_verifier=permit_verifier,
            execution_operation_type=request.execution_operation_type,
            execution_payload=request.execution_payload,
            execution_dispatch_id=request.execution_dispatch_id,
        )

    def _trusted_io_parameters(
        self, parameters: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(parameters, dict):
            return None
        io_number = parameters.get("io_number")
        enabled = parameters.get("enabled")
        if (
            not valid_io_channel(io_number)
            or not isinstance(enabled, bool)
            or io_number not in self._allowed_io_output_channels
        ):
            return None
        try:
            canonical = deepcopy(parameters)
        except Exception:
            return None
        canonical["io_number"] = io_number
        canonical["enabled"] = enabled
        canonical["allowed_io_channels"] = list(
            self._allowed_io_output_channels
        )
        return canonical

    def _run_operator(
        self,
        command: str,
        parameters: dict[str, Any],
        *,
        execute_real: bool,
        confirmation_code: str = "",
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        pending_plan_id: str = "",
        confirm_code: str = "",
        execution_permit_handle: str = "",
        execution_scope: ExecutionScope | None = None,
        permit_verifier: ExecutionPermitVerifierPort | None = None,
        execution_operation_type: str = "",
        execution_payload: dict[str, Any] | None = None,
        execution_dispatch_id: str = "",
    ) -> dict[str, Any]:
        if command == "system" and parameters.get("action") == "emergency_stop":
            return ToolResult.failure(
                state="dedicated_emergency_stop_required",
                message="Use the dedicated emergency-stop application.",
                errors=[{"code": "dedicated_emergency_stop_required"}],
            ).to_dict()
        request = RobotOperationRequest(
            command=command,
            parameters=dict(parameters),
            execute_real=execute_real,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            pending_plan_id=pending_plan_id,
            confirm_code=confirm_code,
            execution_permit_handle=execution_permit_handle,
            execution_scope=execution_scope,
            execution_operation_type=execution_operation_type,
            execution_payload=execution_payload,
            execution_dispatch_id=execution_dispatch_id,
        )
        kwargs: dict[str, Any] = {"request": request}
        call_context = BackendCallContext.from_current_operation()
        if call_context is not None:
            kwargs["call_context"] = call_context
        if self._pass_backend_config:
            kwargs["config"] = self._backend_config
        if permit_verifier is not None:
            kwargs["permit_verifier"] = permit_verifier
        return self._operator_runner(**kwargs)


def _unavailable_operator_runner(**kwargs: Any) -> dict[str, Any]:
    del kwargs
    return ToolResult.failure(
        state="robot_operation_not_composed",
        message="Robot operation adapter was not injected by the composition root.",
        errors=[{"code": "robot_operation_not_composed"}],
    ).to_dict()


def _io_policy_rejected() -> dict[str, Any]:
    return ToolResult.failure(
        state="io_channel_not_allowed",
        message="IO channel is not allowed by the frozen product profile.",
        errors=[{"code": "io_channel_not_allowed"}],
    ).to_dict()
