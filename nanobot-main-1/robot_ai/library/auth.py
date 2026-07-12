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
class EngineerTokenStore:
    ttl_seconds: int = 8 * 3600
    _tokens: dict[str, float] = field(default_factory=dict)

    def issue(self) -> str:
        self._purge()
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.monotonic() + self.ttl_seconds
        return token

    def check(self, token: str) -> bool:
        self._purge()
        expiry = self._tokens.get(token)
        if expiry is None or time.monotonic() > expiry:
            self._tokens.pop(token, None)
            return False
        return True

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)

    def _purge(self) -> None:
        now = time.monotonic()
        for key in list(self._tokens):
            if now > self._tokens[key]:
                del self._tokens[key]


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


_ENGINEER_TOKEN_STORE = EngineerTokenStore()
_ENGINEER_LOGIN_THROTTLE = LoginThrottle()


def get_engineer_token_store() -> EngineerTokenStore:
    return _ENGINEER_TOKEN_STORE


def get_login_throttle() -> LoginThrottle:
    return _ENGINEER_LOGIN_THROTTLE
