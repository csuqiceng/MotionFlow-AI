from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner


def _disabled_admin_install(tmp_path: Path) -> Path:
    """A users.json where admin is a disabled placeholder (no B1a hash)."""
    from robot_ai.library.users import UserRegistry
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", "placeholder", enabled=False,
               actor={"actor": "system:migration", "actor_role": "system"})
    return tmp_path / "users.json"


def test_set_bootstrap_password_enables_admin(tmp_path: Path) -> None:
    from robot_server.admin_cli import users_app
    users_json = _disabled_admin_install(tmp_path)
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["newpw", "newpw"]):
        result = runner.invoke(users_app, ["set-bootstrap-password", "--username", "admin",
                                            "--users-path", str(users_json),
                                            "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code == 0, result.output
    admin = next(u for u in json.loads(users_json.read_text("utf-8"))["users"].values()
                 if u["username"] == "admin")
    assert admin["enabled"] is True
    from robot_ai.library.auth import verify_password
    assert verify_password("newpw", admin["password_hash"]) is True


def test_set_bootstrap_password_no_password_arg(tmp_path: Path) -> None:
    """--password is NOT accepted (password must not appear in args)."""
    from robot_server.admin_cli import users_app
    users_json = _disabled_admin_install(tmp_path)
    runner = CliRunner()
    result = runner.invoke(users_app, ["set-bootstrap-password", "--username", "admin",
                                        "--password", "x", "--users-path", str(users_json),
                                        "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code != 0  # unknown option rejected


def test_set_bootstrap_password_unknown_username(tmp_path: Path) -> None:
    from robot_server.admin_cli import users_app
    users_json = _disabled_admin_install(tmp_path)
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["p", "p"]):
        result = runner.invoke(users_app, ["set-bootstrap-password", "--username", "ghost",
                                            "--users-path", str(users_json),
                                            "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code != 0
