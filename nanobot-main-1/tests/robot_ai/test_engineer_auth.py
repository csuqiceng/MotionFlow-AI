# tests/robot_ai/test_engineer_auth.py
from __future__ import annotations

from robot_ai.library.auth import (
    EngineerTokenStore,
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


def test_token_store_issue_check_revoke() -> None:
    store = EngineerTokenStore(ttl_seconds=3600)
    token = store.issue()
    assert store.check(token) is True
    store.revoke(token)
    assert store.check(token) is False


def test_token_store_rejects_unknown() -> None:
    store = EngineerTokenStore()
    assert store.check("bogus") is False


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
    """CliRunner + mock getpass: matching passwords -> exit 0, hash in config, no plaintext."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from nanobot.cli.commands import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["mypw123", "mypw123"]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 0
    raw = cfg.read_text(encoding="utf-8")
    assert "mypw123" not in raw
    assert "pbkdf2_sha256" in raw
    # reload + verify_password
    from nanobot.config.loader import load_config
    from robot_ai.library.auth import verify_password
    cfg2 = load_config(cfg)
    assert verify_password("mypw123", cfg2.robot_ai.engineer.password_hash) is True


def test_cli_set_password_mismatch(tmp_path) -> None:
    """Mismatched passwords -> exit 1, config not written."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from nanobot.cli.commands import engineer_app
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

    from nanobot.cli.commands import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["", ""]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 1
    assert not cfg.exists()  # config not written


def test_cli_output_no_password(tmp_path) -> None:
    """CLI output must not contain the password."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from nanobot.cli.commands import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["secret-pw-99", "secret-pw-99"]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
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


def test_token_store_rejects_expired() -> None:
    """An expired token must be rejected by check(), and not revive on later calls."""
    import robot_ai.library.auth as auth
    store = auth.EngineerTokenStore(ttl_seconds=3600)
    token = store.issue()
    assert store.check(token) is True
    # Force the token to be expired (expiry strictly in the past).
    store._tokens[token] = auth.time.monotonic() - 1.0
    assert store.check(token) is False
    # A previously-rejected/expired token must not become valid again.
    assert store.check(token) is False
    # Store still rejects unknown tokens after expiry purge.
    assert store.check("bogus") is False
