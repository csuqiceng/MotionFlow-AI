from __future__ import annotations

import json
import os
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.config.paths import get_robot_ai_dir
from robot_ai.knowledge.loader import KnowledgeStore
from robot_ai.models import ToolResult

def _default_path() -> str:
    """Resolve at construction time so ``--config`` selects the same library."""
    return os.environ.get("ROBOT_AI_KNOWLEDGE_PATH", str(get_robot_ai_dir() / "knowledge.json"))

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
    def __init__(self, path: str | None = None) -> None:
        self._path = path or _default_path()

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
        store = KnowledgeStore(self._path)
        if action == "list":
            items = store.load()
        elif action == "query":
            items = store.query(
                category=kwargs.get("category"), keyword=kwargs.get("keyword")
            )
        else:
            return json.dumps(
                ToolResult.failure(
                    state="unknown_knowledge_action",
                    message=f"Unknown: {action}",
                    errors=[{"code": "unknown_knowledge_action"}],
                ).to_dict(),
                ensure_ascii=False,
            )
        return json.dumps(
            ToolResult.success(
                state="knowledge_query",
                message=f"{len(items)} entry/entries.",
                data={"entries": [e.to_dict() for e in items], "count": len(items)},
            ).to_dict(),
            ensure_ascii=False,
        )
