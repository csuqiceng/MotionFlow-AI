from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from robot_ai.library.auth import UserSessionStore, hash_password
from robot_ai.library.users import UserRegistry


def test_engineer_set_password_alias_updates_admin_user(tmp_path: Path) -> None:
    """B1a `nanobot engineer set-password` is a DEPRECATED alias: updates admin in users.json,
    prints a migration notice, and does NOT only change config hash."""
    from nanobot.cli.commands import engineer_app
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", hash_password("oldpw", iterations=100_000))
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["newpw", "newpw"]):
        result = runner.invoke(engineer_app, ["set-password", "--users-path", str(tmp_path / "users.json"),
                                               "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code == 0
    assert "deprecated" in result.output.lower() or "migration" in result.output.lower()
    admin = next(u for u in json.loads((tmp_path / "users.json").read_text("utf-8"))["users"].values()
                 if u["username"] == "admin")
    from robot_ai.library.auth import verify_password
    assert verify_password("newpw", admin["password_hash"]) is True


def test_engineer_login_alias_returns_user_token(tmp_path: Path) -> None:
    """B1a /api/robot/engineer/login alias -> process_auth_login(admin/engineer) -> user token."""
    from nanobot.api.robot_routes import process_engineer_login
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", hash_password("s3cret", iterations=100_000))
    store = UserSessionStore()
    status, body = process_engineer_login({"password": "s3cret"},
                                           users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "a.jsonl"),
                                           token_store=store, throttle=__import__("robot_ai.library.auth", fromlist=["LoginThrottle"]).LoginThrottle())
    assert status == 200
    tok = body["data"]["user_token"]
    assert store.check(tok)["role"] == "engineer"
