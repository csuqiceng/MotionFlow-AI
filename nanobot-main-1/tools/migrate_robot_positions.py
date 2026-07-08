from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.positions.registry import NamedPosition, PositionRegistry  # noqa: E402


def migrate_positions(src_path: str | Path, out_path: str | Path) -> int:
    src = Path(src_path)
    if not src.exists():
        return 0
    payload = json.loads(src.read_text(encoding="utf-8"))
    positions = [
        NamedPosition.from_dict(p)
        for p in payload.get("positions", [])
        if p.get("name")
    ]
    PositionRegistry(out_path).replace(positions)
    return len(positions)


if __name__ == "__main__":
    legacy = Path(
        os.environ.get(
            "ROBOT_LEGACY_DATA_DIR",
            r"C:/Users/KY/Desktop/yjcao/ai_pipeline_prototype-trae-solo-agent-cINULN (1)/ai_pipeline_prototype-trae-solo-agent-cINULN/重构版本/data",
        )
    )
    out = Path.home() / ".nanobot" / "robot_ai" / "positions.json"
    n = migrate_positions(legacy / "position_registry.json", out)
    print(f"Migrated {n} positions -> {out}")
