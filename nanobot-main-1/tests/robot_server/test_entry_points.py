from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_module_entry_point_routes_to_robot_server_not_chat_cli() -> None:
    source = (ROOT / "nanobot" / "__main__.py").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "robot_server.cli" in source
    assert "nanobot.cli" not in source
    assert 'nanobot = "nanobot.cli.commands:app"' not in project
    assert 'robot-server = "robot_server.cli:main"' in project
