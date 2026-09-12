from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


def _param_hash(params: dict[str, Any]) -> str:
    """Stable SHA256 of the command parameters (canonical JSON, sorted keys)."""
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class PendingPlan:
    plan_id: str
    command: str
    parameters: dict[str, Any]
    param_hash: str
    dry_run_result: dict[str, Any]
    created_at: float
    expires_at: float
    plan_version: str = "1"
    confirmed: bool = False
    permit_handle: str = ""
    child_permit_handles: tuple[str, ...] = ()
    node_approval_receipts: dict[str, str] = field(default_factory=dict)
    confirmation_digest: str = ""

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) > self.expires_at

    def matches(self, parameters: dict[str, Any]) -> bool:
        return _param_hash(parameters) == self.param_hash


class PendingPlanStore:
    """In-memory pending-plan store. POC: lost on restart."""

    def __init__(self, ttl_sec: float = 300.0) -> None:
        self._ttl = ttl_sec
        self._plans: dict[str, PendingPlan] = {}
        self._lock = threading.RLock()

    def create(
        self,
        *,
        command: str,
        parameters: dict[str, Any],
        dry_run_result: dict[str, Any],
    ) -> PendingPlan:
        with self._lock:
            self.expire_old()
            ph = _param_hash(parameters)
            plan_id = hashlib.sha256(
                f"{command}:{ph}:{time.time()}".encode("utf-8")
            ).hexdigest()[:16]
            now = time.time()
            plan = PendingPlan(
                plan_id=plan_id,
                command=command,
                parameters=deepcopy(parameters),
                param_hash=ph,
                dry_run_result=deepcopy(dry_run_result),
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._plans[plan_id] = plan
            return deepcopy(plan)

    def get(self, plan_id: str) -> PendingPlan | None:
        with self._lock:
            self.expire_old()
            plan = self._plans.get(plan_id)
            return deepcopy(plan) if plan is not None else None

    def discard(self, plan_id: str) -> bool:
        """Remove a plan whose staging transaction did not complete."""
        with self._lock:
            return self._plans.pop(plan_id, None) is not None

    def _get_locked(self, plan_id: str) -> PendingPlan | None:
        self.expire_old()
        return self._plans.get(plan_id)

    def verify(self, plan_id: str, parameters: dict[str, Any]) -> bool:
        """True if plan exists, not expired, not yet consumed, and params match."""
        with self._lock:
            plan = self._get_locked(plan_id)
            if plan is None or plan.is_expired() or not plan.confirmed:
                return False
            return plan.matches(parameters)

    def confirm(self, plan_id: str) -> bool:
        with self._lock:
            plan = self._get_locked(plan_id)
            if plan is None or plan.is_expired():
                return False
            plan.confirmed = True
            return True

    def authorize(
        self,
        plan_id: str,
        *,
        permit_handle: str,
        child_permit_handles: tuple[str, ...] = (),
        node_approval_receipts: dict[str, str] | None = None,
    ) -> str | None:
        """Bind a server-side permit and issue a client confirmation receipt."""
        with self._lock:
            plan = self._get_locked(plan_id)
            if plan is None or plan.is_expired() or not plan.confirmed:
                return None
            receipt = secrets.token_urlsafe(32)
            plan.permit_handle = str(permit_handle)
            plan.child_permit_handles = tuple(str(value) for value in child_permit_handles)
            plan.node_approval_receipts = {
                str(key): str(value)
                for key, value in (node_approval_receipts or {}).items()
            }
            plan.confirmation_digest = hashlib.sha256(receipt.encode("utf-8")).hexdigest()
            return receipt

    def verify_confirmation(self, plan_id: str, receipt: str) -> bool:
        with self._lock:
            plan = self._get_locked(plan_id)
            if (
                plan is None
                or plan.is_expired()
                or not plan.confirmed
                or not plan.permit_handle
                or not plan.confirmation_digest
            ):
                return False
            supplied = hashlib.sha256(str(receipt).encode("utf-8")).hexdigest()
            return hmac.compare_digest(supplied, plan.confirmation_digest)

    def expire_old(self) -> None:
        with self._lock:
            now = time.time()
            self._plans = {
                pid: p for pid, p in self._plans.items() if not p.is_expired(now)
            }
