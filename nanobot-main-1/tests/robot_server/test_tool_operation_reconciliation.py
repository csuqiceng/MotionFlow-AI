from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest

import robot_server.tool_operation_store as tool_operation_store
from robot_platform.library.migration import (
    ensure_audit_chain,
    read_verified_audit_records,
    verify_audit_chain,
)
from robot_server.audit_api import RobotAuditService
from robot_server.tool_operation_store import JsonToolOperationStore


class _Identity:
    def require_engineer_session(self, token):
        if token != "engineer-token":
            return {}, (401, {"error": {"code": "unauthorized"}})
        return {"user_id": "engineer-1", "role": "engineer"}, None


def test_persisted_tool_receipt_includes_readable_observed_timestamp(tmp_path) -> None:
    path = tmp_path / "tool_operations.json"
    store = JsonToolOperationStore(path)
    assert store.begin(
        "robot_arm", "request-1", "request-fingerprint",
        operation_fingerprint="effect-fingerprint",
        target_device_id="controller-1",
        effect_operation_id="dispatch-request-1",
    )
    assert store.claim_effect_dispatch(
        "robot_arm", "request-1", "request-fingerprint",
        effect_operation_id="dispatch-request-1",
    )
    assert store.record_effect_terminal(
        "robot_arm", "request-1", "request-fingerprint",
        effect_operation_id="dispatch-request-1",
        result={"ok": True, "state": "completed"},
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    record = next(iter(payload["records"].values()))
    observed_at = record["effect_receipt"]["observed_at"]
    assert record["effect_receipt"]["observed_at_iso"] == datetime.fromtimestamp(
        observed_at, tz=timezone.utc,
    ).isoformat()


def test_process_probe_system_error_is_treated_as_not_alive(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_operation_store.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(SystemError("invalid parameter")),
    )

    assert tool_operation_store._process_is_alive(999_999) is False


class _Platform:
    def execution_context(self):
        return {"controller_id": "controller-1"}

    def get_status(self):
        return {
            "ok": True, "state": "status_report",
            "data": {"robot_state": {
                "mode": "idle",
                "axes_mm": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
            }},
        }


def test_engineer_can_reconcile_unknown_only_with_server_controller_evidence(tmp_path) -> None:
    audit = tmp_path / "audit.jsonl"
    ensure_audit_chain(audit)
    store = JsonToolOperationStore(tmp_path / "tool_operations.json")
    assert store.begin(
        "robot_arm", "request-1", "request-fingerprint",
        operation_fingerprint="effect-fingerprint",
        target_device_id="controller-1",
        effect_payload={"action": "linear_move", "target_pose": {
            "x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6,
        }},
        readback_predicate={
            "kind": "axes_equal",
            "expected": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
            "tolerance": 0.001,
        },
        effect_operation_id="dispatch-request-1",
    )
    assert store.claim_effect_dispatch(
        "robot_arm", "request-1", "request-fingerprint",
        effect_operation_id="dispatch-request-1",
    )
    assert store.mark_unknown(
        "robot_arm", "request-1", "request-fingerprint", reason="timeout",
    )
    record = store.get("robot_arm", "request-1")
    assert record is not None
    assert store.record_effect_terminal(
        "robot_arm", "request-1", "request-fingerprint",
        effect_operation_id=record.effect_operation_id,
        result={"ok": True, "state": "late_completion"},
    )
    # Reconciliation must consume the authenticated receipt after a process
    # restart, not an in-memory object from the producer.
    store = JsonToolOperationStore(tmp_path / "tool_operations.json")
    service = RobotAuditService(
        tmp_path, _Identity(), tool_operation_store=store, platform=_Platform(),
    )

    status, unresolved = service.list_unresolved_tool_operations("engineer-token")
    assert status == 200
    assert unresolved["data"]["items"][0]["operation_fingerprint"] == "effect-fingerprint"

    status, result = service.reconcile_tool_operation("engineer-token", {
        "tool_id": "robot_arm", "request_key": "request-1",
        "resolution": "confirmed_tool_effect_completed",
        "notes": "Controller readback matches the exact target pose.",
    })

    assert status == 200
    assert result["data"]["evidence"]["source"] == (
        "authenticated_tool_effect_receipt"
    )
    assert store.unresolved_records() == ()
    assert store.get("robot_arm", "request-1").state == "completed"
    verify_audit_chain(audit)

    assert store.begin(
        "robot_arm", "request-2", "request-fingerprint-2",
        operation_fingerprint="effect-fingerprint-2",
        target_device_id="controller-1",
        effect_payload={"action": "linear_move"},
        readback_predicate={
            "kind": "axes_equal",
            "expected": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
            "tolerance": 0.001,
        },
        effect_operation_id="dispatch-request-2",
    )
    assert store.claim_effect_dispatch(
        "robot_arm", "request-2", "request-fingerprint-2",
        effect_operation_id="dispatch-request-2",
    )
    assert store.mark_unknown(
        "robot_arm", "request-2", "request-fingerprint-2", reason="timeout",
    )
    record = store.get("robot_arm", "request-2")
    assert record is not None
    assert store.record_effect_terminal(
        "robot_arm", "request-2", "request-fingerprint-2",
        effect_operation_id=record.effect_operation_id,
        result={"ok": True, "state": "late_completion"},
    )
    contradicted, _ = service.reconcile_tool_operation("engineer-token", {
        "tool_id": "robot_arm", "request_key": "request-2",
        "resolution": "confirmed_tool_effect_not_started",
        "notes": "contradictory claim",
    })
    assert contradicted == 409
    assert store.get("robot_arm", "request-2").state == "unknown"


def test_matching_current_pose_without_dispatch_receipt_is_inconclusive(tmp_path) -> None:
    ensure_audit_chain(tmp_path / "audit.jsonl")
    store = JsonToolOperationStore(tmp_path / "tool_operations.json")
    assert store.begin(
        "robot_arm", "already-there", "request-fingerprint",
        operation_fingerprint="effect-fingerprint",
        target_device_id="controller-1",
        effect_payload={"action": "linear_move"},
        readback_predicate={
            "kind": "axes_equal",
            "expected": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
            "tolerance": 0.001,
        },
        effect_operation_id="dispatch-never-completed",
    )
    assert store.claim_effect_dispatch(
        "robot_arm", "already-there", "request-fingerprint",
        effect_operation_id="dispatch-never-completed",
    )
    assert store.mark_unknown(
        "robot_arm", "already-there", "request-fingerprint", reason="timeout",
    )
    service = RobotAuditService(
        tmp_path, _Identity(), tool_operation_store=store, platform=_Platform(),
    )

    status, result = service.reconcile_tool_operation("engineer-token", {
        "tool_id": "robot_arm", "request_key": "already-there",
        "resolution": "confirmed_tool_effect_completed",
        "notes": "Pose happens to match but no dispatch receipt exists.",
    })

    assert status == 422
    assert result["error"]["code"] == "tool_reconciliation_evidence_inconclusive"
    assert store.get("robot_arm", "already-there").state == "unknown"


def test_reconciliation_requires_engineer_and_authenticated_effect_receipt(tmp_path) -> None:
    ensure_audit_chain(tmp_path / "audit.jsonl")
    store = JsonToolOperationStore(tmp_path / "tool_operations.json")
    assert store.begin(
        "robot_arm", "request-1", "request-fingerprint",
        operation_fingerprint="effect-fingerprint",
        target_device_id="controller-1",
        effect_payload={"action": "linear_move"},
        readback_predicate={"kind": "unsupported"},
        effect_operation_id="effect-operation-1",
    )
    assert store.mark_unknown(
        "robot_arm", "request-1", "request-fingerprint", reason="timeout",
    )
    unavailable = type("Unavailable", (), {
        "execution_context": lambda self: {"controller_id": "controller-1"},
        "get_status": lambda self: {"ok": False},
    })()
    service = RobotAuditService(
        tmp_path, _Identity(),
        tool_operation_store=store, platform=unavailable,
    )
    body = {
        "tool_id": "robot_arm", "request_key": "request-1",
        "resolution": "confirmed_tool_effect_not_started", "notes": "checked",
    }

    assert service.reconcile_tool_operation("bad-token", body)[0] == 401
    assert service.reconcile_tool_operation("engineer-token", body)[0] == 200


def test_operation_store_rejects_unsigned_receipt_tampering(tmp_path) -> None:
    path = tmp_path / "tool_operations.json"
    store = JsonToolOperationStore(path)
    assert store.begin(
        "robot_arm", "request-1", "fingerprint",
        operation_fingerprint="effect", target_device_id="controller-1",
        effect_operation_id="effect-operation-1",
    )
    assert store.claim_effect_dispatch(
        "robot_arm", "request-1", "fingerprint",
        effect_operation_id="effect-operation-1",
    )
    assert store.mark_unknown(
        "robot_arm", "request-1", "fingerprint", reason="timeout",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = next(iter(payload["records"].values()))
    raw["effect_receipt"] = {
        "schema_version": 1,
        "source": "authenticated_application_tool_terminal",
        "effect_operation_id": "effect-operation-1",
        "operation_fingerprint": "effect",
        "target_device_id": "controller-1",
        "resolution": "confirmed_tool_effect_completed",
        "terminal_state": "forged",
        "result_hash": "0" * 64,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity"):
        store.get("robot_arm", "request-1")


def test_operation_store_begin_is_atomic_across_processes(tmp_path) -> None:
    path = tmp_path / "tool_operations.json"
    gate = tmp_path / "start"
    script = (
        "import pathlib,sys,time; "
        "from robot_server.tool_operation_store import JsonToolOperationStore; "
        "s=JsonToolOperationStore(sys.argv[1]); g=pathlib.Path(sys.argv[2]); "
        "\nwhile not g.exists(): time.sleep(0.005)\n"
        "print(s.begin('robot_arm','same-request',sys.argv[3],"
        "operation_fingerprint='same-effect',target_device_id='controller-1',"
        "effect_operation_id=sys.argv[4]),flush=True)"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(gate),
             f"fingerprint-{index}", f"effect-operation-{index}"],
            cwd=str(pathlib.Path.cwd()), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        for index in (1, 2)
    ]
    time.sleep(0.1)
    gate.write_text("go", encoding="utf-8")
    outcomes = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        outcomes.append(stdout.strip())

    assert outcomes.count("True") == 1
    assert outcomes.count("False") == 1
    record = JsonToolOperationStore(path).get("robot_arm", "same-request")
    assert record is not None
    assert record.fingerprint in {"fingerprint-1", "fingerprint-2"}


def test_same_effect_different_request_keys_are_atomic_across_processes(tmp_path) -> None:
    path = tmp_path / "tool_operations.json"
    gate = tmp_path / "start"
    script = (
        "import pathlib,sys,time; "
        "from robot_server.tool_operation_store import JsonToolOperationStore; "
        "s=JsonToolOperationStore(sys.argv[1]); g=pathlib.Path(sys.argv[2]); "
        "\nwhile not g.exists(): time.sleep(0.005)\n"
        "ok=s.begin('robot_arm',sys.argv[3],sys.argv[4],"
        "operation_fingerprint='same-effect',target_device_id='controller-1',"
        "effect_operation_id=sys.argv[5]); "
        "claimed=(s.claim_effect_dispatch('robot_arm',sys.argv[3],sys.argv[4],"
        "effect_operation_id=sys.argv[5]) if ok else False); "
        "print(f'{ok},{claimed}',flush=True)"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(gate),
             f"request-{index}", f"fingerprint-{index}", f"effect-op-{index}"],
            cwd=str(pathlib.Path.cwd()), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        for index in (1, 2)
    ]
    time.sleep(0.1)
    gate.write_text("go", encoding="utf-8")
    outcomes = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        outcomes.append(stdout.strip())

    assert outcomes.count("True,True") == 1
    assert outcomes.count("False,False") == 1
    assert len(JsonToolOperationStore(path).unresolved_records()) == 1


def test_operation_store_rejects_schema_downgrade_and_valid_snapshot_rollback(
    tmp_path,
) -> None:
    path = tmp_path / "tool_operations.json"
    store = JsonToolOperationStore(path)
    assert store.begin(
        "robot_arm", "request-1", "fingerprint-1",
        operation_fingerprint="effect-1", target_device_id="controller-1",
        effect_operation_id="effect-operation-1",
    )
    old_valid = path.read_bytes()
    assert store.claim_effect_dispatch(
        "robot_arm", "request-1", "fingerprint-1",
        effect_operation_id="effect-operation-1",
    )

    path.write_text('{"schema_version":1,"records":{}}', encoding="utf-8")
    with pytest.raises(ValueError, match="offline migration"):
        JsonToolOperationStore(path)

    path.write_bytes(old_valid)
    with pytest.raises(ValueError, match="rollback"):
        JsonToolOperationStore(path)


def test_first_store_commit_recovers_when_genesis_head_was_written(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "tool_operations.json"
    store = JsonToolOperationStore(path)
    original = store._write_head
    calls = 0

    def fail_after_store(key, generation, store_hash):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash after store replace")
        return original(key, generation, store_hash)

    monkeypatch.setattr(store, "_write_head", fail_after_store)
    with pytest.raises(OSError):
        store.begin(
            "robot_arm", "request-1", "fingerprint",
            operation_fingerprint="effect", target_device_id="controller-1",
            effect_operation_id="effect-operation-1",
        )

    recovered = JsonToolOperationStore(path)
    record = recovered.get("robot_arm", "request-1")
    assert record is not None and record.state == "started"


def test_reconciliation_final_audit_is_idempotently_replayable(
    tmp_path, monkeypatch,
) -> None:
    import robot_server.audit_api as audit_api

    ensure_audit_chain(tmp_path / "audit.jsonl")
    store = JsonToolOperationStore(tmp_path / "tool_operations.json")
    assert store.begin(
        "robot_arm", "request-1", "fingerprint",
        operation_fingerprint="effect", target_device_id="controller-1",
        effect_operation_id="effect-operation-1",
    )
    assert store.mark_unknown(
        "robot_arm", "request-1", "fingerprint", reason="cancelled",
    )
    service = RobotAuditService(
        tmp_path, _Identity(), tool_operation_store=store, platform=_Platform(),
    )
    original = audit_api._audit_append_once
    failed = False

    def fail_final_once(path, entry):
        nonlocal failed
        if entry.get("action") == "tool_operation_reconciled" and not failed:
            failed = True
            raise OSError("simulated final audit outage")
        return original(path, entry)

    monkeypatch.setattr(audit_api, "_audit_append_once", fail_final_once)
    body = {
        "tool_id": "robot_arm", "request_key": "request-1",
        "resolution": "confirmed_tool_effect_not_started", "notes": "checked",
    }
    first_status, _ = service.reconcile_tool_operation("engineer-token", body)
    assert first_status == 503
    assert store.get("robot_arm", "request-1").state == "completed"
    assert len(store.pending_reconciliation_audits()) == 1

    # A fresh service must discover and drain the authenticated outbox without
    # the original client retaining or replaying its request key/body.
    restarted_store = JsonToolOperationStore(tmp_path / "tool_operations.json")
    RobotAuditService(
        tmp_path, _Identity(),
        tool_operation_store=restarted_store, platform=_Platform(),
    )
    assert restarted_store.pending_reconciliation_audits() == ()
    actions = [
        record.get("action")
        for record in read_verified_audit_records(tmp_path / "audit.jsonl")
    ]
    assert actions.count("tool_operation_reconciliation_requested") == 1
    assert actions.count("tool_operation_reconciled") == 1
