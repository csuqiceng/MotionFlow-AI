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

_PARAMETERS = {"type": "object", "properties": {"action": {"type": "string", "enum": ["preview_save", "preview_update", "preview_delete", "confirm_save"]}, "resource_type": {"type": "string", "enum": ["position", "command", "flow"]}, "name": {"type": "string"}, "pose": {"type": "object"}, "spd": {"type": "number"}, "component_id": {"type": "string"}, "parameters": {"type": "object"}, "aliases": {"type": "array"}, "description": {"type": "string"}, "steps": {"type": "array"}, "confirmation_token": {"type": "string"}}, "required": ["action"], "additionalProperties": True}


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
        for key in (
            "name", "pose", "spd", "component_id", "parameters",
            "aliases", "description", "steps",
        ):
            if key not in parameters or parameters[key] is None:
                continue
            value = deepcopy(parameters[key])
            if key == "spd":
                value = float(value)
            elif key == "pose" and isinstance(value, dict):
                value = {axis: float(number) for axis, number in value.items()}
            elif key == "aliases" and isinstance(value, list):
                value = sorted(str(alias) for alias in value)
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
