from __future__ import annotations

import json
from pathlib import Path


def _write_audit(path: Path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _entries(n: int) -> list[dict]:
    out = []
    for i in range(n):
        ts = "2026-07-12T00:00:0" + str(i // 2)  # pairs share a timestamp
        out.append({"action": "command_publish", "actor": "engineer",
                    "audit_id": f"id-{i:02d}", "timestamp": ts})
    return out


def _authed(store=None, tok=None):
    # Task 7: audit endpoint gates via _require_user_role on a UserSessionStore token.
    from robot_ai.library.auth import UserSessionStore
    store = store or UserSessionStore()
    tok = tok or store.issue({"user_id": "u-admin", "username": "admin", "role": "engineer"})
    return store, tok


def test_audit_first_page_newest_desc_with_cursor(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, _entries(6))
    store, tok = _authed()
    s, body = process_engineer_audit(audit_path=str(audit), limit=3, before=None,
                                      token_store=store, engineer_token=tok)
    assert s == 200
    assert [e["audit_id"] for e in body["data"]["items"]] == ["id-05", "id-04", "id-03"]
    assert body["data"]["next_cursor"] is not None


def test_audit_same_timestamp_across_pages_no_skip(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, _entries(4))
    store, tok = _authed()
    _, p1 = process_engineer_audit(audit_path=str(audit), limit=2, before=None,
                                    token_store=store, engineer_token=tok)
    assert [e["audit_id"] for e in p1["data"]["items"]] == ["id-03", "id-02"]
    _, p2 = process_engineer_audit(audit_path=str(audit), limit=2,
                                    before=p1["data"]["next_cursor"],
                                    token_store=store, engineer_token=tok)
    assert [e["audit_id"] for e in p2["data"]["items"]] == ["id-01", "id-00"]
    assert p2["data"]["next_cursor"] is None


def test_audit_limit_capped_at_100(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, _entries(150))
    store, tok = _authed()
    _, body = process_engineer_audit(audit_path=str(audit), limit=9999, before=None,
                                      token_store=store, engineer_token=tok)
    assert len(body["data"]["items"]) == 100


def test_audit_legacy_migration_id_paginates_alongside_audit_id(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, [
        {"action": "legacy_import", "actor": "system:migration",
         "migration_id": "legacy-import:abc", "timestamp": "2026-07-12T00:00:00"},
        {"action": "command_publish", "actor": "engineer",
         "audit_id": "id-99", "timestamp": "2026-07-12T00:00:01"},
    ])
    store, tok = _authed()
    _, body = process_engineer_audit(audit_path=str(audit), limit=10, before=None,
                                      token_store=store, engineer_token=tok)
    ids = [(e.get("audit_id") or e.get("migration_id")) for e in body["data"]["items"]]
    assert ids == ["id-99", "legacy-import:abc"]
