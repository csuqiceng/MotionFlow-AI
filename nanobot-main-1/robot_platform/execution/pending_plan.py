from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
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
    confirmed: bool = False

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) > self.expires_at

    def matches(self, parameters: dict[str, Any]) -> bool:
        return _param_hash(parameters) == self.param_hash


class PendingPlanStore:
    """In-memory pending-plan store. POC: lost on restart."""

    def __init__(self, ttl_sec: float = 300.0) -> None:
        self._ttl = ttl_sec
        self._plans: dict[str, PendingPlan] = {}

    def create(
        self,
        *,
        command: str,
        parameters: dict[str, Any],
        dry_run_result: dict[str, Any],
    ) -> PendingPlan:
        self.expire_old()
        ph = _param_hash(parameters)
        plan_id = hashlib.sha256(
            f"{command}:{ph}:{time.time()}".encode("utf-8")
        ).hexdigest()[:16]
        now = time.time()
        plan = PendingPlan(
            plan_id=plan_id,
            command=command,
            parameters=dict(parameters),
            param_hash=ph,
            dry_run_result=dry_run_result,
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._plans[plan_id] = plan
        return plan

    def get(self, plan_id: str) -> PendingPlan | None:
        self.expire_old()
        return self._plans.get(plan_id)

    def verify(self, plan_id: str, parameters: dict[str, Any]) -> bool:
        """True if plan exists, not expired, not yet consumed, and params match."""
        plan = self.get(plan_id)
        if plan is None or plan.is_expired() or not plan.confirmed:
            return False
        return plan.matches(parameters)

    def confirm(self, plan_id: str) -> bool:
        plan = self.get(plan_id)
        if plan is None or plan.is_expired():
            return False
        plan.confirmed = True
        return True

    def expire_old(self) -> None:
        now = time.time()
        self._plans = {
            pid: p for pid, p in self._plans.items() if not p.is_expired(now)
        }
