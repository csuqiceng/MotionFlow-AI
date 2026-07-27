"""Vendor-neutral backend assembly and lazy product operation adapters."""

from __future__ import annotations

from typing import Any

from robot_platform.application.operations import RobotOperationRequest
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.simulation_plugin import SimulationBackendPlugin
from robot_platform.models import ToolResult


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
) -> dict[str, Any]:
    """Run an operator request through the selected product backend."""
    resolved_config = config or RobotBackendConfig.from_env()
    if request.command == "system":
        # The selected backend owns safety actions.  This is intentionally
        # before the vendor-adapter fallback so a profile can never advertise
        # one backend for status and silently execute Func104 through another.
        from robot_platform.backends.product_wiring import create_product_robot_backend

        backend = create_product_robot_backend(resolved_config)
        execute_system_action = getattr(backend, "execute_system_action", None)
        if not callable(execute_system_action):
            return ToolResult.failure(
                state="system_action_unsupported",
                message="Selected backend does not implement system actions.",
                errors=[{"code": "system_action_unsupported"}],
            ).to_dict()
        return execute_system_action(request)

    if resolved_config.mode.strip().lower() in {"simulation", "sim"}:
        return _run_simulation_operator_command(request)

    return run_zmotion_operator_request(
        request=request,
        config=resolved_config,
        client_factory=client_factory,
        executor_factory=executor_factory,
    )


def run_zmotion_operator_request(
    *,
    request: RobotOperationRequest,
    config: Any = None,
    client_factory: Any = None,
    executor_factory: Any = None,
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
        ),
        config=resolved_config,
        client_factory=client_factory,
        executor_factory=executor_factory,
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


def default_auto_execution_confirmation() -> tuple[str, bool, bool]:
    """Return the current product's explicit auto-execution proof."""
    from robot_platform.backends.zmotion_adapter import REAL_EXECUTION_CONFIRMATION_CODE

    return REAL_EXECUTION_CONFIRMATION_CODE, True, True


def run_default_readonly_diagnostics(**kwargs: Any) -> dict[str, Any]:
    """Run the current product's controller diagnostics behind the wiring seam."""
    from robot_platform.backends.zmotion_readonly_diagnostics import run_zmotion_readonly_smoke

    return run_zmotion_readonly_smoke(**kwargs)
