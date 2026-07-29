"""Declarative metadata used to decide whether a product Tool may be exposed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolRiskLevel = Literal["read", "motion", "system"]
ToolConcurrency = Literal["parallel", "exclusive", "actor"]
ToolIdempotency = Literal["none", "request"]
ToolAuditPolicy = Literal["best_effort", "required"]
_VALID_RISK_LEVELS = frozenset({"read", "motion", "system"})
_VALID_CONCURRENCY = frozenset({"parallel", "exclusive", "actor"})
_VALID_IDEMPOTENCY = frozenset({"none", "request"})
_VALID_AUDIT_POLICIES = frozenset({"best_effort", "required"})


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
    timeout_seconds: float = 30.0
    concurrency: ToolConcurrency = "parallel"
    resources: tuple[str, ...] = ()
    idempotency: ToolIdempotency = "none"
    audit_policy: ToolAuditPolicy = "best_effort"
    protocol_version: int = 2

    def __post_init__(self) -> None:
        tool_id = str(self.tool_id).strip()
        version = str(self.version).strip()
        required_capabilities = tuple(str(item).strip() for item in self.required_capabilities)
        allowed_roles = tuple(str(item).strip() for item in self.allowed_roles)
        risk_level = str(self.risk_level).strip()
        concurrency = str(self.concurrency).strip()
        resources = tuple(str(item).strip() for item in self.resources)
        idempotency = str(self.idempotency).strip()
        audit_policy = str(self.audit_policy).strip()
        if not tool_id or not version:
            raise ValueError("Tool manifest requires tool_id and version")
        if not allowed_roles or any(not role for role in allowed_roles):
            raise ValueError("Tool manifest requires at least one allowed role")
        if any(not capability for capability in required_capabilities):
            raise ValueError("Tool manifest capability names cannot be empty")
        if risk_level not in _VALID_RISK_LEVELS:
            raise ValueError(f"Unknown tool risk level: {risk_level}")
        if not 0 < float(self.timeout_seconds) <= 300:
            raise ValueError("Tool timeout must be within 0-300 seconds")
        if concurrency not in _VALID_CONCURRENCY:
            raise ValueError(f"Unknown tool concurrency policy: {concurrency}")
        if any(not resource for resource in resources) or len(set(resources)) != len(resources):
            raise ValueError("Tool resources must be non-empty and unique")
        if idempotency not in _VALID_IDEMPOTENCY:
            raise ValueError(f"Unknown tool idempotency policy: {idempotency}")
        if risk_level != "read" and idempotency != "request":
            raise ValueError("Side-effecting tools require request idempotency")
        if audit_policy not in _VALID_AUDIT_POLICIES:
            raise ValueError(f"Unknown tool audit policy: {audit_policy}")
        if int(self.protocol_version) not in {1, 2}:
            raise ValueError("Unsupported Tool manifest protocol version")
        object.__setattr__(self, "tool_id", tool_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "required_capabilities", required_capabilities)
        object.__setattr__(self, "allowed_roles", allowed_roles)
        object.__setattr__(self, "risk_level", risk_level)
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        object.__setattr__(self, "concurrency", concurrency)
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "idempotency", idempotency)
        object.__setattr__(self, "audit_policy", audit_policy)

    def to_public_dict(self, *, protocol_version: int | None = None) -> dict[str, object]:
        version = self.protocol_version if protocol_version is None else int(protocol_version)
        payload: dict[str, object] = {
            "protocol_version": version,
            "tool_id": self.tool_id,
            "version": self.version,
            "required_capabilities": list(self.required_capabilities),
            "allowed_roles": list(self.allowed_roles),
            "risk_level": self.risk_level,
        }
        if version == 1:
            return payload
        if version != 2:
            raise ValueError("Unsupported Tool manifest protocol version")
        payload.update({
            "timeout_seconds": self.timeout_seconds,
            "concurrency": self.concurrency,
            "resources": list(self.resources),
            "idempotency": self.idempotency,
            "audit_policy": self.audit_policy,
        })
        return payload
