from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.knowledge.migration import migrate_knowledge

LEGACY = Path(
    os.environ.get(
        "ROBOT_LEGACY_DATA_DIR",
        r"data/legacy",
    )
)
OUT = Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai" / "knowledge.json"

if __name__ == "__main__":
    entries = migrate_knowledge(LEGACY, OUT)
    print(f"Migrated {len(entries)} entries -> {OUT}")
