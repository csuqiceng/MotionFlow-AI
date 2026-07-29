from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_robot_runtime_boundary_has_no_chat_transport_terms() -> None:
    sources = [
        ROOT / "ai_runtime" / "engine_contract.py",
        ROOT / "ai_runtime" / "contracts.py",
        ROOT / "robot_server" / "app.py",
        ROOT / "robot_server" / "websocket_frames.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in sources)

    assert "nanobot.bus" not in text
    assert "chat_id" not in text
    assert "sender_id" not in text
    assert "channel=" not in text
