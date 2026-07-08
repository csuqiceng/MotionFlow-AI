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
        r"C:/Users/KY/Desktop/yjcao/ai_pipeline_prototype-trae-solo-agent-cINULN (1)/ai_pipeline_prototype-trae-solo-agent-cINULN/重构版本/data",
    )
)
OUT = Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai" / "knowledge.json"

if __name__ == "__main__":
    entries = migrate_knowledge(LEGACY, OUT)
    print(f"Migrated {len(entries)} entries -> {OUT}")
