"""Transport-neutral request context owned by robot_server."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator


_session_key: ContextVar[str | None] = ContextVar("robot_server_session_key", default=None)


def current_session_key() -> str | None:
    return _session_key.get()


@contextmanager
def bind_session_key(value: str) -> Iterator[None]:
    token: Token[str | None] = _session_key.set(value)
    try:
        yield
    finally:
        _session_key.reset(token)
