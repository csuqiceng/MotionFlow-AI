from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

import robot_platform.library.migration as migration_module

from robot_platform.library.migration import (
    AuditIntegrityError, _audit_append, _audit_append_once,
    ensure_audit_chain, verify_audit_chain,
)
from robot_server.audit_api import RobotAuditService


def test_audit_hash_chain_detects_record_tampering_and_blocks_append(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    ensure_audit_chain(path)
    _audit_append(path, {"action": "operation", "actor": "operator:user-1"})
    verify_audit_chain(path)

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["actor"] = "attacker"
    forged = dict(records[0])
    forged.pop("_audit_hash")
    canonical = json.dumps(
        forged, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    records[0]["_audit_hash"] = hashlib.sha256(
        f"{'0' * 64}|{canonical}".encode("utf-8")
    ).hexdigest()
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AuditIntegrityError):
        verify_audit_chain(path)
    with pytest.raises(AuditIntegrityError):
        _audit_append(path, {"action": "must_fail_closed"})

    assert records[0]["_audit_alg"] == "hmac-sha256"


def test_legacy_audit_prefix_is_anchored_then_protected(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text('{"action":"legacy"}\n', encoding="utf-8")
    ensure_audit_chain(path)
    verify_audit_chain(path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"action":"unchained-after-checkpoint"}\n')
    with pytest.raises(AuditIntegrityError):
        verify_audit_chain(path)


def test_audit_read_api_fails_closed_when_integrity_is_invalid(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    ensure_audit_chain(path)
    _audit_append(path, {"action": "operation", "actor": "operator:user-1"})
    path.write_text(
        path.read_text(encoding="utf-8").replace("operator:user-1", "attacker"),
        encoding="utf-8",
    )

    class Identity:
        def require_engineer_session(self, _token):
            return {"user_id": "engineer-1"}, None

    status, result = RobotAuditService(tmp_path, Identity()).list("token")
    assert status == 503
    assert result["error"]["code"] == "audit_integrity_failed"


def test_direct_audit_append_never_falls_back_to_public_hash(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    _audit_append(path, {"action": "direct"})

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["_audit_alg"] == "hmac-sha256"
    verify_audit_chain(path)


def test_audit_key_configuration_inside_log_directory_is_rejected(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("MOTIONFLOW_AUDIT_KEY_PATH", str(tmp_path / "audit.key"))

    with pytest.raises(AuditIntegrityError, match="outside"):
        _audit_append(path, {"action": "must-not-write"})
    assert not path.exists()


def test_public_sha_chain_cannot_be_accepted_as_an_authenticated_prefix(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    record = {
        "action": "forged", "_audit_seq": 1, "_audit_prev_hash": "0" * 64,
    }
    canonical = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    record["_audit_hash"] = hashlib.sha256(
        f"{'0' * 64}|{canonical}".encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(AuditIntegrityError, match="hmac-sha256"):
        verify_audit_chain(path)
    with pytest.raises(AuditIntegrityError, match="hmac-sha256"):
        _audit_append(path, {"action": "must-not-anchor-forgery"})

    ensure_audit_chain(path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["action"] == "audit_legacy_sha_quarantined"
    assert records[0]["_audit_alg"] == "hmac-sha256"
    quarantined = list(tmp_path.glob("audit.untrusted-legacy-sha256-*.jsonl"))
    assert len(quarantined) == 1
    assert json.loads(quarantined[0].read_text(encoding="utf-8"))["action"] == "forged"


def test_signed_audit_identity_check_and_append_are_atomic(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    entry = {"audit_id": "same-id", "action": "once"}
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _index: _audit_append_once(path, entry), range(16)))

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 15
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert sum(record.get("audit_id") == "same-id" for record in records) == 1
    verify_audit_chain(path)


def test_malformed_public_sha_log_is_not_quarantined_as_legacy(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text(json.dumps({
        "action": "malformed", "_audit_seq": 999,
        "_audit_prev_hash": "bad", "_audit_hash": "bad",
    }) + "\n", encoding="utf-8")

    with pytest.raises(AuditIntegrityError):
        ensure_audit_chain(path)
    assert path.exists()
    assert list(tmp_path.glob("audit.untrusted-legacy-sha256-*.jsonl")) == []


def test_unchained_prefix_followed_by_public_sha_is_not_quarantined(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    first = {"action": "forged-unchained", "audit_id": "attacker-chosen"}
    first_hash = hashlib.sha256(
        f"{'0' * 64}|{json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}".encode(
            "utf-8"
        )
    ).hexdigest()
    second = {
        "action": "public-sha-after-prefix",
        "_audit_seq": 2,
        "_audit_prev_hash": first_hash,
    }
    canonical = json.dumps(
        second, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    second["_audit_hash"] = hashlib.sha256(
        f"{first_hash}|{canonical}".encode("utf-8")
    ).hexdigest()
    original = "\n".join((json.dumps(first), json.dumps(second))) + "\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(AuditIntegrityError):
        ensure_audit_chain(path)

    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("audit.untrusted-legacy-sha256-*.jsonl")) == []


def test_signed_audit_append_once_is_atomic_across_processes(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    script = (
        "import sys; "
        "from robot_platform.library.migration import _audit_append_once; "
        "print(_audit_append_once(sys.argv[1], "
        "{'audit_id':'cross-process-id','action':'once'}))"
    )

    def invoke(_index: int) -> str:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            check=True, capture_output=True, text=True,
        )
        return completed.stdout.strip()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(invoke, range(8)))

    assert outcomes.count("True") == 1
    assert outcomes.count("False") == 7
    verify_audit_chain(path)


def test_signed_audit_log_rejects_tail_truncation_and_old_valid_prefix(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    ensure_audit_chain(path)
    _audit_append(path, {"action": "second"})
    old_valid_prefix = path.read_bytes()
    _audit_append(path, {"action": "third"})
    latest = path.read_bytes()

    lines = latest.decode("utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError, match="truncation|rollback"):
        verify_audit_chain(path)

    path.write_bytes(old_valid_prefix)
    with pytest.raises(AuditIntegrityError, match="truncation|rollback"):
        verify_audit_chain(path)

    path.write_bytes(latest)
    verify_audit_chain(path)


def test_sealed_audit_rejects_removal_of_all_authenticated_records(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text('{"action":"legacy"}\n', encoding="utf-8")
    ensure_audit_chain(path)

    path.write_text('{"action":"legacy"}\n', encoding="utf-8")

    with pytest.raises(AuditIntegrityError, match="truncation"):
        verify_audit_chain(path)


def test_first_audit_append_recovers_from_log_before_head_crash(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "audit.jsonl"
    original = migration_module._write_audit_head
    calls = 0

    def fail_after_log(audit_path, key, sequence, head_hash):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash after log fsync")
        return original(audit_path, key, sequence, head_hash)

    monkeypatch.setattr(migration_module, "_write_audit_head", fail_after_log)
    with pytest.raises(OSError):
        _audit_append(path, {"action": "first"})
    monkeypatch.setattr(migration_module, "_write_audit_head", original)

    verify_audit_chain(path)
    assert json.loads(path.read_text(encoding="utf-8"))["action"] == "first"
