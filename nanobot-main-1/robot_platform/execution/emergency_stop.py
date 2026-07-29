"""One-use in-process authority for the emergency-stop exception path."""

from __future__ import annotations

import secrets
import threading
import time
from typing import Protocol

from robot_platform.application.principal import AuthenticatedPrincipal


class EmergencyStopVerifierPort(Protocol):
    def claim(self, token: str) -> bool: ...


class EmergencyStopAuthority:
    """Issues one-use tokens only to the dedicated emergency-stop adapter."""

    def __init__(self, *, ttl_sec: float = 10.0) -> None:
        self._ttl_sec = float(ttl_sec)
        self._tokens: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self, principal: AuthenticatedPrincipal) -> str:
        del principal  # identity is audited by the application service, never trusted from HTTP body
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = time.time() + self._ttl_sec
        return token

    def claim(self, token: str) -> bool:
        with self._lock:
            expires_at = self._tokens.pop(str(token), None)
            return expires_at is not None and time.time() < expires_at
