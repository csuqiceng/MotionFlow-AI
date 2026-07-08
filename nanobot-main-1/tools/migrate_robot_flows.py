from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.flow.aliases import migrate_aliases  # noqa: E402
from robot_ai.flow.migration import migrate_flows  # noqa: E402

LEGACY = Path(
    os.environ.get(
        "ROBOT_LEGACY_DATA_DIR",
        r"C:/Users/KY/Desktop/yjcao/ai_pipeline_prototype-trae-solo-agent-cINULN (1)/ai_pipeline_prototype-trae-solo-agent-cINULN/重构版本/data",
    )
)
OUT_DIR = Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai"
FLOWS_OUT = OUT_DIR / "flows.json"
ALIASES_OUT = OUT_DIR / "flow_aliases.json"

if __name__ == "__main__":
    flows = migrate_flows(LEGACY, FLOWS_OUT)
    aliases = migrate_aliases(LEGACY, ALIASES_OUT)
    print(f"Migrated {flows} flows -> {FLOWS_OUT}")
    print(f"Migrated {aliases} aliases -> {ALIASES_OUT}")
