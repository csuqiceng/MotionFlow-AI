from __future__ import annotations

import json
import os
from typing import Any

from ai_runtime.robot_tools.base import Tool, tool_parameters
from robot_platform import get_robot_data_dir
from ai_runtime.robot_tools.principal import current_application_principal
from robot_platform.application import (
    RobotKnowledgeApplicationPort,
    RobotKnowledgeQuery,
)
from robot_platform.models import ToolResult

def _default_path() -> str:
    """Resolve at construction time so ``--config`` selects the same library."""
    return os.environ.get("ROBOT_AI_KNOWLEDGE_PATH", str(get_robot_data_dir() / "knowledge.json"))

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "query"]},
        "category": {
            "type": "string",
            "description": "safety|operation|error_code|flow|position|skill|general",
        },
        "keyword": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": True,
}


@tool_parameters(_PARAMETERS)
class RobotKnowledgeTool(Tool):
    def __init__(
        self,
        path: str | None = None,
        *,
        knowledge_application: RobotKnowledgeApplicationPort | None = None,
    ) -> None:
        self._path = path or _default_path()
        self._knowledge_application = knowledge_application

    @property
    def name(self) -> str:
        return "robot_knowledge"

    @property
    def description(self) -> str:
        return (
            "Read-only robot knowledge lookup (safety limits, operation notes, error codes, "
            "flow/position notes). Never writes to the controller."
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def exclusive(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()
        if self._knowledge_application is None:
            return json.dumps(
                ToolResult.failure(
                    state="knowledge_state_unavailable",
                    message="Knowledge service is unavailable.",
                    errors=[{"code": "knowledge_state_unavailable"}],
                ).to_dict(),
                ensure_ascii=False,
            )
        response = self._knowledge_application.query(RobotKnowledgeQuery(
            principal=current_application_principal(),
            action=action,
            category=str(kwargs.get("category") or ""),
            keyword=str(kwargs.get("keyword") or ""),
        ))
        if not response.ok or response.payload is None:
            error = response.error
            code = getattr(error, "code", "knowledge_state_unavailable")
            message = getattr(error, "message", "Knowledge service is unavailable.")
            return json.dumps(
                ToolResult.failure(
                    state=code, message=message, errors=[{"code": code}],
                ).to_dict(),
                ensure_ascii=False,
            )
        payload = dict(response.payload)
        state = str(payload.pop("state", "knowledge_query"))
        return json.dumps(
            ToolResult.success(
                state=state,
                message=f"{payload.get('count', 0)} entry/entries.",
                data=payload,
            ).to_dict(),
            ensure_ascii=False,
        )
