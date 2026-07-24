"""Public, host-independent robot platform use cases.

AI tools, HTTP handlers and desktop code may parse their own input, but must
cross into controller code through this service.  The current implementation
adapts the existing ZMotion operator path; a future backend can replace that
adapter without changing those callers.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.flow import FlowRegistry, run_flow
from robot_platform.flow.aliases import FlowAlias
from robot_platform.models import ToolResult
from robot_platform.runtime import get_robot_data_dir
from robot_platform.tools.robot_tools import RobotToolFacade
from robot_platform.zmotion_operator_control import (
    REAL_EXECUTION_CONFIRMATION_CODE,
    ZMotionOperatorRequest,
    run_zmotion_operator_command,
)

OperatorRunner = Callable[..., dict[str, Any]]
FlowRunner = Callable[..., dict[str, Any]]


class RobotPlatform:
    """The public command boundary for the mechanical-arm platform."""

    def __init__(
        self,
        *,
        facade: RobotToolFacade | None = None,
        operator_runner: OperatorRunner = run_zmotion_operator_command,
        flow_runner: FlowRunner = run_flow,
        backend_config: RobotBackendConfig | None = None,
        flows_path: str | Path | None = None,
        flow_aliases_path: str | Path | None = None,
    ) -> None:
        data_dir = get_robot_data_dir()
        self._facade = facade or RobotToolFacade()
        self._operator_runner = operator_runner
        self._flow_runner = flow_runner
        self._backend_config = backend_config
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
        return self._facade.robot_get_status()

    def plan_motion(self, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Create and safety-check a dry-run plan; controller writes stay off."""
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
    ) -> dict[str, Any]:
        """Execute only when the caller carries an established confirmation proof.

        ``confirmation_code`` supports the explicit auto-execution path.  The
        Web/server path instead supplies a pending plan ID and backend-issued
        ``confirm_code``; the controller safety gate verifies both against its
        plan and session stores before any controller write.
        """
        has_confirmation = bool(confirmation_code) or bool(pending_plan_id and confirm_code)
        if not has_confirmation or not (confirm_work_area_clear and confirm_estop_ready):
            return ToolResult.failure(
                state="confirmation_required",
                message="Real execution requires confirmation code, clear work area and estop readiness.",
                errors=[{"code": "confirmation_required"}],
            ).to_dict()
        return self._run_operator(
            command,
            parameters,
            execute_real=True,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            pending_plan_id=pending_plan_id,
            confirm_code=confirm_code,
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
    ) -> dict[str, Any]:
        """Resolve a persisted flow and run every step through the safety gate."""
        resolved_name = str(name or "")
        if alias:
            resolved_name = FlowAlias(self._flow_aliases_path).resolve(alias) or ""
            if not resolved_name:
                return ToolResult.failure(
                    state="flow_alias_not_found",
                    message=f"Flow alias '{alias}' does not match any alias.",
                    errors=[{"code": "flow_alias_not_found", "flow_alias": alias}],
                ).to_dict()
        flow = FlowRegistry(self._flows_path).get(resolved_name)
        if flow is None:
            return ToolResult.failure(
                state="flow_not_found",
                message=f"Flow '{resolved_name}' does not exist.",
                errors=[{"code": "flow_not_found", "name": resolved_name}],
            ).to_dict()
        return self.run_flow_entry(
            flow,
            execute_real=execute_real,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
        )

    def run_flow_entry(
        self,
        flow: Any,
        *,
        execute_real: bool = False,
        confirmation_code: str = "",
        confirm_work_area_clear: bool = False,
        confirm_estop_ready: bool = False,
        on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
        before_step: Callable[[int], bool] | None = None,
    ) -> dict[str, Any]:
        """Run a resolved published flow through the same platform safety boundary."""
        if execute_real and (not confirmation_code or not confirm_work_area_clear or not confirm_estop_ready):
            return ToolResult.failure(
                state="confirmation_required",
                message="Real flow execution requires the established confirmation proof.",
                errors=[{"code": "confirmation_required"}],
            ).to_dict()
        return self._flow_runner(
            flow,
            config=self._backend_config,
            execute_real=execute_real,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            on_step=on_step,
            before_step=before_step,
        )

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
    ) -> dict[str, Any]:
        request = ZMotionOperatorRequest(
            command=command,
            parameters=dict(parameters),
            execute_real=execute_real,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            pending_plan_id=pending_plan_id,
            confirm_code=confirm_code,
        )
        kwargs: dict[str, Any] = {"request": request}
        if self._backend_config is not None:
            kwargs["config"] = self._backend_config
        return self._operator_runner(**kwargs)


def auto_execution_confirmation() -> tuple[str, bool, bool]:
    """Return the deliberate confirmation proof used only by configured auto mode."""
    return REAL_EXECUTION_CONFIRMATION_CODE, True, True
