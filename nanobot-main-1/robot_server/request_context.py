"""Transport-neutral request context owned by robot_server."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from robot_platform.application import AuthenticatedPrincipal


_session_key: ContextVar[str | None] = ContextVar("robot_server_session_key", default=None)
_principal: ContextVar[AuthenticatedPrincipal | None] = ContextVar(
    "robot_server_authenticated_principal", default=None
)


def current_session_key() -> str | None:
    return _session_key.get()


def current_principal() -> AuthenticatedPrincipal | None:
    return _principal.get()


@contextmanager
def bind_session_key(value: str) -> Iterator[None]:
    token: Token[str | None] = _session_key.set(value)
    try:
        yield
    finally:
        _session_key.reset(token)


@contextmanager
def bind_principal(principal: AuthenticatedPrincipal) -> Iterator[None]:
    """Bind a principal established by a trusted interface adapter."""
    principal_token: Token[AuthenticatedPrincipal | None] = _principal.set(principal)
    session_token: Token[str | None] = _session_key.set(
        f"robot-server:{principal.session_id}"
    )
    try:
        yield
    finally:
        _session_key.reset(session_token)
        _principal.reset(principal_token)
