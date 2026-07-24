from __future__ import annotations

import hashlib
import hmac
import time

# POC secret (in production: from config/env, not hardcoded).
_SECRET = b"robot-ai-confirm-secret"


def issue_confirm_code(plan_id: str, *, ttl_sec: float = 300.0) -> str:
    """Backend-issued confirm code (plan_id + time window). NOT the LLM's EXECUTE_ZMOTION_REAL."""
    window = int(time.time() / ttl_sec)
    payload = f"{plan_id}:{window}".encode("utf-8")
    sig = hmac.new(_SECRET, payload, hashlib.sha256).hexdigest()[:16]
    return f"RC-{sig}"


def verify_confirm_code(plan_id: str, code: str, *, ttl_sec: float = 300.0) -> bool:
    if not code or not code.startswith("RC-"):
        return False
    # Accept current or previous window (avoid edge expiry).
    for delta in (0, -1, 1):
        window = int(time.time() / ttl_sec) + delta
        payload = f"{plan_id}:{window}".encode("utf-8")
        expected = hmac.new(_SECRET, payload, hashlib.sha256).hexdigest()[:16]
        if hmac.compare_digest(f"RC-{expected}", code):
            return True
    return False
