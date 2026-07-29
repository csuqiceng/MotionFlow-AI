from __future__ import annotations

import json
from typing import Any

from ai_runtime.robot_tools.base import Tool, tool_parameters
from ai_runtime.robot_tools.principal import current_application_principal
from robot_platform.application import (
    RobotPositionApplicationPort,
    RobotPositionQuery,
)
from robot_platform.models import ToolResult

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "get", "resolve"]},
        "name": {
            "type": "string",
            "description": "Position name (case-insensitive).",
        },
    },
    "required": ["action"],
    "additionalProperties": True,
}


@tool_parameters(_PARAMETERS)
class RobotPositionTool(Tool):
    def __init__(
        self, *, position_application: RobotPositionApplicationPort | None = None,
    ) -> None:
        self._position_application = position_application

    @property
    def name(self) -> str:
        return "robot_position"

    @property
    def description(self) -> str:
        return (
            "Read-only robot-library lookup (list/get/resolve). Lists named positions, "
            "published position commands, and flow summaries. Never writes."
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def exclusive(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        if self._position_application is None:
            return _json_failure(
                "position_state_unavailable", "Position service is unavailable.",
            )
        action = str(kwargs.get("action") or "").strip()
        name = str(kwargs.get("name") or "")
        try:
            response = self._position_application.query(RobotPositionQuery(
                principal=current_application_principal(), action=action, name=name,
            ))
        except Exception:
            return _json_failure(
                "position_state_unavailable", "Position service is unavailable.",
            )
        if not response.ok or response.payload is None:
            error = response.error
            return _json_failure(
                getattr(error, "code", "position_state_unavailable"),
                getattr(error, "message", "Position service is unavailable."),
            )
        payload = dict(response.payload)
        state = str(payload.pop("state", "position_result"))
        return json.dumps(
            ToolResult.success(
                state=state, message="Position query completed.", data=payload,
            ).to_dict(),
            ensure_ascii=False,
        )


def _json_failure(code: str, message: str) -> str:
    return json.dumps(
        ToolResult.failure(
            state=code, message=message, errors=[{"code": code}],
        ).to_dict(),
        ensure_ascii=False,
    )
