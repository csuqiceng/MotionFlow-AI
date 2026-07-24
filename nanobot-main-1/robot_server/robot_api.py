"""Standard JSON robot API backed only by public RobotPlatform use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from robot_platform import PendingPlanStore, RobotPlatform, SessionGateStore, issue_confirm_code
from robot_platform.execution.confirm_code import verify_confirm_code
from robot_platform.platform import auto_execution_confirmation


@dataclass
class RobotOperationService:
    """Own the HTTP-facing pending-plan lifecycle without a gateway dependency."""

    platform: RobotPlatform
    pending_plans: PendingPlanStore
    session_gates: SessionGateStore

    def plan(self, body: Any) -> tuple[int, dict[str, Any]]:
        parsed = _command_body(body)
        if isinstance(parsed[0], int):
            return parsed
        session_key, command, parameters = parsed
        result = self.platform.plan_motion(command, parameters)
        if not result.get("ok"):
            return 200, result
        plan = self.pending_plans.create(
            command=command, parameters=parameters, dry_run_result=result
        )
        self.session_gates.set_pending_plan(session_key, plan.plan_id)
        return 201, {
            "plan_id": plan.plan_id,
            "plan": result,
            "param_hash": plan.param_hash,
            "expires_at": plan.expires_at,
        }

    def confirm(self, plan_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        parsed = _confirmation_body(body)
        if isinstance(parsed[0], int):
            return parsed
        session_key, work_area_clear, estop_ready = parsed
        if not work_area_clear or not estop_ready:
            return _error(400, "both safety confirmations must be true")
        plan = self.pending_plans.get(plan_id)
        if plan is None:
            return _error(404, "pending plan not found or expired")
        if not self.session_gates.confirm(session_key, plan_id):
            return _error(409, "session has no matching pending plan")
        if not self.pending_plans.confirm(plan_id):
            return _error(409, "pending plan cannot be confirmed")
        return 200, {"confirm_code": issue_confirm_code(plan_id)}

    def execute(self, plan_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            return _error(400, "request body must be a JSON object")
        session_key = _session_key(body)
        confirm_code = body.get("confirm_code")
        if not isinstance(confirm_code, str) or not confirm_code:
            return _error(400, "confirm_code is required")
        plan = self.pending_plans.get(plan_id)
        if plan is None:
            return _error(404, "pending plan not found or expired")
        # Do not accept command/parameters from execute: only the immutable
        # dry-run plan may be executed.
        result = self.platform.execute_confirmed_plan(
            plan.command,
            plan.parameters,
            confirmation_code="",
            confirm_work_area_clear=True,
            confirm_estop_ready=True,
            pending_plan_id=plan_id,
            confirm_code=confirm_code,
        )
        return 200, result

    def emergency_stop(self, body: Any) -> tuple[int, dict[str, Any]]:
        parsed = _confirmation_body(body)
        if isinstance(parsed[0], int):
            return parsed
        _session, work_area_clear, estop_ready = parsed
        confirmation_code = body.get("confirmation_code") if isinstance(body, dict) else None
        if not isinstance(confirmation_code, str) or not confirmation_code:
            return _error(400, "confirmation_code is required")
        return 200, self.platform.emergency_stop(
            confirmation_code=confirmation_code,
            confirm_work_area_clear=work_area_clear,
            confirm_estop_ready=estop_ready,
        )

    def plan_flow(self, body: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            return _error(400, "request body must be a JSON object")
        name = body.get("flow_name", body.get("name"))
        alias = body.get("alias")
        if not isinstance(name, str) or not name.strip():
            return _error(400, "flow_name is required")
        if alias is not None and not isinstance(alias, str):
            return _error(400, "alias must be a string")
        parameters = {"name": name.strip(), "alias": alias.strip() if isinstance(alias, str) and alias.strip() else None}
        dry_run_result = self.platform.run_flow(parameters["name"], alias=parameters["alias"], execute_real=False)
        if not dry_run_result.get("ok"):
            return 200, dry_run_result
        plan = self.pending_plans.create(command="flow_run", parameters=parameters, dry_run_result=dry_run_result)
        self.session_gates.set_pending_plan(_session_key(body), plan.plan_id)
        return 201, {"plan_id": plan.plan_id, "flow_name": parameters["name"],
                     "dry_run_result": dry_run_result, "param_hash": plan.param_hash,
                     "expires_at": plan.expires_at}

    def execute_flow(self, plan_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            return _error(400, "request body must be a JSON object")
        session_key = _session_key(body); confirm_code = body.get("confirm_code")
        if not isinstance(confirm_code, str) or not confirm_code:
            return _error(400, "confirm_code is required")
        plan = self.pending_plans.get(plan_id)
        if plan is None or plan.command != "flow_run":
            return _error(404, "pending flow plan not found or expired")
        if not self.session_gates.is_confirmed(session_key, plan_id):
            return _error(409, "session has no matching confirmed flow plan")
        if not verify_confirm_code(plan_id, confirm_code) or not self.pending_plans.verify(plan_id, plan.parameters):
            return _error(409, "flow confirmation proof is invalid or expired")
        # The browser never receives the controller's internal execution
        # credential.  It is created only after the immutable plan, matching
        # session gate and server-issued confirmation proof have all verified.
        internal_code, clear, estop_ready = auto_execution_confirmation()
        result = self.platform.run_flow(
            str(plan.parameters["name"]), alias=plan.parameters.get("alias"), execute_real=True,
            confirmation_code=internal_code, confirm_work_area_clear=clear, confirm_estop_ready=estop_ready,
        )
        return 200, result

    def run_flow(self, body: Any) -> tuple[int, dict[str, Any]]:
        """Compatibility dry-run endpoint.

        Real flow execution must use plan_flow -> confirm -> execute_flow so
        a browser cannot bypass the immutable-plan and server-proof gates.
        """
        if not isinstance(body, dict):
            return _error(400, "request body must be a JSON object")
        name = body.get("name")
        alias = body.get("alias")
        execute_real = bool(body.get("execute_real"))
        if not isinstance(name, str) or not name:
            return _error(400, "name is required")
        if alias is not None and not isinstance(alias, str):
            return _error(400, "alias must be a string")
        if execute_real:
            return _error(409, "real flow execution requires the staged flow plan endpoints")
        return 200, self.platform.run_flow(
            name,
            alias=alias,
            execute_real=False,
        )


def _command_body(body: Any) -> tuple[str, str, dict[str, Any]] | tuple[int, dict[str, Any]]:
    if not isinstance(body, dict):
        return _error(400, "request body must be a JSON object")
    command = body.get("command")
    parameters = body.get("parameters")
    if not isinstance(command, str) or not command:
        return _error(400, "command is required")
    if not isinstance(parameters, dict):
        return _error(400, "parameters must be an object")
    return _session_key(body), command, parameters


def _confirmation_body(body: Any) -> tuple[str, bool, bool] | tuple[int, dict[str, Any]]:
    if not isinstance(body, dict):
        return _error(400, "request body must be a JSON object")
    return (
        _session_key(body),
        bool(body.get("confirm_work_area_clear")),
        bool(body.get("confirm_estop_ready")),
    )


def _session_key(body: dict[str, Any]) -> str:
    value = body.get("session_id")
    if not isinstance(value, str) or not value.strip():
        return "robot-server:default"
    return f"robot-server:{value.strip()[:128]}"


def _error(status: int, message: str) -> tuple[int, dict[str, Any]]:
    return status, {"error": {"code": status, "message": message}}
