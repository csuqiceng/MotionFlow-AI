from __future__ import annotations

import json

import pytest

from nanobot.config.loader import load_config, save_config
from robot_ai.execution import mode


def test_execution_mode_survives_typed_config_round_trip(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {"execution_mode": "auto_after_safety_check"}}),
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert config.tools.execution_mode == "auto_after_safety_check"
    assert saved["tools"]["executionMode"] == "auto_after_safety_check"


@pytest.mark.parametrize("field_name", ["executionMode", "execution_mode"])
def test_mode_reader_uses_active_config_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {field_name: "auto_after_safety_check"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path))

    assert mode._load_execution_mode() == "auto_after_safety_check"


@pytest.mark.parametrize(
    "payload",
    [{}, {"tools": {}}, {"tools": {"executionMode": "invalid"}}],
)
def test_mode_reader_fails_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch, payload: dict
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path))

    assert mode._load_execution_mode() == "dry_run_only"
