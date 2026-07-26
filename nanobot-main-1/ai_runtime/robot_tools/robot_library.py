from __future__ import annotations

import json
import secrets
import time
from typing import Any

from ai_runtime.robot_tools.base import Tool, tool_parameters
from robot_platform import get_robot_data_dir
from robot_platform.library.mutation_service import RobotLibraryMutationService
from robot_platform.models import ToolResult
from robot_platform.runtime import current_robot_actor

_PENDING: dict[str, tuple[float, str, dict[str, Any]]] = {}
_TTL_SECONDS = 300
_PARAMETERS = {"type": "object", "properties": {"action": {"type": "string", "enum": ["preview_save", "preview_update", "preview_delete", "confirm_save"]}, "resource_type": {"type": "string", "enum": ["position", "command", "flow"]}, "name": {"type": "string"}, "pose": {"type": "object"}, "spd": {"type": "number"}, "component_id": {"type": "string"}, "parameters": {"type": "object"}, "aliases": {"type": "array"}, "description": {"type": "string"}, "steps": {"type": "array"}, "confirmation_token": {"type": "string"}}, "required": ["action"], "additionalProperties": True}


@tool_parameters(_PARAMETERS)
class RobotLibraryTool(Tool):
    def __init__(self, data_dir: str | None = None) -> None:
        self._data_dir = data_dir or str(get_robot_data_dir())

    @property
    def name(self) -> str:
        return "robot_library"

    @property
    def description(self) -> str:
        return "Create a position, command, or flow only in two steps: preview_save then confirm_save. Engineers may also preview_update or preview_delete positions, then confirm_save."

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "")
        actor = current_robot_actor()
        if action in {"preview_save", "preview_update", "preview_delete"}:
            resource_type = str(kwargs.get("resource_type") or "")
            payload = {key: value for key, value in kwargs.items() if key not in {"action", "resource_type", "confirmation_token"} and value is not None}
            if action != "preview_save" and not actor.startswith("engineer:"):
                result = ToolResult.failure(state="library_forbidden", message="Only engineers may modify or delete saved library entries.", errors=[{"code": "library_forbidden"}])
                return json.dumps(result.to_dict(), ensure_ascii=False)
            if action in {"preview_update", "preview_delete"} and resource_type != "position":
                result = ToolResult.failure(state="library_preview_invalid", message="Only positions support chat update or delete.", errors=[{"code": "library_preview_invalid"}])
                return json.dumps(result.to_dict(), ensure_ascii=False)
            if resource_type not in {"position", "command", "flow"} or not str(payload.get("name", "")).strip():
                result = ToolResult.failure(state="library_preview_invalid", message="resource_type and name are required.", errors=[{"code": "library_preview_invalid"}])
            else:
                token = secrets.token_urlsafe(18)
                operation = {"preview_save": "create", "preview_update": "update", "preview_delete": "delete"}[action]
                _PENDING[token] = (time.monotonic() + _TTL_SECONDS, actor, {"operation": operation, "resource_type": resource_type, "payload": payload})
                result = ToolResult.success(state="library_save_preview", message="Review the proposed resource, then ask the user for explicit confirmation.", data={"operation": operation, "resource_type": resource_type, "preview": payload, "confirmation_token": token, "expires_in_seconds": _TTL_SECONDS})
            return json.dumps(result.to_dict(), ensure_ascii=False)
        if action == "confirm_save":
            token = str(kwargs.get("confirmation_token") or "")
            pending = _PENDING.pop(token, None)
            if pending is None or pending[0] < time.monotonic():
                result = ToolResult.failure(state="library_confirmation_expired", message="No active save confirmation exists.", errors=[{"code": "library_confirmation_expired"}])
            elif pending[1] != actor:
                result = ToolResult.failure(state="library_confirmation_forbidden", message="The confirmation belongs to another user session.", errors=[{"code": "library_confirmation_forbidden"}])
            else:
                try:
                    mutation = RobotLibraryMutationService(self._data_dir)
                    operation = pending[2].get("operation", "create")
                    if operation == "create":
                        saved = mutation.create(pending[2]["resource_type"], pending[2]["payload"], actor=actor)
                    elif operation == "update":
                        saved = mutation.update_position(pending[2]["payload"], actor=actor)
                    else:
                        saved = mutation.delete_position(pending[2]["payload"], actor=actor)
                    result = ToolResult.success(state="library_saved", message="Robot library resource saved.", data=saved)
                except ValueError as exc:
                    result = ToolResult.failure(state="library_save_invalid", message=str(exc), errors=[{"code": "library_save_invalid"}])
            return json.dumps(result.to_dict(), ensure_ascii=False)
        return json.dumps(ToolResult.failure(state="unknown_library_action", message=f"Unknown: {action}", errors=[{"code": "unknown_library_action"}]).to_dict(), ensure_ascii=False)
