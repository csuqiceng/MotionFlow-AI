from __future__ import annotations

import json
from pathlib import Path

from nanobot.config.loader import load_config, save_config


def test_save_config_drops_legacy_chat_transport_sections(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"channels": {"websocket": {"enabled": true}}, "gateway": {"port": 1234}}', encoding="utf-8")

    save_config(load_config(path), path)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert "channels" not in written
    assert "gateway" not in written
