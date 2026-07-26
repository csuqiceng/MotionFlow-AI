"""Declarative metadata used to decide whether a product Tool may be exposed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolRiskLevel = Literal["read", "motion", "system"]
_VALID_RISK_LEVELS = frozenset({"read", "motion", "system"})


@dataclass(frozen=True)
class ToolManifest:
    """Stable, SDK-neutral declaration for one product Tool.

    ``required_capabilities`` names either a motion primitive or one of the
    boolean public capability aliases ``state_read`` and ``real_writes``.
    """

    tool_id: str
    version: str
    required_capabilities: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ("operator", "engineer")
    risk_level: ToolRiskLevel = "read"

    def __post_init__(self) -> None:
        tool_id = str(self.tool_id).strip()
        version = str(self.version).strip()
        required_capabilities = tuple(str(item).strip() for item in self.required_capabilities)
        allowed_roles = tuple(str(item).strip() for item in self.allowed_roles)
        risk_level = str(self.risk_level).strip()
        if not tool_id or not version:
            raise ValueError("Tool manifest requires tool_id and version")
        if not allowed_roles or any(not role for role in allowed_roles):
            raise ValueError("Tool manifest requires at least one allowed role")
        if any(not capability for capability in required_capabilities):
            raise ValueError("Tool manifest capability names cannot be empty")
        if risk_level not in _VALID_RISK_LEVELS:
            raise ValueError(f"Unknown tool risk level: {risk_level}")
        object.__setattr__(self, "tool_id", tool_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "required_capabilities", required_capabilities)
        object.__setattr__(self, "allowed_roles", allowed_roles)
        object.__setattr__(self, "risk_level", risk_level)
