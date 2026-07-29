"""Transport-neutral contracts exposed by the robot AI runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any

from ai_runtime.identity import VerifiedPrincipal


@dataclass(frozen=True)
class RuntimeRequest:
    conversation_id: str
    actor_id: str
    content: str
    stream: bool = True
    attachments: tuple[str, ...] = ()
    request_id: str | None = None
    principal: VerifiedPrincipal | None = None

    def __post_init__(self) -> None:
        if self.principal is not None and self.actor_id != self.principal.actor:
            raise ValueError("RuntimeRequest actor_id must match verified principal")


@dataclass(frozen=True)
class RuntimeEvent:
    conversation_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __post_init__(self) -> None:
        conversation_id = validate_conversation_id(self.conversation_id)
        kind = str(self.kind).strip()
        if not kind or len(kind) > 64:
            raise ValueError("RuntimeEvent kind must contain 1 to 64 characters")
        if not isinstance(self.payload, dict):
            raise TypeError("RuntimeEvent payload must be an object")
        object.__setattr__(self, "conversation_id", conversation_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "payload", deepcopy(self.payload))

    def to_contract_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "conversation_id": self.conversation_id,
            "kind": self.kind,
            "payload": deepcopy(self.payload),
            "request_id": self.request_id,
        }


def validate_conversation_id(value: str) -> str:
    """Validate the product-level conversation identifier."""
    cleaned = str(value).strip()
    if not cleaned or len(cleaned) > 128:
        raise ValueError("conversation_id must contain 1 to 128 characters")
    return cleaned
