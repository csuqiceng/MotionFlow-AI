"""Read-only robot knowledge query use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotKnowledgeQuery:
    principal: AuthenticatedPrincipal
    action: str
    category: str = ""
    keyword: str = ""


@dataclass(frozen=True)
class RobotKnowledgeError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotKnowledgeResponse:
    payload: dict[str, Any] | None = None
    error: RobotKnowledgeError | None = None

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotKnowledgeResponse requires payload or error")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotKnowledgeCatalogPort(Protocol):
    def list_entries(self) -> list[dict[str, Any]]: ...
    def query_entries(self, *, category: str, keyword: str) -> list[dict[str, Any]]: ...


class RobotKnowledgeApplicationPort(Protocol):
    def query(self, query: RobotKnowledgeQuery) -> RobotKnowledgeResponse: ...


class RobotKnowledgeApplicationService:
    def __init__(self, catalog: RobotKnowledgeCatalogPort) -> None:
        self._catalog = catalog

    def query(self, query: RobotKnowledgeQuery) -> RobotKnowledgeResponse:
        if not isinstance(query, RobotKnowledgeQuery):
            return _failure("invalid_knowledge_request", "Knowledge request is invalid.")
        if query.principal.role not in {"operator", "engineer"}:
            return _failure("knowledge_forbidden", "Operator role is required.")
        try:
            if query.action == "list":
                entries = self._catalog.list_entries()
            elif query.action == "query":
                entries = self._catalog.query_entries(
                    category=str(query.category).strip(),
                    keyword=str(query.keyword).strip(),
                )
            else:
                return _failure(
                    "unknown_knowledge_action", "Unknown knowledge action.",
                )
            public = [_entry(item) for item in entries]
            return RobotKnowledgeResponse(payload={
                "state": "knowledge_query",
                "entries": public,
                "count": len(public),
            })
        except Exception:
            return _failure(
                "knowledge_state_unavailable", "Knowledge service is unavailable.",
            )


def _entry(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("invalid knowledge entry")
    return {
        "category": _text(raw.get("category"), 128),
        "title": _text(raw.get("title"), 1024),
        "content": _text(raw.get("content"), 16384),
        "source": _text(raw.get("source"), 2048),
    }


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid knowledge field")
    return value[:limit]


def _failure(code: str, message: str) -> RobotKnowledgeResponse:
    return RobotKnowledgeResponse(error=RobotKnowledgeError(code, message))
