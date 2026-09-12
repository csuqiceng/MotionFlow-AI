"""Crash-safe, authenticated Tool operation/idempotency state."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from ai_runtime.tool_operation_store import (
    ToolOperationRecord,
    _not_dispatched_receipt,
    _terminal_receipt,
)
from robot_platform.library.storage import atomic_write_json


class JsonToolOperationStore:
    """One authenticated state machine shared safely by multiple processes."""

    durable = True

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._lock = RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._generation = 0
        with self._transaction():
            pass

    def get(self, tool_id: str, request_key: str) -> ToolOperationRecord | None:
        with self._transaction():
            raw = self._records.get(_key(tool_id, request_key))
            return _record(raw) if raw is not None else None

    def begin(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        operation_fingerprint: str = "",
        target_device_id: str = "", effect_payload: dict[str, Any] | None = None,
        readback_predicate: dict[str, Any] | None = None,
        effect_operation_id: str = "",
    ) -> bool:
        storage_key = _key(tool_id, request_key)
        if not str(effect_operation_id).strip():
            return False
        with self._transaction():
            requested_effect = str(operation_fingerprint or fingerprint)
            if storage_key in self._records or any(
                raw.get("state") in {"started", "unknown"}
                and str(raw.get("operation_fingerprint") or "*") == requested_effect
                for raw in self._records.values()
            ):
                return False
            self._records[storage_key] = {
                "tool_id": str(tool_id), "request_key": str(request_key),
                "fingerprint": str(fingerprint),
                "operation_fingerprint": requested_effect,
                "target_device_id": str(target_device_id),
                "effect_payload": deepcopy(effect_payload),
                "readback_predicate": deepcopy(readback_predicate),
                "effect_operation_id": str(effect_operation_id),
                "owner_pid": os.getpid(),
                "dispatch_state": "prepared", "effect_receipt": None,
                "state": "started", "result": None,
            }
            self._persist_locked()
            return True

    def claim_effect_dispatch(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        effect_operation_id: str,
    ) -> bool:
        with self._transaction():
            raw = self._matching(
                tool_id, request_key, fingerprint, effect_operation_id,
            )
            if (
                raw is None or raw.get("state") != "started"
                or raw.get("dispatch_state") != "prepared"
            ):
                return False
            raw["dispatch_state"] = "dispatch_claimed"
            self._persist_locked()
            return True

    def record_effect_terminal(
        self, tool_id: str, request_key: str, fingerprint: str, *,
        effect_operation_id: str, result: dict[str, Any],
    ) -> bool:
        with self._transaction():
            raw = self._matching(
                tool_id, request_key, fingerprint, effect_operation_id,
            )
            if (
                raw is None
                or raw.get("dispatch_state") != "dispatch_claimed"
                or raw.get("effect_receipt") is not None
                or raw.get("state") not in {"started", "unknown"}
            ):
                return False
            raw["dispatch_state"] = "terminal"
            raw["effect_receipt"] = _terminal_receipt(_record(raw), result)
            self._persist_locked()
            return True

    def complete(
        self, tool_id: str, request_key: str, fingerprint: str,
        result: dict[str, Any],
    ) -> bool:
        return self._finish(tool_id, request_key, fingerprint, "completed", result)

    def mark_unknown(
        self, tool_id: str, request_key: str, fingerprint: str, *, reason: str,
    ) -> bool:
        with self._transaction():
            raw = self._matching(tool_id, request_key, fingerprint)
            if raw is None or raw.get("state") not in {"started", "unknown"}:
                return False
            if (
                raw.get("dispatch_state", "prepared") == "prepared"
                and raw.get("effect_receipt") is None
            ):
                record = _record(raw)
                raw["dispatch_state"] = "terminal"
                raw["effect_receipt"] = _not_dispatched_receipt(record, str(reason))
            raw["state"] = "unknown"
            raw["result"] = {"reason": str(reason)}
            self._persist_locked()
            return True

    def unresolved_fingerprints(self) -> frozenset[str]:
        with self._transaction():
            return frozenset(
                str(raw.get("operation_fingerprint") or "*")
                for raw in self._records.values()
                if raw.get("state") in {"started", "unknown"}
            )

    def unresolved_records(self) -> tuple[ToolOperationRecord, ...]:
        with self._transaction():
            return tuple(
                _record(raw) for raw in self._records.values()
                if raw.get("state") in {"started", "unknown"}
            )

    def reconcile_unknown(
        self, tool_id: str, request_key: str, *, result: dict[str, Any],
        evidence: dict[str, Any], audit_outbox: dict[str, Any] | None = None,
    ) -> bool:
        with self._transaction():
            raw = self._records.get(_key(tool_id, request_key))
            if raw is None or raw.get("state") != "unknown":
                return False
            receipt = raw.get("effect_receipt")
            if (
                not isinstance(receipt, dict)
                or evidence.get("effect_receipt_hash") != _object_hash(receipt)
                or evidence.get("resolution") != receipt.get("resolution")
            ):
                return False
            resolved = deepcopy(result)
            resolved.setdefault("data", {})["reconciliation_evidence"] = deepcopy(evidence)
            if audit_outbox is not None:
                if not str(audit_outbox.get("audit_id", "")).strip():
                    return False
                resolved["data"]["reconciliation_audit_outbox"] = {
                    "pending": True,
                    "event": deepcopy(audit_outbox),
                }
            raw["state"] = "completed"
            raw["result"] = resolved
            self._persist_locked()
            return True

    def release_unknown_after_execution_recovery(
        self, *, effect_operation_id: str, target_device_id: str,
        result: dict[str, Any], evidence: dict[str, Any],
    ) -> int:
        released = 0
        with self._transaction():
            for raw in self._records.values():
                if (
                    raw.get("state") != "unknown"
                    or raw.get("effect_operation_id") != str(effect_operation_id)
                    or raw.get("target_device_id") != str(target_device_id)
                ):
                    continue
                resolved = deepcopy(result)
                resolved.setdefault("data", {})["execution_recovery_evidence"] = deepcopy(evidence)
                raw["state"] = "completed"
                raw["result"] = resolved
                released += 1
            if released:
                self._persist_locked()
        return released

    def pending_reconciliation_audits(self) -> tuple[dict[str, Any], ...]:
        """Return authenticated final-audit outbox items, including their store keys."""
        with self._transaction():
            pending: list[dict[str, Any]] = []
            upgraded = False
            for raw in self._records.values():
                result = raw.get("result")
                data = result.get("data") if isinstance(result, dict) else None
                outbox = data.get("reconciliation_audit_outbox") if isinstance(data, dict) else None
                if outbox is None:
                    legacy_event = _legacy_reconciliation_audit_event(raw)
                    if legacy_event is not None:
                        outbox = {"pending": True, "event": legacy_event}
                        data["reconciliation_audit_outbox"] = outbox
                        upgraded = True
                event = outbox.get("event") if isinstance(outbox, dict) else None
                if (
                    isinstance(outbox, dict)
                    and outbox.get("pending") is True
                    and isinstance(event, dict)
                ):
                    pending.append({
                        "tool_id": str(raw.get("tool_id", "")),
                        "request_key": str(raw.get("request_key", "")),
                        "event": deepcopy(event),
                    })
            if upgraded:
                self._persist_locked()
            return tuple(pending)

    def acknowledge_reconciliation_audit(
        self, tool_id: str, request_key: str, audit_id: str,
    ) -> bool:
        """Atomically mark one append-once audit outbox item as delivered."""
        with self._transaction():
            raw = self._records.get(_key(tool_id, request_key))
            result = raw.get("result") if isinstance(raw, dict) else None
            data = result.get("data") if isinstance(result, dict) else None
            outbox = data.get("reconciliation_audit_outbox") if isinstance(data, dict) else None
            event = outbox.get("event") if isinstance(outbox, dict) else None
            if (
                not isinstance(event, dict)
                or event.get("audit_id") != str(audit_id)
            ):
                return False
            if outbox.get("pending") is not True:
                return True
            outbox["pending"] = False
            self._persist_locked()
            return True

    def _finish(
        self, tool_id: str, request_key: str, fingerprint: str,
        state: str, result: dict[str, Any],
    ) -> bool:
        with self._transaction():
            raw = self._matching(tool_id, request_key, fingerprint)
            if (
                raw is None
                or state == "completed" and (
                    raw.get("state") != "started"
                    or raw.get("dispatch_state") != "terminal"
                    or raw.get("effect_receipt") is None
                )
            ):
                return False
            raw["state"] = state
            raw["result"] = deepcopy(result)
            self._persist_locked()
            return True

    def _matching(
        self, tool_id: str, request_key: str, fingerprint: str,
        effect_operation_id: str | None = None,
    ) -> dict[str, Any] | None:
        raw = self._records.get(_key(tool_id, request_key))
        if raw is None or raw.get("fingerprint") != str(fingerprint):
            return None
        if (
            effect_operation_id is not None
            and raw.get("effect_operation_id") != str(effect_operation_id)
        ):
            return None
        return raw

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with _process_lock(self._path):
            with self._lock:
                self._load_locked()
                if self._recover_abandoned_locked():
                    self._persist_locked()
                yield

    def _recover_abandoned_locked(self) -> bool:
        recovered = False
        for raw in self._records.values():
            if (
                raw.get("state") != "started"
                or _process_is_alive(raw.get("owner_pid"))
            ):
                continue
            raw["state"] = "unknown"
            raw["result"] = {
                "reason": "runtime_restarted_during_tool_execution",
            }
            if (
                raw.get("dispatch_state", "prepared") == "prepared"
                and raw.get("effect_receipt") is None
            ):
                record = _record(raw)
                raw["dispatch_state"] = "terminal"
                raw["effect_receipt"] = _not_dispatched_receipt(
                    record, "runtime_restarted_before_dispatch_claim",
                )
            recovered = True
        return recovered

    def _load_locked(self) -> None:
        if not self._path.exists():
            key = self._integrity_key()
            head = self._load_head(key)
            if head is not None and not (
                int(head.get("generation", -1)) == 0
                and head.get("store_hash") == self._empty_store_hash()
            ):
                raise ValueError("Tool operation store was deleted or rolled back")
            self._records = {}
            self._generation = 0
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Tool operation store is unreadable") from exc
        if not isinstance(payload, dict):
            raise ValueError("Tool operation store schema is invalid")
        if payload.get("schema_version") != 3 or not isinstance(payload.get("records"), dict):
            if payload.get("schema_version") in {1, 2}:
                raise ValueError(
                    "Unsigned or unsealed Tool operation state requires explicit offline migration"
                )
            raise ValueError("Tool operation store schema is invalid")
        stored_mac = str(payload.get("_integrity_mac", ""))
        unsigned = dict(payload)
        unsigned.pop("_integrity_mac", None)
        key = self._integrity_key()
        expected = hmac.new(
            key, _canonical_json(unsigned).encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        if (
            payload.get("_integrity_alg") != "hmac-sha256"
            or payload.get("_integrity_key_id") != hashlib.sha256(key).hexdigest()[:16]
            or not hmac.compare_digest(stored_mac, expected)
        ):
            raise ValueError("Tool operation store integrity verification failed")
        try:
            generation = int(payload["generation"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Tool operation store generation is invalid") from exc
        if generation < 1:
            raise ValueError("Tool operation store generation is invalid")
        store_hash = _object_hash(payload)
        head = self._load_head(key)
        if head is None:
            raise ValueError("Tool operation sealed head is unavailable")
        head_generation = int(head.get("generation", -1))
        if generation == head_generation:
            if head.get("store_hash") != store_hash:
                raise ValueError("Tool operation store does not match its sealed head")
        elif generation == head_generation + 1:
            # A valid store exactly one generation ahead is the only safe
            # crash window: atomic store replace completed before head seal.
            self._write_head(key, generation, store_hash)
        else:
            raise ValueError("Tool operation store rollback was detected")
        self._records = deepcopy(payload["records"])
        self._generation = generation

    def _persist_locked(self) -> None:
        key = self._integrity_key()
        if self._generation == 0 and self._load_head(key) is None:
            self._write_head(key, 0, self._empty_store_hash())
        generation = self._generation + 1
        payload: dict[str, Any] = {
            "schema_version": 3,
            "generation": generation,
            "records": _with_readable_timestamps(self._records),
            "_integrity_alg": "hmac-sha256",
            "_integrity_key_id": hashlib.sha256(key).hexdigest()[:16],
        }
        payload["_integrity_mac"] = hmac.new(
            key, _canonical_json(payload).encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        atomic_write_json(self._path, payload)
        self._write_head(key, generation, _object_hash(payload))
        self._generation = generation

    def _integrity_key(self) -> bytes:
        configured = os.environ.get("MOTIONFLOW_TOOL_OPERATION_KEY_PATH", "").strip()
        path = (
            Path(os.path.expanduser(configured)).resolve() if configured else
            (self._path.parent.parent / ".motionflow-secrets" /
             f"tool-operation-{hashlib.sha256(str(self._path.parent).encode()).hexdigest()[:16]}.key").resolve()
        )
        try:
            path.relative_to(self._path.parent)
        except ValueError:
            pass
        else:
            raise ValueError("Tool operation integrity key must be outside the data directory")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, {"schema_version": 1, "key": secrets.token_hex(32)})
            try:
                path.chmod(0o600)
            except OSError:
                pass
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            key = bytes.fromhex(str(raw.get("key", "")))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Tool operation integrity key is invalid") from exc
        if len(key) < 32:
            raise ValueError("Tool operation integrity key is too short")
        return key

    def _head_path(self) -> Path:
        digest = hashlib.sha256(str(self._path.parent).encode()).hexdigest()[:16]
        return (
            self._path.parent.parent / ".motionflow-secrets" /
            f"tool-operation-{digest}.head.json"
        ).resolve()

    def _empty_store_hash(self) -> str:
        return hashlib.sha256(
            f"absent:{self._path}".encode("utf-8")
        ).hexdigest()

    def _load_head(self, key: bytes) -> dict[str, Any] | None:
        path = self._head_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            stored_mac = str(payload.pop("_integrity_mac"))
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Tool operation sealed head is invalid") from exc
        expected = hmac.new(
            key, _canonical_json(payload).encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        if (
            payload.get("schema_version") != 1
            or payload.get("store_path_hash") != hashlib.sha256(
                str(self._path).encode()
            ).hexdigest()
            or not hmac.compare_digest(stored_mac, expected)
        ):
            raise ValueError("Tool operation sealed head integrity failed")
        return payload

    def _write_head(self, key: bytes, generation: int, store_hash: str) -> None:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "store_path_hash": hashlib.sha256(str(self._path).encode()).hexdigest(),
            "generation": int(generation),
            "store_hash": str(store_hash),
        }
        payload["_integrity_mac"] = hmac.new(
            key, _canonical_json(payload).encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        path = self._head_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, payload)


@contextmanager
def _process_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _legacy_reconciliation_audit_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Backfill the outbox for records written before durable delivery existed."""
    result = raw.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    evidence = data.get("reconciliation_evidence") if isinstance(data, dict) else None
    if (
        raw.get("state") != "completed"
        or not isinstance(result, dict)
        or result.get("state") not in {
            "tool_effect_reconciled_completed",
            "tool_effect_reconciled_not_started",
        }
        or not isinstance(evidence, dict)
    ):
        return None
    tool_id = str(raw.get("tool_id", ""))
    request_key = str(raw.get("request_key", ""))
    resolution = str(evidence.get("resolution", ""))
    digest = hashlib.sha256(
        "\x1f".join((tool_id, request_key, resolution, "completed")).encode("utf-8")
    ).hexdigest()
    return {
        "audit_id": f"tool-reconciliation-completed-{digest[:32]}",
        "action": "tool_operation_reconciled",
        "actor": f"engineer:{evidence.get('engineer', 'unknown')}",
        "tool_id": tool_id,
        "request_key_hash": hashlib.sha256(request_key.encode()).hexdigest(),
        "resolution": resolution,
        "evidence": deepcopy(evidence),
        "timestamp": str(evidence.get("observed_at", "")),
    }


def _key(tool_id: str, request_key: str) -> str:
    return f"{str(tool_id)}\u001f{str(request_key)}"


def _record(raw: dict[str, Any]) -> ToolOperationRecord:
    return ToolOperationRecord(
        tool_id=str(raw["tool_id"]), request_key=str(raw["request_key"]),
        fingerprint=str(raw["fingerprint"]),
        operation_fingerprint=str(raw.get("operation_fingerprint") or raw["fingerprint"]),
        state=str(raw["state"]), target_device_id=str(raw.get("target_device_id", "")),
        effect_payload=deepcopy(raw.get("effect_payload")),
        readback_predicate=deepcopy(raw.get("readback_predicate")),
        effect_operation_id=str(raw.get("effect_operation_id", "")),
        dispatch_state=str(raw.get("dispatch_state", "prepared")),
        effect_receipt=deepcopy(raw.get("effect_receipt")),
        result=deepcopy(raw.get("result")),
    )


def _with_readable_timestamps(value: Any) -> Any:
    """Add display-only UTC values without changing durable numeric timestamps."""
    if isinstance(value, dict):
        rendered = {
            str(key): _with_readable_timestamps(item)
            for key, item in value.items()
        }
        observed_at = rendered.get("observed_at")
        if isinstance(observed_at, (int, float)) and not isinstance(observed_at, bool):
            rendered["observed_at_iso"] = datetime.fromtimestamp(
                observed_at, tz=timezone.utc,
            ).isoformat()
        return rendered
    if isinstance(value, list):
        return [_with_readable_timestamps(item) for item in value]
    return deepcopy(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _object_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _process_is_alive(value: Any) -> bool:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True
