"""Fail-closed reconciliation of an unknown real-controller execution."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from robot_platform.application import AuthenticatedPrincipal
from robot_platform.execution.permit import ExecutionPermitState
from robot_platform.library.migration import AuditIntegrityError, _audit_append_once


class ExecutionRecoveryService:
    """Reconcile only a proved-safe unknown permit; never dispatch a write."""

    def __init__(
        self, *, platform: Any, permits: Any, audit_path: Path,
        tool_operation_store: Any = None,
    ) -> None:
        self._platform = platform
        self._permits = permits
        self._audit_path = audit_path
        self._tool_operation_store = tool_operation_store

    def list_unresolved(self, principal: AuthenticatedPrincipal) -> tuple[int, dict[str, Any]]:
        error = _authorize(principal)
        if error is not None:
            return error
        controller_id = str(self._platform.execution_context().get("controller_id", ""))
        if not controller_id:
            return 503, {"error": {"code": "execution_recovery_status_unavailable", "message": "Controller identity could not be verified."}}
        records = [
            record for record in self._permits.unresolved_records()
            if record.controller_id == controller_id
        ]
        try:
            safe, evidence = _safe_idle_evidence(self._platform.get_status())
        except Exception:
            safe = False
            evidence = {
                "connected_real_device": False,
                "mode": "status_unavailable",
                "alarms": ["status_unavailable"],
                "cancel_latch": False,
            }
        return 200, {"ok": True, "data": {"items": [
            {
                "operation_id": record.operation_id,
                "issued_at": record.issued_at,
                "updated_at": record.updated_at,
                # Legacy permit payloads are host-owned persistence. Never
                # return their free-form reason/diagnostic strings to a UI.
                "reason": "controller_result_not_definite",
                "recovery_ready": safe,
            }
            for record in records
        ]}}

    def reconcile(
        self, body: Any, *, principal: AuthenticatedPrincipal,
    ) -> tuple[int, dict[str, Any]]:
        error = _authorize(principal)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("request body must be an object")
        operation_id = str(body.get("operation_id", "")).strip()
        notes = str(body.get("notes", "")).strip()
        if not operation_id or not notes or len(notes) > 1000:
            return _invalid("operation_id and non-empty notes up to 1000 characters are required")
        if body.get("confirm_work_area_clear") is not True or body.get("confirm_estop_ready") is not True:
            return _invalid("both safety confirmations must be true")
        record = self._permits.find_unresolved_by_operation_id(operation_id)
        if record is None or record.state is not ExecutionPermitState.OUTCOME_UNKNOWN:
            return 409, {"error": {"code": "execution_not_reconcilable", "message": "Execution is not awaiting reconciliation."}}
        context = self._platform.execution_context()
        controller_id = str(context.get("controller_id", ""))
        if not controller_id or controller_id != record.controller_id:
            return 409, {"error": {"code": "execution_recovery_controller_mismatch", "message": "Execution belongs to another controller."}}
        try:
            status = self._platform.get_status()
        except Exception:
            return 503, {"error": {"code": "execution_recovery_status_unavailable", "message": "Controller status could not be verified."}}
        safe, evidence = _safe_idle_evidence(status)
        if not safe:
            return 422, {"error": {"code": "execution_recovery_controller_not_safe", "message": "Controller is not proven idle and safe for reconciliation.", "data": evidence}}
        observed_at = datetime.now(timezone.utc).isoformat()
        audit_id = f"execution-recovery:{secrets.token_urlsafe(16)}"
        reconciliation = {
            "operation_id": operation_id,
            "controller_id": controller_id,
            "actor": f"{principal.role}:{principal.actor_id}",
            "session_id": principal.session_id,
            "notes_hash": hashlib.sha256(notes.encode("utf-8")).hexdigest(),
            "observed_at": observed_at,
            "controller_evidence": evidence,
        }
        try:
            _audit_append_once(self._audit_path, {
                "audit_id": audit_id,
                "action": "execution_reconciliation_requested",
                "timestamp": observed_at,
                **reconciliation,
            })
        except (OSError, AuditIntegrityError):
            return 503, {"error": {"code": "execution_recovery_audit_unavailable", "message": "Recovery audit is unavailable."}}
        tool_operations_released = 0
        if self._tool_operation_store is not None:
            tool_result = {
                "ok": False,
                "state": "tool_effect_reconciled_prior_execution_outcome_unknown",
                "message": "The prior execution outcome remains unknown after safety recovery.",
                "data": {"prior_outcome": "unknown"},
                "errors": [],
            }
            try:
                tool_operations_released = self._tool_operation_store.release_unknown_after_execution_recovery(
                    effect_operation_id=record.operation_id,
                    target_device_id=controller_id,
                    result=tool_result,
                    evidence={
                        "source": "execution_recovery_safe_controller_evidence",
                        "audit_id": audit_id,
                        "controller_evidence": evidence,
                    },
                )
            except (OSError, ValueError):
                return 503, {"error": {
                    "code": "execution_recovery_tool_state_unavailable",
                    "message": "Tool operation state could not be safely reconciled.",
                }}
        result = {
            "ok": False,
            "state": "execution_safety_recovered_prior_outcome_unknown",
            "message": "Controller safety was recovered; the prior execution outcome remains unknown.",
            "data": {"prior_outcome": "unknown", "controller_evidence": evidence},
            "errors": [],
        }
        evidence_text = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        reconciled = self._permits.release_unknown_after_safety_recovery(
            record.handle,
            controller_evidence=evidence_text,
            audit_id=audit_id,
            result=result,
        )
        if not reconciled:
            return 409, {"error": {"code": "execution_not_reconcilable", "message": "Execution changed before reconciliation completed."}}
        reconciliation["tool_operations_released"] = tool_operations_released
        try:
            _audit_append_once(self._audit_path, {
                "audit_id": f"{audit_id}:completed",
                "action": "execution_safety_recovered_prior_outcome_unknown",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **reconciliation,
            })
        except (OSError, AuditIntegrityError):
            # The initial audit record and the permit transition both succeeded;
            # never report a completed safety recovery as a failed recovery.
            return 200, {"ok": True, "data": {
                "operation_id": operation_id,
                "state": result["state"],
                "controller_evidence": evidence,
                "audit_finalization": "pending",
            }}
        return 200, {"ok": True, "data": {"operation_id": operation_id, "state": result["state"], "controller_evidence": evidence, "audit_finalization": "complete"}}


def _authorize(principal: Any) -> tuple[int, dict[str, Any]] | None:
    if not isinstance(principal, AuthenticatedPrincipal) or principal.role not in {"operator", "engineer"}:
        return 403, {"error": {"code": "execution_recovery_forbidden", "message": "Authenticated operator role is required."}}
    return None


def _invalid(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_execution_recovery_request", "message": message}}


def _safe_idle_evidence(status: Any) -> tuple[bool, dict[str, Any]]:
    data = status.get("data") if isinstance(status, dict) else None
    state = data.get("robot_state") if isinstance(data, dict) else None
    state = state if isinstance(state, dict) else {}
    alarms = state.get("alarms")
    alarms = [str(item) for item in alarms] if isinstance(alarms, list) else ["status_unavailable"]
    evidence = {
        "connected_real_device": state.get("connected_real_device") is True,
        "mode": str(state.get("mode", "")),
        "alarms": alarms,
        "cancel_latch": bool(state.get("cancel_latch")),
    }
    safe = (
        evidence["connected_real_device"]
        and evidence["mode"] == "idle"
        and not evidence["alarms"]
        and not evidence["cancel_latch"]
    )
    return safe, evidence
