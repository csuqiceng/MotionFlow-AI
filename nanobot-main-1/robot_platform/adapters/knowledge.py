"""File adapter for the robot knowledge catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform.knowledge.loader import KnowledgeStore


class FileRobotKnowledgeAdapter:
    def __init__(self, path: str | Path) -> None:
        self._store = KnowledgeStore(path)

    def list_entries(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._store.load()]

    def query_entries(self, *, category: str, keyword: str) -> list[dict[str, Any]]:
        return [
            entry.to_dict()
            for entry in self._store.query(
                category=category or None,
                keyword=keyword or None,
            )
        ]
