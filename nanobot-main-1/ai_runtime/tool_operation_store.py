"""Durable operation-state contract for side-effecting product Tools."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from threading import RLock
from time import time
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolOperationRecord:
    tool_id: str
    request_key: str
    fingerprint: str
    operation_fingerprint: str
    state: str
    target_device_id: str = ""
    effect_payload: dict[str, Any] | None = None
    readback_predicate: dict[str, Any] | None = None
    effect_operation_id: str = ""
    dispatch_state: str = "prepared"
    effect_receipt: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class ToolOperationStorePort(Protocol):
    @property
    def durable(self) -> bool: ...
    def get(self, tool_id: str, request_key: str) -> ToolOperationRecord | None: ...
    def begin(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        operation_fingerprint: str = "",
        target_device_id: str = "", effect_payload: dict[str, Any] | None = None,
        readback_predicate: dict[str, Any] | None = None,
        effect_operation_id: str = "",
    ) -> bool: ...
    def complete(
        self, tool_id: str, request_key: str, fingerprint: str,
        result: dict[str, Any],
    ) -> bool: ...
    def mark_unknown(
        self, tool_id: str, request_key: str, fingerprint: str, *, reason: str,
    ) -> bool: ...
    def claim_effect_dispatch(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        effect_operation_id: str,
    ) -> bool: ...
    def record_effect_terminal(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        effect_operation_id: str, result: dict[str, Any],
    ) -> bool: ...
    def reconcile_unknown(
        self, tool_id: str, request_key: str, *, result: dict[str, Any],
        evidence: dict[str, Any],
    ) -> bool: ...
    def unresolved_fingerprints(self) -> frozenset[str]: ...
    def unresolved_records(self) -> tuple[ToolOperationRecord, ...]: ...


class InMemoryToolOperationStore:
    """Test/embedded adapter; product writes require a durable adapter."""

    def __init__(self, *, durable: bool = False) -> None:
        self.durable = bool(durable)
        self._records: dict[tuple[str, str], ToolOperationRecord] = {}
        self._lock = RLock()

    def get(self, tool_id: str, request_key: str) -> ToolOperationRecord | None:
        with self._lock:
            record = self._records.get((str(tool_id), str(request_key)))
            return deepcopy(record)

    def begin(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        operation_fingerprint: str = "",
        target_device_id: str = "", effect_payload: dict[str, Any] | None = None,
        readback_predicate: dict[str, Any] | None = None,
        effect_operation_id: str = "",
    ) -> bool:
        key = (str(tool_id), str(request_key))
        with self._lock:
            requested_effect = str(operation_fingerprint or fingerprint)
            if key in self._records or any(
                record.state in {"started", "unknown"}
                and record.operation_fingerprint == requested_effect
                for record in self._records.values()
            ):
                return False
            self._records[key] = ToolOperationRecord(
                tool_id=key[0], request_key=key[1], fingerprint=str(fingerprint),
                operation_fingerprint=requested_effect,
                state="started", target_device_id=str(target_device_id),
                effect_payload=deepcopy(effect_payload),
                readback_predicate=deepcopy(readback_predicate),
                effect_operation_id=str(effect_operation_id),
            )
            return True

    def complete(
        self, tool_id: str, request_key: str, fingerprint: str,
        result: dict[str, Any],
    ) -> bool:
        return self._finish(tool_id, request_key, fingerprint, "completed", result)

    def mark_unknown(
        self, tool_id: str, request_key: str, fingerprint: str, *, reason: str,
    ) -> bool:
        key = (str(tool_id), str(request_key))
        with self._lock:
            current = self._records.get(key)
            if current is None or current.fingerprint != str(fingerprint):
                return False
            receipt = deepcopy(current.effect_receipt)
            dispatch_state = current.dispatch_state
            if dispatch_state == "prepared" and receipt is None:
                receipt = _not_dispatched_receipt(current, str(reason))
                dispatch_state = "terminal"
            self._records[key] = _replace_record(
                current, state="unknown", dispatch_state=dispatch_state,
                effect_receipt=receipt, result={"reason": str(reason)},
            )
            return True

    def claim_effect_dispatch(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        effect_operation_id: str,
    ) -> bool:
        key = (str(tool_id), str(request_key))
        with self._lock:
            current = self._records.get(key)
            if (
                current is None
                or current.fingerprint != str(fingerprint)
                or current.effect_operation_id != str(effect_operation_id)
                or current.state != "started"
                or current.dispatch_state != "prepared"
            ):
                return False
            self._records[key] = _replace_record(
                current, dispatch_state="dispatch_claimed",
            )
            return True

    def record_effect_terminal(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        effect_operation_id: str, result: dict[str, Any],
    ) -> bool:
        key = (str(tool_id), str(request_key))
        with self._lock:
            current = self._records.get(key)
            if (
                current is None
                or current.fingerprint != str(fingerprint)
                or current.effect_operation_id != str(effect_operation_id)
                or current.dispatch_state != "dispatch_claimed"
                or current.effect_receipt is not None
            ):
                return False
            self._records[key] = _replace_record(
                current, dispatch_state="terminal",
                effect_receipt=_terminal_receipt(current, result),
            )
            return True

    def unresolved_fingerprints(self) -> frozenset[str]:
        with self._lock:
            return frozenset(
                record.operation_fingerprint for record in self._records.values()
                if record.state in {"started", "unknown"}
            )

    def unresolved_records(self) -> tuple[ToolOperationRecord, ...]:
        with self._lock:
            return tuple(
                deepcopy(record) for record in self._records.values()
                if record.state in {"started", "unknown"}
            )

    def reconcile_unknown(
        self, tool_id: str, request_key: str, *, result: dict[str, Any],
        evidence: dict[str, Any],
    ) -> bool:
        key = (str(tool_id), str(request_key))
        with self._lock:
            current = self._records.get(key)
            if current is None or current.state != "unknown":
                return False
            resolved = deepcopy(result)
            resolved.setdefault("data", {})["reconciliation_evidence"] = deepcopy(evidence)
            self._records[key] = ToolOperationRecord(
                tool_id=key[0], request_key=key[1],
                fingerprint=current.fingerprint,
                operation_fingerprint=current.operation_fingerprint,
                state="completed", target_device_id=current.target_device_id,
                effect_payload=deepcopy(current.effect_payload),
                readback_predicate=deepcopy(current.readback_predicate),
                effect_operation_id=current.effect_operation_id,
                dispatch_state=current.dispatch_state,
                effect_receipt=deepcopy(current.effect_receipt),
                result=resolved,
            )
            return True

    def _finish(
        self, tool_id: str, request_key: str, fingerprint: str,
        state: str, result: dict[str, Any],
    ) -> bool:
        key = (str(tool_id), str(request_key))
        with self._lock:
            current = self._records.get(key)
            if (
                current is None
                or current.fingerprint != str(fingerprint)
                or state == "completed" and (
                    current.state != "started"
                    or current.dispatch_state != "terminal"
                    or current.effect_receipt is None
                )
            ):
                return False
            self._records[key] = ToolOperationRecord(
                tool_id=key[0], request_key=key[1], fingerprint=str(fingerprint),
                operation_fingerprint=current.operation_fingerprint, state=state,
                target_device_id=current.target_device_id,
                effect_payload=deepcopy(current.effect_payload),
                readback_predicate=deepcopy(current.readback_predicate),
                effect_operation_id=current.effect_operation_id,
                dispatch_state=current.dispatch_state,
                effect_receipt=deepcopy(current.effect_receipt),
                result=deepcopy(result),
            )
            return True


class UnavailableToolOperationStore(InMemoryToolOperationStore):
    """Fail-closed marker used when product persistence was not composed."""

    def __init__(self) -> None:
        super().__init__(durable=False)


def _replace_record(record: ToolOperationRecord, **changes: Any) -> ToolOperationRecord:
    values = {
        "tool_id": record.tool_id, "request_key": record.request_key,
        "fingerprint": record.fingerprint,
        "operation_fingerprint": record.operation_fingerprint,
        "state": record.state, "target_device_id": record.target_device_id,
        "effect_payload": deepcopy(record.effect_payload),
        "readback_predicate": deepcopy(record.readback_predicate),
        "effect_operation_id": record.effect_operation_id,
        "dispatch_state": record.dispatch_state,
        "effect_receipt": deepcopy(record.effect_receipt),
        "result": deepcopy(record.result),
    }
    values.update(changes)
    return ToolOperationRecord(**values)


def _terminal_receipt(
    record: ToolOperationRecord, result: dict[str, Any],
) -> dict[str, Any]:
    frozen = deepcopy(result)
    return {
        "schema_version": 1,
        "source": "authenticated_application_tool_terminal",
        "effect_operation_id": record.effect_operation_id,
        "operation_fingerprint": record.operation_fingerprint,
        "target_device_id": record.target_device_id,
        "resolution": (
            "confirmed_tool_effect_completed"
            if bool(frozen.get("ok")) else "inconclusive"
        ),
        "terminal_state": str(frozen.get("state", "")),
        "result_hash": hashlib.sha256(json.dumps(
            frozen, sort_keys=True, separators=(",", ":"), default=str,
        ).encode("utf-8")).hexdigest(),
        "observed_at": time(),
    }


def _not_dispatched_receipt(
    record: ToolOperationRecord, reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "operation_store_pre_dispatch_state",
        "effect_operation_id": record.effect_operation_id,
        "operation_fingerprint": record.operation_fingerprint,
        "target_device_id": record.target_device_id,
        "resolution": "confirmed_tool_effect_not_started",
        "terminal_state": "cancelled_before_dispatch",
        "reason": reason,
        "observed_at": time(),
    }
