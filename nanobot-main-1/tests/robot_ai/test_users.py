from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.users import UserRegistry, normalize_username


def test_normalize_username_strip_casefold() -> None:
    assert normalize_username("Admin") == "admin"
    assert normalize_username("  Alice  ") == "alice"
    assert normalize_username("ADMIN") == "admin"
    assert normalize_username(None) == ""  # type: ignore[arg-type]


def test_normalize_username_independent_of_normalize_id() -> None:
    """Changing normalize_username must NOT affect command-id normalization."""
    from robot_ai.library.models import normalize_id
    assert normalize_username("Pick Place") == "pick place"     # space preserved (casefold only)
    assert normalize_id("Pick Place") == "pick-place"            # command-id collapses whitespace


def _reg(tmp_path: Path) -> UserRegistry:
    return UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")


def test_create_user(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    u = reg.create("Admin", "engineer", "pbkdf2_sha256$x$y$z")
    assert u["username"] == "Admin"
    assert u["role"] == "engineer"
    assert u["enabled"] is True
    assert u["user_id"]
    assert reg.get_by_username("admin")["user_id"] == u["user_id"]


def test_create_user_does_not_persist_first_password_change_marker(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    user = reg.create("operator", "operator", "h")

    assert "must_change_password" not in user
    assert "must_change_password" not in UserRegistry(reg.path, audit_path=reg.audit_path).get(user["user_id"])


def test_create_rejects_duplicate_normalized_username(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Admin", "engineer", "h1")
    try:
        reg.create(" ADMIN ", "operator", "h2")  # same normalization -> conflict
        assert False
    except ValueError:
        pass


def test_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    UserRegistry(path, audit_path=tmp_path / "audit.jsonl").create("admin", "engineer", "h")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert "pending_audits" in payload
    reg = UserRegistry(path, audit_path=tmp_path / "audit.jsonl")
    assert reg.get_by_username("admin") is not None


def test_outbox_drains_to_audit(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("admin", "engineer", "h")
    lines = [ln for ln in (tmp_path / "audit.jsonl").read_text("utf-8").splitlines() if ln.strip()]
    assert any(json.loads(ln)["action"] == "user_create" for ln in lines)
    assert reg._data["pending_audits"] == []


def test_create_rejects_empty_username(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    for bad in ["", "   "]:
        try:
            reg.create(bad, "engineer", "h")
            assert False
        except ValueError:
            pass


def test_bootstrap_set_password_atomic_enable_and_password(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    u = reg.create("admin", "engineer", "placeholder", enabled=False)
    reg.bootstrap_set_password(u["user_id"], "newhash")
    reloaded = UserRegistry(reg.path, audit_path=reg.audit_path).get(u["user_id"])
    assert reloaded["enabled"] is True and reloaded["password_hash"] == "newhash"
    actions = [json.loads(ln)["action"]
               for ln in reg.audit_path.read_text("utf-8").splitlines() if ln.strip()]
    assert actions.count("user_bootstrap_password") == 1  # single atomic write


def test_enabled_engineer_count_and_last_engineer_protection(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    a = reg.create("admin", "engineer", "h")
    assert reg.enabled_engineer_count() == 1
    try:
        reg.update(a["user_id"], enabled=False)
        assert False
    except Exception as e:  # ConflictError-shaped
        assert "last_engineer" in str(e).lower() or "engineer" in str(e).lower()
