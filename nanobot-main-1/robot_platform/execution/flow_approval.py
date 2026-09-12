"""One-use, server-owned HumanApproval authority for immutable Flow nodes."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from robot_platform.application.principal import AuthenticatedPrincipal


class FlowApprovalStorePort(Protocol):
    def issue(
        self, *, plan_id: str, node_id: str, snapshot_hash: str,
        principal: AuthenticatedPrincipal,
    ) -> str: ...
    def claim(
        self, receipt: str, *, plan_id: str, node_id: str,
        snapshot_hash: str, principal: AuthenticatedPrincipal,
    ) -> bool: ...
    def revoke_plan(self, plan_id: str) -> None: ...


@dataclass
class _Approval:
    digest: str
    plan_id: str
    node_id: str
    snapshot_hash: str
    principal: AuthenticatedPrincipal
    claimed: bool = False


class FlowApprovalStore:
    def __init__(self) -> None:
        self._records: dict[str, _Approval] = {}
        self._lock = RLock()

    def issue(
        self, *, plan_id: str, node_id: str, snapshot_hash: str,
        principal: AuthenticatedPrincipal,
    ) -> str:
        if not all(str(value).strip() for value in (plan_id, node_id, snapshot_hash)):
            raise ValueError("Flow approval scope is incomplete")
        receipt = secrets.token_urlsafe(32)
        digest = hashlib.sha256(receipt.encode("utf-8")).hexdigest()
        with self._lock:
            self._records[digest] = _Approval(
                digest, str(plan_id), str(node_id), str(snapshot_hash), principal,
            )
        return receipt

    def claim(
        self, receipt: str, *, plan_id: str, node_id: str,
        snapshot_hash: str, principal: AuthenticatedPrincipal,
    ) -> bool:
        digest = hashlib.sha256(str(receipt).encode("utf-8")).hexdigest()
        with self._lock:
            record = self._records.get(digest)
            if (
                record is None or record.claimed
                or record.plan_id != str(plan_id)
                or record.node_id != str(node_id)
                or record.snapshot_hash != str(snapshot_hash)
                or record.principal != principal
            ):
                return False
            record.claimed = True
            return True

    def revoke_plan(self, plan_id: str) -> None:
        with self._lock:
            self._records = {
                digest: record for digest, record in self._records.items()
                if record.plan_id != str(plan_id)
            }
