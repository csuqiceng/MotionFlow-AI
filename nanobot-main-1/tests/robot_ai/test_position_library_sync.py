from __future__ import annotations

import json
import importlib.resources

from robot_platform.library.mutation_service import (
    RobotLibraryMutationService,
    ensure_published_position_commands,
)
from robot_platform.positions.defaults import ensure_default_positions


def test_packaged_position_configuration_is_imported_without_code_defaults(tmp_path) -> None:
    expected = json.loads(
        (
            importlib.resources.files("robot_platform.positions")
            / "seed_positions.json"
        ).read_text(encoding="utf-8")
    )["positions"]
    ensure_default_positions(tmp_path / "positions.json")
    payload = json.loads((tmp_path / "positions.json").read_text(encoding="utf-8"))
    assert payload["positions"] == sorted(expected, key=lambda item: item["name"])


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


def test_position_import_does_not_rewrite_existing_project_motion_command(tmp_path) -> None:
    service = RobotLibraryMutationService(tmp_path)
    service.create_command(
        {
            "name": "配置位置",
            "component_id": "linear_move",
            "parameters": {
                "target_x": 1,
                "target_y": 2,
                "target_z": 3,
                "target_rx": 4,
                "target_ry": 5,
                "target_rz": 6,
                "spd_pct": 20,
                "acc_pct": 37,
                "dec_pct": 43,
                "move_type": 0,
                "stop_cmd": 0,
            },
        },
        actor="engineer:config-import",
    )
    from robot_platform.positions.registry import NamedPosition, PositionRegistry

    PositionRegistry(tmp_path / "positions.json").register(
        NamedPosition("配置位置", [10, 20, 30, 40, 50, 60], spd=10)
    )

    ensure_published_position_commands(tmp_path)
    commands = json.loads((tmp_path / "commands.json").read_text(encoding="utf-8"))
    published = commands["commands"]["配置位置"]["versions"]["1"]
    assert published["parameters"]["acc_pct"] == 37
    assert published["parameters"]["dec_pct"] == 43
