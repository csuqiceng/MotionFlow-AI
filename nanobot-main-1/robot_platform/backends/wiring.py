"""Vendor-neutral backend assembly and lazy product operation adapters."""

from __future__ import annotations

from typing import Any

from robot_platform.application.operations import RobotOperationRequest
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.simulation_plugin import SimulationBackendPlugin
from robot_platform.models import ToolResult


_SIMULATION_SYSTEM_ACTIONS = frozenset({
    "emergency_stop",
    "release_emergency_stop",
    "pause",
    "resume",
    "alarm_reset",
    "release_cancel",
    "stop_current",
})


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
    if resolved_config.mode.strip().lower() in {"simulation", "sim"}:
        return _run_simulation_operator_command(request)

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
    """Acknowledge safe, controller-free system actions in simulation mode."""
    action = str(request.parameters.get("action", ""))
    if request.command != "system" or action not in _SIMULATION_SYSTEM_ACTIONS:
        return ToolResult.failure(
            state="simulation_operation_unsupported",
            message="Simulation supports only known system actions through this operator path.",
            errors=[{"code": "simulation_operation_unsupported", "command": request.command, "action": action}],
        ).to_dict()
    return ToolResult.success(
        state="simulated_system_action_completed",
        message=f"Simulated system action {action} completed.",
        data={"action": action, "simulation": True},
    ).to_dict()


def default_auto_execution_confirmation() -> tuple[str, bool, bool]:
    """Return the current product's explicit auto-execution proof."""
    from robot_platform.backends.zmotion_adapter import REAL_EXECUTION_CONFIRMATION_CODE

    return REAL_EXECUTION_CONFIRMATION_CODE, True, True


def run_default_readonly_diagnostics(**kwargs: Any) -> dict[str, Any]:
    """Run the current product's controller diagnostics behind the wiring seam."""
    from robot_platform.backends.zmotion_readonly_diagnostics import run_zmotion_readonly_smoke

    return run_zmotion_readonly_smoke(**kwargs)
