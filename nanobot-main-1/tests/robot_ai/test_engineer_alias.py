from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from robot_ai.library.auth import UserSessionStore, hash_password
from robot_ai.library.users import UserRegistry


def test_engineer_set_password_alias_updates_admin_user(tmp_path: Path) -> None:
    """robot-admin updates the admin identity in users.json, not configuration."""
    from robot_server.admin_cli import engineer_app
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", hash_password("oldpw", iterations=100_000))
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["newpw", "newpw"]):
        result = runner.invoke(engineer_app, ["set-password", "--users-path", str(tmp_path / "users.json"),
                                               "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code == 0
    assert "password updated" in result.output.lower()
    admin = next(u for u in json.loads((tmp_path / "users.json").read_text("utf-8"))["users"].values()
                 if u["username"] == "admin")
    from robot_ai.library.auth import verify_password
    assert verify_password("newpw", admin["password_hash"]) is True
