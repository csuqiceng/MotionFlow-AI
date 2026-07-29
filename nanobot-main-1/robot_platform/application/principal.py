"""Trusted identity passed from interface adapters into robot use cases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Identity established by a trusted interface adapter.

    These values must come from an authenticated server/CLI context.  Robot
    use cases must never construct a principal from user-controlled request
    fields or model-generated Tool arguments.
    """

    actor_id: str
    role: str
    session_id: str
    auth_source: str

    def __post_init__(self) -> None:
        for field_name in ("actor_id", "role", "session_id", "auth_source"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"AuthenticatedPrincipal requires {field_name}")
            object.__setattr__(self, field_name, value)

