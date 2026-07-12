"""Robot library data models: enums, ParameterField, Component, Command, AuditEntry.

Pure data (dataclasses + from_dict/to_dict), mirroring ``robot_ai.flow.models``.
No ZMotion / Qt / permission deps. ``version`` is a forward-compatible field
(A1 stores only the single current record per command; version history is
deferred to phase B).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CommandStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


def normalize_id(name: str) -> str:
    """Stable id derived from a name: strip + lowercase + collapse whitespace to '-'."""
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return s


@dataclass
class ParameterField:
    name: str
    type: str  # "int" | "float" | "str" | "bool"
    unit: str = ""
    minimum: Any = None
    maximum: Any = None
    default: Any = None
    required: bool = True
    description: str = ""

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "ParameterField":
        return cls(
            name=str(p.get("name", "")),
            type=str(p.get("type", "str")),
            unit=str(p.get("unit", "")),
            minimum=p.get("minimum"),
            maximum=p.get("maximum"),
            default=p.get("default"),
            required=bool(p.get("required", True)),
            description=str(p.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Component:
    id: str
    func_num: int
    name: str
    parameters: list[ParameterField] = field(default_factory=list)
    required_safety_state: str = ""
    flow_eligible: bool = True
    risk_level: str = "medium"
    description: str = ""

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "Component":
        return cls(
            id=str(p.get("id", "")),
            func_num=int(p.get("func_num", 0)),
            name=str(p.get("name", "")),
            parameters=[ParameterField.from_dict(dict(x)) for x in p.get("parameters", [])],
            required_safety_state=str(p.get("required_safety_state", "")),
            flow_eligible=bool(p.get("flow_eligible", True)),
            risk_level=str(p.get("risk_level", "medium")),
            description=str(p.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Command:
    id: str
    name: str
    component_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    risk_level: str = RiskLevel.HIGH.value
    status: str = CommandStatus.PUBLISHED.value
    version: int = 1
    source: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    published_at: str = ""

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "Command":
        return cls(
            id=str(p.get("id", "")),
            name=str(p.get("name", "")),
            component_id=str(p.get("component_id", "")),
            parameters=dict(p.get("parameters", {})),
            aliases=[str(a) for a in p.get("aliases", [])],
            description=str(p.get("description", "")),
            risk_level=str(p.get("risk_level", RiskLevel.HIGH.value)),
            status=str(p.get("status", CommandStatus.PUBLISHED.value)),
            version=int(p.get("version", 1)),
            source=str(p.get("source", "")),
            created_by=str(p.get("created_by", "")),
            created_at=str(p.get("created_at", "")),
            updated_at=str(p.get("updated_at", "")),
            published_at=str(p.get("published_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEntry:
    action: str
    actor: str
    timestamp: str
    target: dict[str, Any] | None = None
    migration_id: str | None = None
    before: Any = None
    after: Any = None

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "AuditEntry":
        return cls(
            action=str(p.get("action", "")),
            actor=str(p.get("actor", "")),
            timestamp=str(p.get("timestamp", "")),
            target=p.get("target"),
            migration_id=p.get("migration_id"),
            before=p.get("before"),
            after=p.get("after"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
