from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_desktop_template_omits_chat_transport_and_gateway_configuration() -> None:
    template = ROOT / "desktop" / "electron" / "config.default.template.json"
    config = json.loads(template.read_text(encoding="utf-8"))

    assert "channels" not in config
    assert "gateway" not in config
    assert "api" not in config
    assert config["tools"]["enabled_tools"] == [
        "robot_arm", "robot_flow", "robot_knowledge", "robot_position", "cron",
    ]
