from __future__ import annotations

import json

from robot_ai.positions.registry import PositionRegistry
from tools.migrate_robot_positions import migrate_positions


def test_migration_preserves_pose(tmp_path) -> None:
    src = tmp_path / "old"
    src.mkdir()
    (src / "position_registry.json").write_text(
        json.dumps(
            {
                "version": "1.1",
                "positions": [
                    {
                        "name": "A",
                        "pose": [1000.0, 0.0, 800.0, 0.0, 90.0, 0.0],
                        "spd": 50,
                        "move_type": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "positions.json"
    n = migrate_positions(src / "position_registry.json", out)
    assert n == 1
    assert PositionRegistry(out).resolve("A")["x"] == 1000.0
