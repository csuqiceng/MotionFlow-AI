"""Trusted identity capability passed through the agent runtime.

The capability can only be minted by a trusted host adapter after it has
authenticated a request.  Model/tool payloads only carry strings and cannot
manufacture an instance that passes the seal check.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Iterator


_VERIFICATION_SEAL = object()


@dataclass(frozen=True)
class VerifiedPrincipal:
    actor_id: str
    role: str
    session_id: str
    auth_source: str
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _VERIFICATION_SEAL:
            raise TypeError("VerifiedPrincipal must be issued by a trusted adapter")
        for name in ("actor_id", "role", "session_id", "auth_source"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"VerifiedPrincipal requires {name}")
            object.__setattr__(self, name, value)
        if self.role not in {"operator", "engineer", "system"}:
            raise ValueError("VerifiedPrincipal role is invalid")

    @property
    def actor(self) -> str:
        return f"{self.role}:{self.actor_id}"


def issue_verified_principal(
    *, actor_id: str, role: str, session_id: str, auth_source: str,
) -> VerifiedPrincipal:
    """Mint claims after the calling host adapter authenticates the request."""
    return VerifiedPrincipal(
        actor_id=actor_id,
        role=role,
        session_id=session_id,
        auth_source=auth_source,
        _seal=_VERIFICATION_SEAL,
    )


_current_principal: ContextVar[VerifiedPrincipal | None] = ContextVar(
    "verified_agent_principal", default=None,
)


def current_verified_principal() -> VerifiedPrincipal | None:
    return _current_principal.get()


@contextmanager
def bind_verified_principal(principal: VerifiedPrincipal) -> Iterator[None]:
    if not isinstance(principal, VerifiedPrincipal):
        raise TypeError("Agent turn requires VerifiedPrincipal")
    token: Token[VerifiedPrincipal | None] = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)
