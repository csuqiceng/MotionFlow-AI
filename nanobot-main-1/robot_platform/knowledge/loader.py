from __future__ import annotations

import json
from pathlib import Path

from robot_platform.knowledge.models import KnowledgeEntry


class KnowledgeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[KnowledgeEntry]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [KnowledgeEntry.from_dict(e) for e in payload.get("entries", [])]

    def replace(self, entries: list[KnowledgeEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": "1.0", "entries": [e.to_dict() for e in entries]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def query(
        self, *, category: str | None = None, keyword: str | None = None
    ) -> list[KnowledgeEntry]:
        items = self.load()
        if category:
            items = [e for e in items if e.category == category]
        if keyword:
            k = keyword.lower()
            items = [
                e for e in items if k in e.title.lower() or k in e.content.lower()
            ]
        return items
