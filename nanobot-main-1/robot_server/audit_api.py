"""Engineer-visible audit log projection for the robot platform."""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from robot_platform.library.migration import (
    AuditIntegrityError, _audit_append_once, read_verified_audit_records,
)
from robot_server.identity_api import RobotIdentityService


class RobotAuditService:
    def __init__(
        self, data_dir: Path, identity: RobotIdentityService,
        *, tool_operation_store: Any = None, platform: Any = None,
    ) -> None:
        self._audit_path = data_dir / "audit.jsonl"
        self._identity = identity
        self._tool_operation_store = tool_operation_store
        self._platform = platform
        self._drain_reconciliation_audit_outbox()

    def list(self, token: str, *, limit: str = "50", before: str = "") -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        self._drain_reconciliation_audit_outbox()
        try:
            page_size = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            return _invalid("limit must be an integer")
        cursor = _decode_cursor(before)
        if before and cursor is None:
            return _invalid("malformed audit cursor")
        try:
            entries = sorted(
                read_verified_audit_records(self._audit_path),
                key=_sort_key, reverse=True,
            )
        except AuditIntegrityError:
            return 503, {"error": {
                "code": "audit_integrity_failed",
                "message": "Audit integrity verification failed.",
            }}
        if cursor is not None:
            entries = [entry for entry in entries if _sort_key(entry) < cursor]
        page = entries[:page_size]
        next_cursor = _encode_cursor(_sort_key(page[-1])) if len(entries) > len(page) else None
        return 200, {"ok": True, "data": {"items": page, "next": next_cursor}}

    def list_unresolved_tool_operations(
        self, token: str,
    ) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if self._tool_operation_store is None:
            return 503, {"error": {"code": "tool_operation_store_unavailable"}}
        self._drain_reconciliation_audit_outbox()
        try:
            records = self._tool_operation_store.unresolved_records()
        except (OSError, ValueError):
            return 503, {"error": {"code": "tool_operation_store_integrity_failed"}}
        items = [{
            "tool_id": record.tool_id,
            "request_key": record.request_key,
            "state": record.state,
            "operation_fingerprint": record.operation_fingerprint,
        } for record in records]
        return 200, {"ok": True, "data": {"items": items}}

    def reconcile_tool_operation(
        self, token: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("request body must be an object")
        tool_id = str(body.get("tool_id", "")).strip()
        request_key = str(body.get("request_key", "")).strip()
        resolution = str(body.get("resolution", "")).strip()
        notes = str(body.get("notes", "")).strip()
        if not tool_id or not request_key or resolution not in {
            "confirmed_tool_effect_completed",
            "confirmed_tool_effect_not_started",
        } or not notes:
            return _invalid(
                "tool_id, request_key, notes and a supported resolution are required"
            )
        if self._tool_operation_store is None or self._platform is None:
            return 503, {"error": {"code": "tool_reconciliation_unavailable"}}
        try:
            record = self._tool_operation_store.get(tool_id, request_key)
        except (OSError, ValueError):
            return 503, {"error": {"code": "tool_operation_store_integrity_failed"}}
        if record is None:
            return 409, {"error": {
                "code": "tool_operation_not_reconcilable",
                "message": "The Tool effect operation does not exist.",
            }}
        execution_context = self._platform.execution_context()
        controller_id = str(execution_context.get("controller_id", ""))
        if not controller_id or controller_id != record.target_device_id:
            return 409, {"error": {
                "code": "tool_reconciliation_device_mismatch",
                "message": "The operation belongs to another controller.",
            }}
        if record.state == "completed" and _is_reconciled_result(record.result):
            stored_evidence = record.result["data"]["reconciliation_evidence"]
            if stored_evidence.get("resolution") != resolution:
                return 409, {"error": {
                    "code": "tool_reconciliation_resolution_mismatch",
                    "message": "Requested resolution contradicts the stored reconciliation.",
                }}
            return self._finish_reconciliation_audit(
                tool_id, request_key, record.result, stored_evidence,
            )
        if record.state != "unknown":
            return 409, {"error": {
                "code": "tool_operation_not_reconcilable",
                "message": "The operation is not in an unknown state.",
            }}
        observed_at = datetime.now(timezone.utc).isoformat()
        proven_resolution = _prove_tool_resolution(record)
        if proven_resolution is None:
            return 422, {"error": {
                "code": "tool_reconciliation_evidence_inconclusive",
                "message": "The authenticated Tool effect receipt is inconclusive.",
            }}
        if resolution != proven_resolution:
            return 409, {"error": {
                "code": "tool_reconciliation_resolution_mismatch",
                "message": "Requested resolution contradicts the Tool effect receipt.",
            }}
        actor = str(session.get("user_id", "unknown"))
        evidence = {
            "source": "authenticated_tool_effect_receipt",
            "target_device_id": controller_id,
            "operation_fingerprint": record.operation_fingerprint,
            "effect_operation_id": record.effect_operation_id,
            "effect_receipt_hash": _object_hash(record.effect_receipt),
            "resolution": proven_resolution,
            "observed_at": observed_at,
            "engineer": actor,
            "notes_hash": hashlib.sha256(notes.encode("utf-8")).hexdigest(),
        }
        result = {
            "ok": resolution == "confirmed_tool_effect_completed",
            "state": (
                "tool_effect_reconciled_completed"
                if resolution == "confirmed_tool_effect_completed"
                else "tool_effect_reconciled_not_started"
            ),
            "message": "Unknown Tool effect reconciled by an engineer.",
            "data": {}, "errors": [],
        }
        final_audit = _final_reconciliation_audit(
            tool_id, request_key, evidence,
        )
        requested = {
            "audit_id": _reconciliation_audit_id(
                tool_id, request_key, resolution, "requested",
            ),
            "action": "tool_operation_reconciliation_requested",
            "actor": f"engineer:{actor}", "tool_id": tool_id,
            "request_key_hash": hashlib.sha256(request_key.encode()).hexdigest(),
            "resolution": resolution, "evidence": evidence,
            "timestamp": observed_at,
        }
        try:
            _audit_append_once(self._audit_path, requested)
        except (OSError, AuditIntegrityError):
            return 503, {"error": {"code": "reconciliation_audit_unavailable"}}
        if not self._tool_operation_store.reconcile_unknown(
            tool_id, request_key, result=result, evidence=evidence,
            audit_outbox=final_audit,
        ):
            try:
                current = self._tool_operation_store.get(tool_id, request_key)
            except (OSError, ValueError):
                current = None
            if current is not None and _is_reconciled_result(current.result):
                return self._finish_reconciliation_audit(
                    tool_id, request_key, current.result,
                    current.result["data"]["reconciliation_evidence"],
                )
            return 409, {"error": {
                "code": "tool_operation_not_reconcilable",
                "message": "The operation is not in an unknown state.",
            }}
        return self._finish_reconciliation_audit(
            tool_id, request_key, result, evidence, final_audit=final_audit,
        )

    def _finish_reconciliation_audit(
        self, tool_id: str, request_key: str, result: dict[str, Any],
        evidence: dict[str, Any], *, final_audit: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        final = final_audit or _outbox_event(result)
        if final is None:
            return 200, {"ok": True, "data": {
                "tool_id": tool_id, "state": result["state"], "evidence": evidence,
            }}
        try:
            _audit_append_once(self._audit_path, final)
            if not self._tool_operation_store.acknowledge_reconciliation_audit(
                tool_id, request_key, str(final["audit_id"]),
            ):
                raise OSError("reconciliation audit outbox acknowledgement failed")
        except (OSError, AuditIntegrityError):
            return 503, {"error": {
                "code": "reconciliation_audit_pending",
                "message": "The Tool effect is reconciled; retry to finalize its audit outbox.",
            }}
        return 200, {"ok": True, "data": {
            "tool_id": tool_id, "state": result["state"], "evidence": evidence,
        }}

    def _drain_reconciliation_audit_outbox(self) -> bool:
        store = self._tool_operation_store
        if store is None or not hasattr(store, "pending_reconciliation_audits"):
            return True
        try:
            items = store.pending_reconciliation_audits()
            for item in items:
                event = item["event"]
                _audit_append_once(self._audit_path, event)
                if not store.acknowledge_reconciliation_audit(
                    item["tool_id"], item["request_key"], str(event["audit_id"]),
                ):
                    return False
            return True
        except (OSError, ValueError, AuditIntegrityError, KeyError, TypeError):
            return False

def _sort_key(entry: dict[str, Any]) -> tuple[str, str]:
    return str(entry.get("timestamp", "")), str(entry.get("audit_id") or entry.get("migration_id") or "")


def _prove_tool_resolution(record: Any) -> str | None:
    receipt = record.effect_receipt
    if not isinstance(receipt, dict):
        return None
    if (
        not record.effect_operation_id
        or receipt.get("schema_version") != 1
        or receipt.get("source") not in {
            "authenticated_application_tool_terminal",
            "operation_store_pre_dispatch_state",
        }
        or receipt.get("effect_operation_id") != record.effect_operation_id
        or receipt.get("operation_fingerprint") != record.operation_fingerprint
        or receipt.get("target_device_id") != record.target_device_id
    ):
        return None
    resolution = receipt.get("resolution")
    if (
        receipt.get("source") == "authenticated_application_tool_terminal"
        and resolution == "confirmed_tool_effect_completed"
        and str(receipt.get("terminal_state", ""))
        and len(str(receipt.get("result_hash", ""))) == 64
    ):
        return "confirmed_tool_effect_completed"
    if (
        receipt.get("source") == "operation_store_pre_dispatch_state"
        and resolution == "confirmed_tool_effect_not_started"
        and receipt.get("terminal_state") == "cancelled_before_dispatch"
    ):
        return "confirmed_tool_effect_not_started"
    return None


def _object_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


def _is_reconciled_result(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("state") in {
            "tool_effect_reconciled_completed",
            "tool_effect_reconciled_not_started",
        }
        and isinstance(value.get("data"), dict)
        and isinstance(value["data"].get("reconciliation_evidence"), dict)
    )


def _outbox_event(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        return None
    outbox = result["data"].get("reconciliation_audit_outbox")
    if not isinstance(outbox, dict) or outbox.get("pending") is not True:
        return None
    event = outbox.get("event")
    return event if isinstance(event, dict) else None


def _final_reconciliation_audit(
    tool_id: str, request_key: str, evidence: dict[str, Any],
) -> dict[str, Any]:
    resolution = str(evidence.get("resolution", ""))
    return {
        "audit_id": _reconciliation_audit_id(
            tool_id, request_key, resolution, "completed",
        ),
        "action": "tool_operation_reconciled",
        "actor": f"engineer:{evidence.get('engineer', 'unknown')}",
        "tool_id": tool_id,
        "request_key_hash": hashlib.sha256(request_key.encode()).hexdigest(),
        "resolution": resolution,
        "evidence": deepcopy(evidence),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _reconciliation_audit_id(
    tool_id: str, request_key: str, resolution: str, stage: str,
) -> str:
    digest = hashlib.sha256(
        "\x1f".join((tool_id, request_key, resolution, stage)).encode("utf-8")
    ).hexdigest()
    return f"tool-reconciliation-{stage}-{digest[:32]}"


def _encode_cursor(cursor: tuple[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(cursor).encode("utf-8")).decode("ascii")


def _decode_cursor(value: str) -> tuple[str, str] | None:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(decoded, list) or len(decoded) != 2:
        return None
    return str(decoded[0]), str(decoded[1])


def _invalid(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_request", "message": message}}
