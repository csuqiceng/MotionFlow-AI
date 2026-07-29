"""Server-side execution permits for safety-critical robot writes."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from robot_platform.application.principal import AuthenticatedPrincipal


class ExecutionPermitState(str, Enum):
    ISSUED = "issued"
    RESERVED = "reserved"
    EXECUTING = "executing"
    CONSUMED = "consumed"
    SKIPPED = "skipped"
    FAILED = "failed"
    EXPIRED = "expired"
    OUTCOME_UNKNOWN = "outcome_unknown"


_DEFINITE_TERMINAL_STATES = frozenset(
    {ExecutionPermitState.CONSUMED, ExecutionPermitState.SKIPPED, ExecutionPermitState.FAILED}
)


@dataclass(frozen=True)
class ExecutionScope:
    """Everything a permit authorizes, excluding secret/opaque handle data."""

    principal: AuthenticatedPrincipal
    robot_id: str
    controller_id: str
    operation_type: str
    payload_hash: str
    payload_schema_version: str
    product_profile_version: str
    capability_version: str
    deployment_instance_id: str
    core_version: str
    plan_id: str
    plan_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "robot_id",
            "controller_id",
            "operation_type",
            "payload_hash",
            "payload_schema_version",
            "product_profile_version",
            "capability_version",
            "deployment_instance_id",
            "core_version",
            "plan_id",
            "plan_version",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"ExecutionScope requires {field_name}")
            object.__setattr__(self, field_name, value)

    @classmethod
    def for_payload(
        cls,
        *,
        principal: AuthenticatedPrincipal,
        robot_id: str,
        controller_id: str,
        operation_type: str,
        payload: dict[str, Any],
        payload_schema_version: str,
        product_profile_version: str,
        capability_version: str,
        deployment_instance_id: str,
        core_version: str,
        plan_id: str,
        plan_version: str,
    ) -> "ExecutionScope":
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return cls(
            principal=principal,
            robot_id=robot_id,
            controller_id=controller_id,
            operation_type=operation_type,
            payload_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            payload_schema_version=payload_schema_version,
            product_profile_version=product_profile_version,
            capability_version=capability_version,
            deployment_instance_id=deployment_instance_id,
            core_version=core_version,
            plan_id=plan_id,
            plan_version=plan_version,
        )

    @property
    def scope_hash(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def execution_identity_hash(self) -> str:
        """Stable identity of one physical plan, independent of login/runtime."""
        identity = {
            "robot_id": self.robot_id,
            "controller_id": self.controller_id,
            "operation_type": self.operation_type,
            "payload_hash": self.payload_hash,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
        }
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FlowStepExecutionGrant:
    """Server-created runtime grant for exactly one immutable Flow step."""

    permit_handle: str
    scope: ExecutionScope
    dispatch_id: str

    def __post_init__(self) -> None:
        if not str(self.permit_handle).strip() or not str(self.dispatch_id).strip():
            raise ValueError("FlowStepExecutionGrant requires handle and dispatch ID")

@dataclass
class ExecutionPermit:
    """Mutable record held only by the trusted server-side permit store."""

    handle: str
    operation_id: str
    idempotency_key: str
    scope_hash: str
    execution_identity_hash: str
    robot_id: str
    controller_id: str
    issued_at: float
    expires_at: float
    state: ExecutionPermitState = ExecutionPermitState.ISSUED
    result: dict[str, Any] | None = None
    claimed_dispatch_ids: list[str] = field(default_factory=list)
    requires_dispatch_claim: bool = True
    updated_at: float = field(default_factory=time.time)


class ExecutionPermitStore:
    """Thread-safe permit state machine with optional crash-safe persistence."""

    def __init__(
        self, *, ttl_sec: float = 300.0, storage_path: str | Path | None = None
    ) -> None:
        if ttl_sec <= 0:
            raise ValueError("ExecutionPermitStore ttl_sec must be positive")
        self._ttl_sec = float(ttl_sec)
        self._permits: dict[str, ExecutionPermit] = {}
        self._idempotency_index: dict[str, str] = {}
        self._execution_identity_index: dict[str, str] = {}
        self._lock = threading.RLock()
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._process_lock_stream: Any = None
        with self._lock:
            try:
                self._acquire_process_lock_locked()
                self._load_locked()
            except BaseException:
                # Construction may fail on corrupt/incompatible persisted data.
                # Never retain the process-wide ownership lock in that case.
                self.close()
                raise

    def close(self) -> None:
        with self._lock:
            stream = self._process_lock_stream
            if stream is None:
                return
            try:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
                self._process_lock_stream = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def issue(
        self,
        scope: ExecutionScope,
        *,
        operation_id: str,
        idempotency_key: str,
        requires_dispatch_claim: bool = True,
        now: float | None = None,
    ) -> ExecutionPermit:
        operation_id = str(operation_id).strip()
        idempotency_key = str(idempotency_key).strip()
        if not operation_id or not idempotency_key:
            raise ValueError("operation_id and idempotency_key are required")
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            existing_handle = self._idempotency_index.get(idempotency_key)
            if existing_handle is not None:
                existing = self._permits[existing_handle]
                if existing.scope_hash != scope.scope_hash:
                    raise ValueError("idempotency key is already bound to another execution scope")
                return _snapshot(existing)
            identity_handle = self._execution_identity_index.get(scope.execution_identity_hash)
            if identity_handle is not None:
                existing = self._permits[identity_handle]
                raise ValueError(
                    "physical execution identity already has a permit; create a new plan/version "
                    f"after reconciling state '{existing.state.value}'"
                )
            unresolved = next(
                (
                    permit
                    for permit in self._permits.values()
                    if permit.robot_id == scope.robot_id
                    and permit.controller_id == scope.controller_id
                    and permit.state
                    in {
                        ExecutionPermitState.RESERVED,
                        ExecutionPermitState.EXECUTING,
                        ExecutionPermitState.OUTCOME_UNKNOWN,
                    }
                ),
                None,
            )
            if unresolved is not None:
                raise ValueError(
                    "controller has an unresolved execution; reconcile operation "
                    f"'{unresolved.operation_id}' before issuing another permit"
                )
            record = ExecutionPermit(
                handle=secrets.token_urlsafe(32),
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                scope_hash=scope.scope_hash,
                execution_identity_hash=scope.execution_identity_hash,
                robot_id=scope.robot_id,
                controller_id=scope.controller_id,
                issued_at=timestamp,
                expires_at=timestamp + self._ttl_sec,
                requires_dispatch_claim=bool(requires_dispatch_claim),
                updated_at=timestamp,
            )
            self._permits[record.handle] = record
            self._idempotency_index[idempotency_key] = record.handle
            self._execution_identity_index[record.execution_identity_hash] = record.handle
            self._persist_locked()
            return _snapshot(record)

    def get(self, handle: str, *, now: float | None = None) -> ExecutionPermit | None:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            record = self._permits.get(handle)
            if record is None:
                return None
            self._expire_if_needed(record, timestamp)
            return _snapshot(record)

    def reserve(
        self,
        handle: str,
        scope: ExecutionScope,
        *,
        now: float | None = None,
    ) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            record = self._permits.get(handle)
            if record is None:
                return False
            self._expire_if_needed(record, timestamp)
            if record.scope_hash != scope.scope_hash:
                return False
            if record.state is not ExecutionPermitState.ISSUED:
                return False
            self._transition(record, ExecutionPermitState.RESERVED, timestamp)
            return True

    def claim_dispatch(
        self,
        handle: str,
        scope: ExecutionScope,
        *,
        dispatch_id: str,
        operation_type: str,
        payload: dict[str, Any],
    ) -> bool:
        """Atomically claim one exact backend write dispatch."""
        dispatch_id = str(dispatch_id).strip()
        if not dispatch_id:
            return False
        reconstructed = ExecutionScope.for_payload(
            principal=scope.principal,
            robot_id=scope.robot_id,
            controller_id=scope.controller_id,
            operation_type=operation_type,
            payload=payload,
            payload_schema_version=scope.payload_schema_version,
            product_profile_version=scope.product_profile_version,
            capability_version=scope.capability_version,
            deployment_instance_id=scope.deployment_instance_id,
            core_version=scope.core_version,
            plan_id=scope.plan_id,
            plan_version=scope.plan_version,
        )
        if reconstructed.scope_hash != scope.scope_hash:
            return False
        with self._lock:
            record = self._permits.get(str(handle))
            if (
                record is None
                or record.state is not ExecutionPermitState.EXECUTING
                or record.scope_hash != reconstructed.scope_hash
                or dispatch_id in record.claimed_dispatch_ids
            ):
                return False
            record.claimed_dispatch_ids.append(dispatch_id)
            record.updated_at = time.time()
            self._persist_locked()
            return True

    def mark_executing(self, handle: str, *, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            record = self._permits.get(handle)
            if record is None or record.state is not ExecutionPermitState.RESERVED:
                return False
            if timestamp >= record.expires_at:
                self._transition(record, ExecutionPermitState.EXPIRED, timestamp)
                return False
            self._transition(record, ExecutionPermitState.EXECUTING, timestamp)
            return True

    def complete(
        self,
        handle: str,
        result: dict[str, Any],
        *,
        now: float | None = None,
    ) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            record = self._permits.get(handle)
            if record is None or record.state is not ExecutionPermitState.EXECUTING:
                return False
            if record.requires_dispatch_claim and not record.claimed_dispatch_ids:
                return False
            self._transition(record, ExecutionPermitState.CONSUMED, timestamp)
            record.result = deepcopy(result)
            self._persist_locked()
            return True

    def abort_before_dispatch(
        self,
        handle: str,
        *,
        reason: str,
        audit_id: str = "",
        now: float | None = None,
    ) -> bool:
        """Fail a reservation only when no SDK write was dispatched."""
        return self._finish(
            handle,
            expected=ExecutionPermitState.RESERVED,
            target=ExecutionPermitState.FAILED,
            result={
                "reason": str(reason),
                "audit_id": str(audit_id),
                "write_dispatched": False,
            },
            now=now,
        )

    def skip_unstarted(
        self,
        handle: str,
        *,
        reason: str,
        now: float | None = None,
    ) -> bool:
        """Atomically retire an unselected Flow child without dispatch rights."""
        return self._finish(
            handle,
            expected=ExecutionPermitState.ISSUED,
            target=ExecutionPermitState.SKIPPED,
            result={
                "reason": str(reason),
                "write_dispatched": False,
                "skipped": True,
            },
            now=now,
        )

    def fail_with_controller_evidence(
        self,
        handle: str,
        result: dict[str, Any],
        *,
        controller_operation_id: str,
        controller_evidence: str,
        audit_id: str,
        now: float | None = None,
    ) -> bool:
        """Record a definite controller failure after SDK dispatch.

        Callers must use ``mark_outcome_unknown`` when they cannot prove that
        the controller rejected or failed the operation.
        """
        if not all(
            str(value).strip()
            for value in (controller_operation_id, controller_evidence, audit_id)
        ):
            raise ValueError("definite controller failure requires operation, evidence, and audit IDs")
        evidence_result = deepcopy(result)
        evidence_result.update(
            {
                "controller_operation_id": str(controller_operation_id),
                "controller_evidence": str(controller_evidence),
                "audit_id": str(audit_id),
                "write_dispatched": True,
            }
        )
        return self._finish(
            handle,
            expected=ExecutionPermitState.EXECUTING,
            target=ExecutionPermitState.FAILED,
            result=evidence_result,
            now=now,
        )

    def mark_outcome_unknown(
        self,
        handle: str,
        *,
        reason: str,
        now: float | None = None,
    ) -> bool:
        return self._finish(
            handle,
            expected=ExecutionPermitState.EXECUTING,
            target=ExecutionPermitState.OUTCOME_UNKNOWN,
            result={"reason": str(reason)},
            now=now,
        )

    def reconcile_unknown(
        self,
        handle: str,
        *,
        succeeded: bool,
        controller_operation_id: str,
        controller_evidence: str,
        audit_id: str,
        result: dict[str, Any],
        now: float | None = None,
    ) -> bool:
        """Record a proven outcome without dispatching another SDK write."""
        if not all(
            str(value).strip()
            for value in (controller_operation_id, controller_evidence, audit_id)
        ):
            raise ValueError("reconciliation requires operation, evidence, and audit IDs")
        reconciled = deepcopy(result)
        reconciled.update(
            {
                "controller_operation_id": str(controller_operation_id),
                "controller_evidence": str(controller_evidence),
                "audit_id": str(audit_id),
                "reconciled": True,
            }
        )
        return self._finish(
            handle,
            expected=ExecutionPermitState.OUTCOME_UNKNOWN,
            target=(ExecutionPermitState.CONSUMED if succeeded else ExecutionPermitState.FAILED),
            result=reconciled,
            now=now,
        )

    def definite_result_for_idempotency_key(
        self, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self._lock:
            handle = self._idempotency_index.get(str(idempotency_key))
            record = self._permits.get(handle) if handle is not None else None
            if record is None or record.state not in _DEFINITE_TERMINAL_STATES:
                return None
            return deepcopy(record.result or {})

    def definite_result_for_exact_execution(
        self,
        handle: str,
        idempotency_key: str,
        expected_scope: ExecutionScope,
    ) -> dict[str, Any] | None:
        """Return a terminal result only for the exact handle/key/scope tuple."""
        with self._lock:
            record = self._permits.get(str(handle))
            if (
                record is None
                or record.idempotency_key != str(idempotency_key)
                or record.scope_hash != expected_scope.scope_hash
                or record.execution_identity_hash
                != expected_scope.execution_identity_hash
                or record.state not in _DEFINITE_TERMINAL_STATES
            ):
                return None
            return deepcopy(record.result or {})

    def _transition_from(
        self,
        handle: str,
        *,
        expected: ExecutionPermitState,
        target: ExecutionPermitState,
        now: float | None,
    ) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            record = self._permits.get(handle)
            if record is None or record.state is not expected:
                return False
            self._transition(record, target, timestamp)
            return True

    def _finish(
        self,
        handle: str,
        *,
        expected: ExecutionPermitState,
        target: ExecutionPermitState,
        result: dict[str, Any],
        now: float | None,
    ) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            record = self._permits.get(handle)
            if record is None or record.state is not expected:
                return False
            self._transition(record, target, timestamp)
            record.result = deepcopy(result)
            self._persist_locked()
            return True

    def _expire_if_needed(self, record: ExecutionPermit, now: float) -> None:
        if record.state is ExecutionPermitState.ISSUED and now >= record.expires_at:
            self._transition(record, ExecutionPermitState.EXPIRED, now)

    def _transition(
        self, record: ExecutionPermit, target: ExecutionPermitState, now: float
    ) -> None:
        record.state = target
        record.updated_at = now
        self._persist_locked()

    def _load_locked(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        recovered = False
        for item in raw.get("permits", []):
            data = dict(item)
            data["state"] = ExecutionPermitState(data["state"])
            record = ExecutionPermit(**data)
            if record.state in {
                ExecutionPermitState.RESERVED,
                ExecutionPermitState.EXECUTING,
            }:
                record.state = ExecutionPermitState.OUTCOME_UNKNOWN
                record.result = {"reason": "process_restarted_during_execution"}
                record.updated_at = time.time()
                recovered = True
            self._permits[record.handle] = record
            self._idempotency_index[record.idempotency_key] = record.handle
            self._execution_identity_index[record.execution_identity_hash] = record.handle
        if recovered:
            self._persist_locked()

    def _persist_locked(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "permits": [
                {**asdict(record), "state": record.state.value}
                for record in self._permits.values()
            ],
        }
        temporary = self._storage_path.with_name(
            f".{self._storage_path.name}.{secrets.token_hex(8)}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._storage_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _acquire_process_lock_locked(self) -> None:
        if self._storage_path is None:
            return
        lock_path = self._storage_path.with_suffix(self._storage_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = lock_path.open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError(
                f"robot runtime is already owned by another server: {lock_path}"
            ) from exc
        self._process_lock_stream = stream


def _snapshot(record: ExecutionPermit) -> ExecutionPermit:
    return replace(
        record,
        result=deepcopy(record.result),
        claimed_dispatch_ids=list(record.claimed_dispatch_ids),
    )


class ExecutionPermitVerifierPort(Protocol):
    """Backend-facing port exposing only an atomic, one-use claim."""

    def claim_dispatch(
        self,
        handle: str,
        scope: ExecutionScope,
        *,
        dispatch_id: str,
        operation_type: str,
        payload: dict[str, Any],
    ) -> bool: ...
