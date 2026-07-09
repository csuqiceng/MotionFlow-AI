from __future__ import annotations

import json
import os
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from robot_ai.execution.mode import AUTO_EXECUTE
from robot_ai.flow import FlowEntry, FlowRegistry, FlowStep, run_flow
from robot_ai.flow.aliases import FlowAlias
from robot_ai.models import ToolResult
from robot_ai.zmotion_operator_control import REAL_EXECUTION_CONFIRMATION_CODE

_DEFAULT_FLOWS_PATH = os.environ.get(
    "ROBOT_AI_FLOWS_PATH",
    # Default outside the repo (next to ~/.nanobot/config.json + workspace) so
    # real process flows / test data don't pollute the source tree.
    os.path.join(os.path.expanduser("~"), ".nanobot", "robot_ai", "flows.json"),
)

_DEFAULT_ALIASES_PATH = os.environ.get(
    "ROBOT_AI_FLOW_ALIASES_PATH",
    os.path.join(os.path.expanduser("~"), ".nanobot", "robot_ai", "flow_aliases.json"),
)

# Step whitelist: only these func_ids map to a restricted operator command in
# run_flow. func_id=0 (migrated free-text) is allowed at registration time so
# legacy flows are preserved, but run_flow will report those steps as
# 'unsupported' (non-executable).
_ALLOWED_STEP_FUNC_IDS: frozenset[int] = frozenset({104, 108, 110, 120, 0})

# func_id=104 (system) action whitelist. alarm_reset is operator-only and
# rejected separately (kept here for documentation; it is NOT in the set).
_ALLOWED_SYSTEM_ACTIONS: frozenset[str] = frozenset(
    {
        "emergency_stop",
        "release_emergency_stop",
        "pause",
        "resume",
        "stop_current",
        "release_cancel",
    }
)

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "get", "register", "delete", "confirm", "run"],
            "description": (
                "Flow action. PRIORITY: when the user says any phrase that could be a "
                "flow name (e.g. '点头', '上料', 'demo'), FIRST try action='run' with "
                "name=that phrase. If the flow exists, execute it — do NOT improvise "
                "motion via robot_arm. Only if flow_not_found, then the user may want "
                "a custom motion. '执行X流程'/'运行X' always means run. Only use "
                "'register' when the user explicitly asks to CREATE a new flow."
            ),
        },
        "name": {
            "type": "string",
            "description": "Flow name (case-insensitive lookup).",
        },
        "flow_alias": {
            "type": "string",
            "description": (
                "Optional spoken phrase resolved against flow_aliases.json "
                "(name/keywords, case-insensitive substring) to a canonical flow "
                "name. Alternative to 'name' for run. If the alias is unknown → "
                "flow_alias_not_found."
            ),
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
    def __init__(
        self,
        registry_path: str | None = None,
        *,
        alias_path: str | None = None,
    ) -> None:
        self._registry_path = registry_path or _DEFAULT_FLOWS_PATH
        self._alias_path = alias_path or _DEFAULT_ALIASES_PATH

    @property
    def name(self) -> str:
        return "robot_flow"

    @property
    def description(self) -> str:
        if AUTO_EXECUTE:
            return (
                "Manage and run named, persisted multi-step robot flows. run executes all steps "
                "directly on the controller in auto mode. L1 safety (bounds/limits/alarm) applies "
                "per step. One tool call runs the entire flow — do NOT decompose into individual "
                "robot_arm calls. Report the per-step results (pose / completion) to the user."
            )
        return (
            "Manage and run named, persisted multi-step robot flows. run is dry-run only — "
            "returns the plan per step without writing to the controller. Real execution is "
            "operator-only via the CLI/bridge or the WebUI Robot Control Panel."
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
        # Step whitelist: func_id must be executable (104/108/110/120) or 0
        # (migrated free-text, kept for reference but non-executable). func_id=104
        # (system) further restricts the action; alarm_reset is operator-only.
        for step in steps:
            error = self._validate_step(step)
            if error is not None:
                return error
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

    @staticmethod
    def _validate_step(step: FlowStep) -> dict | None:
        """Return a failure dict if ``step`` violates the whitelist, else None."""
        func_id = int(step.func_id)
        # func_id=0 (migrated free-text) is allowed so legacy flows are
        # preserved; run_flow will report such steps as 'unsupported'.
        if func_id == 0:
            return None
        if func_id not in _ALLOWED_STEP_FUNC_IDS:
            return ToolResult.failure(
                state="flow_invalid",
                message=(
                    f"Step func_id {func_id} is not allowed. Allowed: "
                    "104 (system), 108 (linear_move), 110 (delay), 120 (io), "
                    "0 (migrated non-executable)."
                ),
                errors=[
                    {
                        "code": "step_func_not_allowed",
                        "step_id": step.step_id,
                        "func_id": func_id,
                    }
                ],
            ).to_dict()
        if func_id == 104:
            action = str(step.params.get("action", "")).strip()
            # alarm_reset is operator-only — reject it as a flow step so the LLM
            # can't sneak alarm clearing into a registered flow.
            if action == "alarm_reset":
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
            if action not in _ALLOWED_SYSTEM_ACTIONS:
                return ToolResult.failure(
                    state="flow_invalid",
                    message=(
                        f"System action '{action}' is not allowed. Allowed: "
                        f"{sorted(_ALLOWED_SYSTEM_ACTIONS)}."
                    ),
                    errors=[
                        {
                            "code": "step_action_not_allowed",
                            "step_id": step.step_id,
                            "action": action,
                        }
                    ],
                ).to_dict()
        return None

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
        alias_phrase = str(kwargs.get("flow_alias") or "").strip()
        if alias_phrase:
            # Resolve the spoken phrase to a canonical flow name. If neither
            # 'name' nor the alias resolves to a registered flow, prefer the
            # alias-not-found signal (more informative for the LLM).
            canonical = FlowAlias(self._alias_path).resolve(alias_phrase)
            if not canonical:
                return ToolResult.failure(
                    state="flow_alias_not_found",
                    message=f"Flow alias '{alias_phrase}' does not match any alias.",
                    errors=[
                        {"code": "flow_alias_not_found", "flow_alias": alias_phrase}
                    ],
                ).to_dict()
            name = canonical
        flow = self._registry().get(name)
        if flow is None:
            return ToolResult.failure(
                state="flow_not_found",
                message=f"Flow '{name}' does not exist.",
                errors=[{"code": "flow_not_found", "name": name}],
            ).to_dict()
        # AUTO_EXECUTE (from tools.execution_mode config) controls whether
        # flows execute directly. L1 safety still applies. Default = dry-run.
        return run_flow(
            flow,
            execute_real=AUTO_EXECUTE,
            confirm_work_area_clear=AUTO_EXECUTE,
            confirm_estop_ready=AUTO_EXECUTE,
            confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE if AUTO_EXECUTE else "",
        )
