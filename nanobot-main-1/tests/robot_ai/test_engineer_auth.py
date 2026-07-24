# tests/robot_ai/test_engineer_auth.py
from __future__ import annotations

from robot_ai.library.auth import (
    extract_iterations,
    hash_password,
    verify_password,
)


def test_hash_and_verify() -> None:
    h = hash_password("secret123", iterations=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_format_round_trips() -> None:
    h = hash_password("pw", iterations=5000)
    parts = h.split("$")
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) == 5000
    assert len(parts) == 4


def test_extract_iterations() -> None:
    h = hash_password("pw", iterations=3000)
    assert extract_iterations(h) == 3000
    assert extract_iterations("garbage") == 0


# EngineerTokenStore was removed in Task 7 (replaced by UserSessionStore).
# Its issue/check/revoke/expired/unknown coverage now lives in
# tests/robot_ai/test_user_session.py.


def test_config_schema_engineer_section() -> None:
    from nanobot.config.schema import Config
    cfg = Config()
    assert hasattr(cfg, "robot_ai")
    assert hasattr(cfg.robot_ai, "engineer")
    assert cfg.robot_ai.engineer.password_hash == ""
    assert cfg.robot_ai.engineer.pbkdf2_iterations == 200_000


def test_engineer_password_config_round_trip(tmp_path) -> None:
    """hash -> save_config -> reload -> verify (no plaintext in file)."""
    from nanobot.config.loader import load_config, save_config
    from nanobot.config.schema import Config
    from robot_ai.library.auth import hash_password, verify_password
    cfg_path = tmp_path / "config.json"
    pw = "test-secret-123"
    cfg = Config()
    cfg.robot_ai.engineer.password_hash = hash_password(pw, iterations=1000)
    save_config(cfg, cfg_path)
    raw = cfg_path.read_text(encoding="utf-8")
    assert "test-secret-123" not in raw  # no plaintext
    assert "pbkdf2_sha256" in raw
    cfg2 = load_config(cfg_path)
    assert verify_password(pw, cfg2.robot_ai.engineer.password_hash) is True
    assert verify_password("wrong", cfg2.robot_ai.engineer.password_hash) is False


def test_cli_set_password_match(tmp_path) -> None:
    """Task 6 deprecated alias: matching passwords -> exit 0, hash in users.json (admin),
    no plaintext. `--config` is ignored; the alias updates the admin user in users.json."""
    import json
    from unittest.mock import patch

    from typer.testing import CliRunner

    from robot_server.admin_cli import engineer_app
    from robot_ai.library.auth import hash_password, verify_password
    from robot_ai.library.users import UserRegistry
    users_json = tmp_path / "users.json"
    audit = tmp_path / "a.jsonl"
    UserRegistry(users_json, audit_path=audit).create(
        "admin", "engineer", hash_password("oldpw", iterations=100_000))
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["mypw123", "mypw123"]):
        result = runner.invoke(engineer_app, ["set-password", "--users-path", str(users_json),
                                               "--audit-path", str(audit)])
    assert result.exit_code == 0
    raw = users_json.read_text(encoding="utf-8")
    assert "mypw123" not in raw
    assert "pbkdf2_sha256" in raw
    admin = next(u for u in json.loads(raw)["users"].values() if u["username"] == "admin")
    assert verify_password("mypw123", admin["password_hash"]) is True


def test_cli_set_password_mismatch(tmp_path) -> None:
    """Mismatched passwords -> exit 1, config not written."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from robot_server.admin_cli import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["pw1", "pw2"]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 1
    assert not cfg.exists()  # config not written


def test_cli_set_password_empty(tmp_path) -> None:
    """Empty password -> exit 1, config not written."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from robot_server.admin_cli import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["", ""]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 1
    assert not cfg.exists()  # config not written


def test_cli_output_no_password(tmp_path) -> None:
    """CLI output must not contain the password (Task 6 deprecated alias)."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from robot_server.admin_cli import engineer_app
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry
    users_json = tmp_path / "users.json"
    audit = tmp_path / "a.jsonl"
    UserRegistry(users_json, audit_path=audit).create(
        "admin", "engineer", hash_password("oldpw", iterations=100_000))
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["secret-pw-99", "secret-pw-99"]):
        result = runner.invoke(engineer_app, ["set-password", "--users-path", str(users_json),
                                               "--audit-path", str(audit)])
    assert result.exit_code == 0  # command succeeded
    assert "secret-pw-99" not in result.output


def test_config_schema_engineer_from_dict() -> None:
    from nanobot.config.schema import Config
    cfg = Config.model_validate({
        "robot_ai": {"engineer": {"password_hash": "pbkdf2_sha256$200000$abc$def", "pbkdf2_iterations": 200_000}},
    })
    assert cfg.robot_ai.engineer.password_hash == "pbkdf2_sha256$200000$abc$def"
    assert cfg.robot_ai.engineer.pbkdf2_iterations == 200_000


def test_pbkdf2_iterations_below_minimum_rejected() -> None:
    """pbkdf2_iterations < 100_000 (incl 0, negative) -> ValidationError."""
    from pydantic import ValidationError

    from nanobot.config.schema import EngineerConfig
    for bad in [0, -1, 99_999]:
        try:
            EngineerConfig(pbkdf2_iterations=bad)
            assert False, f"Should reject iterations={bad}"
        except ValidationError:
            pass
