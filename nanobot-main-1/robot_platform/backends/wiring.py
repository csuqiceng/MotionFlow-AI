"""Vendor-neutral backend assembly and lazy product operation adapters."""

from __future__ import annotations

from typing import Any

from robot_platform.application.operations import RobotOperationRequest
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.simulation_plugin import SimulationBackendPlugin
from robot_platform.models import ToolResult
from robot_platform.execution.permit import ExecutionPermitVerifierPort
from robot_platform.execution.emergency_stop import EmergencyStopVerifierPort
from robot_platform.backends.lifecycle import BackendManager


def create_default_backend_registry() -> BackendRegistry:
    """Create the core registry with no product-vendor plugins attached."""
    registry = BackendRegistry()
    registry.register_plugin(SimulationBackendPlugin())
    return registry


def run_default_operator_command(
    *,
    request: RobotOperationRequest,
    config: Any = None,
    client_factory: Any = None,
    executor_factory: Any = None,
    permit_verifier: ExecutionPermitVerifierPort | None = None,
    emergency_stop_verifier: EmergencyStopVerifierPort | None = None,
) -> dict[str, Any]:
    """Fail closed: deployment dispatch requires the composed operation runner."""
    del request, config, client_factory, executor_factory
    del permit_verifier, emergency_stop_verifier
    return ToolResult.failure(
        state="backend_not_composed",
        message="Operator dispatch requires the composition-root Backend manager.",
        errors=[{"code": "backend_not_composed"}],
    ).to_dict()


def run_composed_operator_command(
    *,
    manager: BackendManager,
    request: RobotOperationRequest,
    config: Any,
    client_factory: Any = None,
    executor_factory: Any = None,
    permit_verifier: ExecutionPermitVerifierPort | None = None,
    emergency_stop_verifier: EmergencyStopVerifierPort | None = None,
    call_context: Any = None,
) -> dict[str, Any]:
    """Dispatch through the Backend selected by the composition root.

    Unlike the legacy fallback this function never discovers or constructs a
    second Backend.  Vendor operation adapters are selected from the frozen
    config attached to the already-started manager.
    """
    mode = str(config.mode).strip().casefold()
    if call_context is not None:
        call_context.check()
    if mode in {"simulation", "sim"}:
        if request.command == "system":
            return (
                manager.execute_system_action(request, context=call_context)
                if call_context is not None else manager.execute_system_action(request)
            )
        if request.command == "io":
            return (
                manager.execute_io(request, context=call_context)
                if call_context is not None else manager.execute_io(request)
            )
        return _run_simulation_operator_command(request)
    result = run_zmotion_operator_request(
        request=request,
        config=config,
        client_factory=client_factory,
        executor_factory=executor_factory,
        permit_verifier=permit_verifier,
        emergency_stop_verifier=emergency_stop_verifier,
    )
    if call_context is not None:
        call_context.check()
    return result


def _permit_allows(
    request: RobotOperationRequest,
    verifier: ExecutionPermitVerifierPort | None,
) -> bool:
    return bool(
        verifier is not None
        and request.execution_permit_handle
        and request.execution_scope is not None
        and request.execution_dispatch_id
        and verifier.claim_dispatch(
            request.execution_permit_handle,
            request.execution_scope,
            dispatch_id=request.execution_dispatch_id,
            operation_type=request.command,
            payload={"command": request.command, "parameters": request.parameters},
        )
    )


def run_zmotion_operator_request(
    *,
    request: RobotOperationRequest,
    config: Any = None,
    client_factory: Any = None,
    executor_factory: Any = None,
    permit_verifier: ExecutionPermitVerifierPort | None = None,
    emergency_stop_verifier: EmergencyStopVerifierPort | None = None,
) -> dict[str, Any]:
    """Translate a neutral request only inside the selected ZMotion backend."""
    resolved_config = config or RobotBackendConfig.from_env()

    from robot_platform.backends.zmotion_adapter import (
        ZMotionOperatorRequest,
        run_zmotion_operator_command,
    )

    return run_zmotion_operator_command(
        request=ZMotionOperatorRequest(
            command=request.command,
            parameters=dict(request.parameters),
            execute_real=request.execute_real,
            confirm_work_area_clear=request.confirm_work_area_clear,
            confirm_estop_ready=request.confirm_estop_ready,
            confirmation_code=request.confirmation_code,
            pending_plan_id=request.pending_plan_id,
            confirm_code=request.confirm_code,
            execution_permit_handle=request.execution_permit_handle,
            execution_scope=request.execution_scope,
            execution_operation_type=request.execution_operation_type,
            execution_payload=request.execution_payload,
            execution_dispatch_id=request.execution_dispatch_id,
            emergency_stop_token=request.emergency_stop_token,
        ),
        config=resolved_config,
        client_factory=client_factory,
        executor_factory=executor_factory,
        permit_verifier=permit_verifier,
        emergency_stop_verifier=emergency_stop_verifier,
    )


def _run_simulation_operator_command(request: RobotOperationRequest) -> dict[str, Any]:
    """Simulation exposes system actions through its backend port only."""
    return ToolResult.failure(
        state="simulation_operation_unsupported",
        message="Simulation supports only system actions through this operator path.",
        errors=[{
            "code": "simulation_operation_unsupported",
            "command": request.command,
        }],
    ).to_dict()


def run_default_readonly_diagnostics(**kwargs: Any) -> dict[str, Any]:
    """Run the current product's controller diagnostics behind the wiring seam."""
    from robot_platform.backends.zmotion_readonly_diagnostics import run_zmotion_readonly_smoke

    return run_zmotion_readonly_smoke(**kwargs)
