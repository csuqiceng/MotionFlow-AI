from __future__ import annotations

import json
import os
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from robot_ai.flow import FlowEntry, FlowRegistry, FlowStep, run_flow
from robot_ai.models import ToolResult


_DEFAULT_FLOWS_PATH = os.environ.get(
    "ROBOT_AI_FLOWS_PATH",
    # Default outside the repo (next to ~/.nanobot/config.json + workspace) so
    # real process flows / test data don't pollute the source tree.
    os.path.join(os.path.expanduser("~"), ".nanobot", "robot_ai_flows.json"),
)

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "get", "register", "delete", "confirm", "run"],
            "description": (
                "Named-flow action. list/get are read-only. register/delete/confirm "
                "manage persisted flows. run is ALWAYS dry-run from the LLM (no real "
                "writes); real flow execution is operator-only via the CLI/bridge. "
                "Flow steps may not use alarm_reset (operator-only)."
            ),
        },
        "name": {
            "type": "string",
            "description": "Flow name (case-insensitive lookup).",
        },
        "description": {
            "type": "string",
            "description": "Human-readable flow description for register.",
        },
        "steps": {
            "type": "array",
            "description": (
                "Ordered step list for register. Each step: {func_id, params, "
                "description, spd_pct}. func_id 108=linear_move "
                "(params.target_pose x/y/z/rx/ry/rz + speed_pct/acceleration_pct/"
                "deceleration_pct/r_min/r_max/z_min/z_max), 104=system "
                "(params.action), 110=delay (params.seconds), 120=io "
                "(params.io_number/enabled/allowed_io_channels)."
            ),
        },
        "step_delay_ms": {
            "type": "integer",
            "description": "Optional inter-step delay hint for register.",
        },
        # NOTE: execute_real / confirm_work_area_clear / confirm_estop_ready /
        # confirmation_code are intentionally NOT exposed — robot_flow run is
        # always dry-run from the LLM. Real execution is operator-only (same
        # rule as robot_arm). The tool ignores these even if a caller passes them.
    },
    "required": ["action"],
    "additionalProperties": True,
}


@tool_parameters(_PARAMETERS)
class RobotFlowTool(Tool):
    def __init__(self, registry_path: str | None = None) -> None:
        self._registry_path = registry_path or _DEFAULT_FLOWS_PATH

    @property
    def name(self) -> str:
        return "robot_flow"

    @property
    def description(self) -> str:
        return (
            "Manage and run named, persisted multi-step robot flows. run is ALWAYS dry-run from the "
            "LLM (ok=true, state=flow_completed, no controller writes) — real flow execution is "
            "operator-only via the CLI/bridge. Each step's result carries the same dry-run plan + "
            "blockers semantics as robot_arm: blockers are real-execution requirements, NOT errors. "
            "Report a run as 'flow plan executed (dry-run), no motion', not as a failure."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()
        if action == "list":
            result = self._list()
        elif action == "get":
            result = self._get(str(kwargs.get("name") or ""))
        elif action == "register":
            result = self._register(kwargs)
        elif action == "delete":
            result = self._delete(str(kwargs.get("name") or ""))
        elif action == "confirm":
            result = self._confirm(str(kwargs.get("name") or ""))
        elif action == "run":
            result = self._run(kwargs)
        else:
            result = ToolResult.failure(
                state="unknown_flow_action",
                message=f"Unknown flow action: {action}",
                errors=[{"code": "unknown_flow_action", "action": action}],
            ).to_dict()
        return json.dumps(result, ensure_ascii=False)

    def _registry(self) -> FlowRegistry:
        return FlowRegistry(self._registry_path)

    def _list(self) -> dict:
        flows = [flow.to_dict() for flow in self._registry().list_all()]
        return ToolResult.success(
            state="flow_list",
            message=f"{len(flows)} flow(s) registered.",
            data={"flows": flows, "count": len(flows)},
        ).to_dict()

    def _get(self, name: str) -> dict:
        flow = self._registry().get(name)
        if flow is None:
            return ToolResult.failure(
                state="flow_not_found",
                message=f"Flow '{name}' does not exist.",
                errors=[{"code": "flow_not_found", "name": name}],
            ).to_dict()
        return ToolResult.success(
            state="flow_found",
            message=f"Flow '{flow.name}' found.",
            data={"flow": flow.to_dict()},
        ).to_dict()

    def _register(self, kwargs: dict[str, Any]) -> dict:
        name = str(kwargs.get("name") or "").strip()
        if not name:
            return ToolResult.failure(
                state="flow_invalid",
                message="Flow name is required.",
                errors=[{"code": "missing_flow_name"}],
            ).to_dict()
        raw_steps = kwargs.get("steps") or []
        if not isinstance(raw_steps, list) or not raw_steps:
            return ToolResult.failure(
                state="flow_invalid",
                message="A flow must have at least one step.",
                errors=[{"code": "missing_flow_steps"}],
            ).to_dict()
        steps = [FlowStep.from_dict(dict(step)) for step in raw_steps]
        # alarm_reset is operator-only — reject it as a flow step so the LLM
        # can't sneak alarm clearing into a registered flow.
        for step in steps:
            if int(step.func_id) == 104 and str(step.params.get("action", "")) == "alarm_reset":
                return ToolResult.failure(
                    state="flow_invalid",
                    message="alarm_reset is operator-only and cannot be a flow step.",
                    errors=[
                        {
                            "code": "alarm_reset_not_allowed_in_flow",
                            "step_id": step.step_id,
                        }
                    ],
                ).to_dict()
        entry = FlowEntry(
            name=name,
            description=str(kwargs.get("description") or ""),
            steps=steps,
            step_delay_ms=int(kwargs.get("step_delay_ms", 1000)),
        )
        ok, message = self._registry().add(entry)
        state = "flow_registered" if ok else "flow_invalid"
        return ToolResult(
            ok=ok,
            state=state,
            message=message,
            data={"flow": entry.to_dict()} if ok else {},
            errors=[] if ok else [{"code": state}],
        ).to_dict()

    def _delete(self, name: str) -> dict:
        ok, message = self._registry().remove(name)
        return ToolResult(
            ok=ok,
            state="flow_deleted" if ok else "flow_not_found",
            message=message,
            errors=[] if ok else [{"code": "flow_not_found", "name": name}],
        ).to_dict()

    def _confirm(self, name: str) -> dict:
        ok, message = self._registry().confirm(name)
        return ToolResult(
            ok=ok,
            state="flow_confirmed" if ok else "flow_not_found",
            message=message,
            errors=[] if ok else [{"code": "flow_not_found", "name": name}],
        ).to_dict()

    def _run(self, kwargs: dict[str, Any]) -> dict:
        name = str(kwargs.get("name") or "")
        flow = self._registry().get(name)
        if flow is None:
            return ToolResult.failure(
                state="flow_not_found",
                message=f"Flow '{name}' does not exist.",
                errors=[{"code": "flow_not_found", "name": name}],
            ).to_dict()
        # LLM path is ALWAYS dry-run — ignore any execute_real / confirm_* /
        # confirmation_code the caller tries to pass. Real flow execution is
        # operator-only (CLI/bridge with the EXECUTE_ZMOTION_REAL code).
        return run_flow(
            flow,
            execute_real=False,
            confirm_work_area_clear=False,
            confirm_estop_ready=False,
            confirmation_code="",
        )
