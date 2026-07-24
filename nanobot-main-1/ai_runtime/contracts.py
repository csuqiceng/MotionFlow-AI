"""Transport-neutral contracts exposed by the robot AI runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeRequest:
    conversation_id: str
    actor_id: str
    content: str
    stream: bool = True
    attachments: tuple[str, ...] = ()
    request_id: str | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    conversation_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None


def validate_conversation_id(value: str) -> str:
    """Validate the product-level conversation identifier."""
    cleaned = str(value).strip()
    if not cleaned or len(cleaned) > 128:
        raise ValueError("conversation_id must contain 1 to 128 characters")
    return cleaned
