"""Engineer authentication: pbkdf2 password hashing + in-memory session tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

DEFAULT_ITERATIONS = 200_000


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Hash a password with pbkdf2_sha256.

    The ``iterations`` floor (>=100_000) is enforced by the config schema
    (``EngineerConfig.pbkdf2_iterations``); this function does not validate it,
    so tests may pass lower values for speed.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    # Always burn one PBKDF2 on the failure paths so timing does not reveal
    # whether the stored hash was well-formed (login enumeration oracle, D8).
    ok = False
    try:
        parts = stored_hash.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            iterations = int(parts[1])
            salt = base64.b64decode(parts[2])
            stored_dk = base64.b64decode(parts[3])
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            ok = hmac.compare_digest(dk, stored_dk)
    except Exception:
        ok = False
    if not ok:
        # Fixed salt + discarded output: only the CPU cost matters (D8 timing equalization).
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"\x00" * 16, DEFAULT_ITERATIONS)
    return ok


def extract_iterations(stored_hash: str) -> int:
    try:
        return int(stored_hash.split("$")[1])
    except (IndexError, ValueError):
        return 0


@dataclass
class LoginThrottle:
    """Sliding-window fail counter keyed by client identity (gateway token by
    default; aiohttp falls back to IP — see D2). Not persistent."""
    max_attempts: int = 5
    window_seconds: int = 300
    _fails: dict[str, list[float]] = field(default_factory=dict)

    def _now(self) -> float:
        return time.monotonic()

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.window_seconds]
        self._fails[key] = recent
        return recent

    def is_throttled(self, key: str) -> bool:
        return len(self._prune(key, self._now())) >= self.max_attempts

    def retry_after(self, key: str) -> int:
        recent = self._fails.get(key, [])
        if not recent:
            return 0
        return max(0, int(self.window_seconds - (self._now() - min(recent))) + 1)

    def record_failure(self, key: str) -> None:
        now = self._now()
        self._prune(key, now)
        self._fails.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


@dataclass
class UserSessionStore:
    """In-memory user session tokens bound to {user_id, username, role, expiry}.

    TTL 8h; no refresh. Replaces EngineerTokenStore (B1a) once endpoints migrate.
    """
    ttl_seconds: int = 8 * 3600
    _sessions: dict[str, dict] = field(default_factory=dict)

    def issue(self, user: dict) -> str:
        self._purge()
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "user_id": user["user_id"], "username": user["username"],
            "role": user["role"],
            "expiry": time.monotonic() + self.ttl_seconds,
        }
        return token

    def check(self, token: str) -> dict | None:
        self._purge()
        session = self._sessions.get(token)
        if session is None or time.monotonic() > session["expiry"]:
            self._sessions.pop(token, None)
            return None
        return session

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)

    def revoke_by_user_id(self, user_id: str) -> None:
        for tok in [t for t, s in self._sessions.items() if s["user_id"] == user_id]:
            self._sessions.pop(tok, None)

    def _purge(self) -> None:
        now = time.monotonic()
        for tok in [t for t, s in self._sessions.items() if now > s["expiry"]]:
            self._sessions.pop(tok, None)


_ENGINEER_LOGIN_THROTTLE = LoginThrottle()
_USER_SESSION_STORE = UserSessionStore()


def get_login_throttle() -> LoginThrottle:
    return _ENGINEER_LOGIN_THROTTLE


def get_user_session_store() -> "UserSessionStore":
    return _USER_SESSION_STORE
