from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ai_runtime.robot_tools.base import Tool, tool_parameters
from ai_runtime.robot_tools.principal import current_application_principal
from robot_platform.application import (
    RobotLibraryApplicationPort,
    RobotLibraryConfirmCommand,
    RobotLibraryPreviewCommand,
)
from robot_platform.models import ToolResult

_FLOW_STEP_PARAMETERS = {
    "type": "object",
    "properties": {
        "step_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Unique 1-based step number; generated when omitted.",
        },
        "action": {"type": "string"},
        "func_id": {"type": "integer", "enum": [104, 108, 110, 120]},
        "params": {"type": "object"},
        "position_name": {"type": "string"},
        "spd_pct": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
        "description": {"type": "string"},
    },
    "required": ["func_id", "params"],
    "additionalProperties": True,
}

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "preview_save", "preview_update", "preview_delete", "confirm_save",
            ],
        },
        "resource_type": {
            "type": "string", "enum": ["position", "command", "flow"],
        },
        "name": {"type": "string"},
        "pose": {"type": "object"},
        "spd": {"type": "number"},
        "component_id": {"type": "string"},
        "parameters": {"type": "object"},
        "aliases": {"type": "array"},
        "description": {"type": "string"},
        "steps": {"type": "array", "items": _FLOW_STEP_PARAMETERS},
        "move_type": {"type": "integer"},
        "step_delay_ms": {"type": "number", "minimum": 0},
        "rehearsal_spd": {"type": "number", "exclusiveMinimum": 0},
        "node_graph": {"type": "object"},
        "confirmation_token": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": True,
}


@tool_parameters(_PARAMETERS)
class RobotLibraryTool(Tool):
    def __init__(
        self, *, library_application: RobotLibraryApplicationPort | None = None,
    ) -> None:
        self._library_application = library_application

    def canonical_effect_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        action = str(parameters.get("action") or "").strip()
        if action == "confirm_save":
            return {
                "action": action,
                "confirmation_token": str(
                    parameters.get("confirmation_token") or ""
                ).strip(),
            }
        if action not in {"preview_save", "preview_update", "preview_delete"}:
            return {"action": action}
        frozen: dict[str, Any] = {
            "action": action,
            "resource_type": str(parameters.get("resource_type") or "").strip(),
        }
        resource_type = frozen["resource_type"]
        if action == "preview_save":
            if resource_type == "position":
                frozen.update({
                    "spd": float(parameters.get("spd", 50.0)),
                    "move_type": int(parameters.get("move_type", 0)),
                })
            elif resource_type == "command":
                frozen.update({"aliases": [], "description": ""})
            elif resource_type == "flow":
                frozen.update({
                    "step_delay_ms": float(parameters.get("step_delay_ms", 1000)),
                    "rehearsal_spd": float(parameters.get("rehearsal_spd", 20)),
                    "description": str(parameters.get("description", "")),
                    "node_graph": deepcopy(parameters.get("node_graph")),
                })
        for key in (
            "name", "pose", "spd", "component_id", "parameters",
            "aliases", "description", "steps", "move_type", "step_delay_ms",
            "rehearsal_spd", "node_graph",
        ):
            if key not in parameters or parameters[key] is None:
                continue
            value = deepcopy(parameters[key])
            if key == "spd":
                value = float(value)
            elif key == "move_type":
                value = int(value)
            elif key in {"step_delay_ms", "rehearsal_spd"}:
                value = float(value)
            elif key == "pose" and isinstance(value, dict):
                value = {axis: float(number) for axis, number in value.items()}
            elif key == "aliases" and isinstance(value, list):
                value = sorted(str(alias) for alias in value)
            elif (
                key == "steps"
                and frozen.get("resource_type") == "flow"
                and isinstance(value, list)
            ):
                value = _with_generated_step_ids(value)
            frozen[key] = value
        return frozen

    @property
    def name(self) -> str:
        return "robot_library"

    @property
    def description(self) -> str:
        return (
            "Create a position, command, or flow only in two confirmed steps. "
            "Only engineers may update or delete saved positions."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        if self._library_application is None:
            return _failure(
                "library_state_unavailable", "Library service is unavailable.",
            )
        action = str(kwargs.get("action") or "")
        principal = current_application_principal()
        try:
            if action in {"preview_save", "preview_update", "preview_delete"}:
                resource_type = str(kwargs.get("resource_type") or "")
                payload = {
                    key: value for key, value in kwargs.items()
                    if key not in {"action", "resource_type", "confirmation_token"}
                    and value is not None
                }
                if resource_type == "flow" and action == "preview_save":
                    payload["steps"] = _with_generated_step_ids(payload.get("steps"))
                operation = {
                    "preview_save": "create",
                    "preview_update": "update",
                    "preview_delete": "delete",
                }[action]
                response = self._library_application.preview(
                    RobotLibraryPreviewCommand(
                        principal=principal,
                        operation=operation,
                        resource_type=resource_type,
                        payload=payload,
                    )
                )
            elif action == "confirm_save":
                response = self._library_application.confirm(
                    RobotLibraryConfirmCommand(
                        principal=principal,
                        confirmation_token=str(
                            kwargs.get("confirmation_token") or ""
                        ),
                    )
                )
            else:
                return _failure(
                    "unknown_library_action", "Unknown library action.",
                )
        except Exception:
            return _failure(
                "library_state_unavailable", "Library service is unavailable.",
            )
        if not response.ok or response.payload is None:
            error = response.error
            return _failure(
                getattr(error, "code", "library_state_unavailable"),
                getattr(error, "message", "Library service is unavailable."),
            )
        payload = dict(response.payload)
        state = str(payload.pop("state", "library_result"))
        return json.dumps(
            ToolResult.success(
                state=state, message="Library operation completed.", data=payload,
            ).to_dict(),
            ensure_ascii=False,
        )


def _failure(code: str, message: str) -> str:
    return json.dumps(
        ToolResult.failure(
            state=code, message=message, errors=[{"code": code}],
        ).to_dict(),
        ensure_ascii=False,
    )


def _with_generated_step_ids(steps: Any) -> Any:
    if not isinstance(steps, list):
        return deepcopy(steps)
    normalized: list[Any] = []
    for index, raw_step in enumerate(steps, start=1):
        step = deepcopy(raw_step)
        if isinstance(step, dict) and "step_id" not in step:
            step["step_id"] = index
        normalized.append(step)
    return normalized
