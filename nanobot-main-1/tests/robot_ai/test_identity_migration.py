from __future__ import annotations

import json
from pathlib import Path


def _b1a_config(tmp_path: Path, *, engineer_hash="h_admin", gateway_secret="legacy-secret"):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"robotAi": {"engineer": {"passwordHash": engineer_hash,
                                                          "pbkdf2Iterations": 200_000}}}), encoding="utf-8")
    return cfg


def test_migrate_creates_admin_from_b1a_hash_and_operator_from_secret(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    migrated = migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg,
                                        gateway_secret="legacy-secret", audit_path=str(tmp_path / "a.jsonl"))
    assert migrated is True
    data = json.loads(users.read_text("utf-8"))
    admin = next(u for u in data["users"].values() if u["username"] == "admin")
    assert admin["role"] == "engineer" and admin["enabled"] is True and admin["password_hash"] == "h_admin"
    op = next(u for u in data["users"].values() if u["username"] == "operator")
    assert op["role"] == "operator" and op["enabled"] is True
    from robot_ai.library.auth import verify_password
    assert verify_password("legacy-secret", op["password_hash"]) is True


def test_migrate_disabled_operator_placeholder_when_no_secret(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg,
                             gateway_secret="", audit_path=str(tmp_path / "a.jsonl"))  # no secret
    data = json.loads(users.read_text("utf-8"))
    op = next(u for u in data["users"].values() if u["username"] == "operator")
    assert op["enabled"] is False  # placeholder, NOT hash of any API token
    assert op["password_hash"] != ""


def test_migrate_admin_disabled_placeholder_when_no_b1a_hash(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"robotAi": {"engineer": {"passwordHash": "", "pbkdf2Iterations": 200_000}}}),
                   encoding="utf-8")
    users = tmp_path / "users.json"
    migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg,
                             gateway_secret="", audit_path=str(tmp_path / "a.jsonl"))
    admin = next(u for u in json.loads(users.read_text("utf-8"))["users"].values() if u["username"] == "admin")
    assert admin["enabled"] is False


def test_migrate_idempotent(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg, gateway_secret="s",
                             audit_path=str(tmp_path / "a.jsonl"))
    assert migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg, gateway_secret="s",
                                    audit_path=str(tmp_path / "a.jsonl")) is False


def test_initialize_user_identity_separate_from_libraries(tmp_path: Path, monkeypatch) -> None:
    """initialize_user_identity is its own function (identity domain), idempotent + drains."""
    from unittest.mock import patch

    from robot_ai.library.users import initialize_user_identity
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    audit = tmp_path / "a.jsonl"
    with patch("robot_ai.library.users.UserRegistry.drain_pending_audits", return_value=[]) as m:
        initialize_user_identity(users_path=str(users), audit_path=str(audit),
                                  b1a_config_path=cfg, gateway_secret="s")
        # initialize_user_identity (which runs migrate_users_if_needed -> drain,
        # then its own final drain) drives the outbox at least once. Asserting == 1
        # would be wrong: _commit_with_audit also drains per user_create during migration.
        assert m.call_count >= 1
    assert json.loads(users.read_text("utf-8"))["schema_version"] == "1.0"


def test_initialize_repairs_disabled_operator_placeholder_when_secret_appears(
    tmp_path: Path,
) -> None:
    from robot_ai.library.auth import verify_password
    from robot_ai.library.users import initialize_user_identity

    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    audit = tmp_path / "a.jsonl"

    initialize_user_identity(
        users_path=users,
        audit_path=audit,
        b1a_config_path=cfg,
        gateway_secret="",
    )
    before = json.loads(users.read_text("utf-8"))
    placeholder = next(u for u in before["users"].values() if u["username"] == "operator")
    assert placeholder["enabled"] is False
    assert not placeholder["password_hash"].startswith("pbkdf2_sha256$")

    initialize_user_identity(
        users_path=users,
        audit_path=audit,
        b1a_config_path=cfg,
        gateway_secret="configured-later",
    )

    after = json.loads(users.read_text("utf-8"))
    operator = next(u for u in after["users"].values() if u["username"] == "operator")
    assert operator["enabled"] is True
    assert verify_password("configured-later", operator["password_hash"]) is True


def test_initialize_does_not_reenable_disabled_operator_with_real_password(
    tmp_path: Path,
) -> None:
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry, initialize_user_identity

    users = tmp_path / "users.json"
    audit = tmp_path / "a.jsonl"
    reg = UserRegistry(users, audit_path=audit)
    reg.create("operator", "operator", hash_password("chosen-password"), enabled=False)

    initialize_user_identity(
        users_path=users,
        audit_path=audit,
        gateway_secret="gateway-secret",
    )

    operator = UserRegistry(users, audit_path=audit).get_by_username("operator")
    assert operator is not None
    assert operator["enabled"] is False
