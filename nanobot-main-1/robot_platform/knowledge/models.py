from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class KnowledgeEntry:
    category: str  # safety | operation | error_code | flow | position | skill | general
    title: str
    content: str
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeEntry":
        return cls(
            category=str(d.get("category", "general")),
            title=str(d.get("title", "")),
            content=str(d.get("content", "")),
            source=str(d.get("source", "")),
        )
