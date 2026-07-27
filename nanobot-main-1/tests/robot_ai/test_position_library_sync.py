from __future__ import annotations

import json

from robot_platform.library.mutation_service import (
    RobotLibraryMutationService,
    ensure_published_position_commands,
)
from robot_platform.positions.defaults import ensure_default_positions


def test_legacy_named_positions_are_available_in_a_migrated_registry(tmp_path) -> None:
    ensure_default_positions(tmp_path / "positions.json")
    payload = json.loads((tmp_path / "positions.json").read_text(encoding="utf-8"))
    assert {item["name"] for item in payload["positions"]} >= {
        "home", "位置A", "位置B", "位置C"
    }


def test_saved_position_is_published_as_a_linear_move_command(tmp_path) -> None:
    service = RobotLibraryMutationService(tmp_path)
    result = service.create_position(
        {
            "name": "测试",
            "pose": {"x": 999.99, "y": 0, "z": 800.04, "rx": -9.6, "ry": 90, "rz": -9.6},
            "spd": 20,
            "move_type": 0,
        },
        actor="operator:test",
    )
    assert result["command"]["published_version"] == 1
    command = result["command"]["versions"]["1"]
    assert command["component_id"] == "linear_move"
    assert command["parameters"]["target_x"] == 999.99

    # Existing positions from an older install are backfilled when the library
    # is opened, not only when they are saved again.
    ensure_published_position_commands(tmp_path)
    commands = json.loads((tmp_path / "commands.json").read_text(encoding="utf-8"))
    assert "测试" in commands["commands"]
