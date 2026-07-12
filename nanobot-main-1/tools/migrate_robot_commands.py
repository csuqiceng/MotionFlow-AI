"""Migrate legacy ``query_table.json`` into the robot command library.

Mirrors ``tools/migrate_robot_flows.py``. Reads the legacy file (default
``data/legacy/query_table.json``) and writes ``commands.json`` + ``audit.jsonl``
under ``~/.nanobot/robot_ai/`` (override both with env vars for tests / custom
installs). Idempotent and audit-deduped — safe to re-run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.library.migration import migrate_commands  # noqa: E402

LEGACY_DIR = Path(os.environ.get("ROBOT_LEGACY_DATA_DIR", r"data/legacy"))
LEGACY_FILE = Path(os.environ.get("ROBOT_LEGACY_QUERY_TABLE", "query_table.json"))
LEGACY = LEGACY_DIR / LEGACY_FILE
OUT_DIR = Path(os.environ.get("ROBOT_LIBRARY_OUT_DIR", str(Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai")))
COMMANDS_OUT = OUT_DIR / "commands.json"
AUDIT_OUT = OUT_DIR / "audit.jsonl"


def main() -> int:
    result = migrate_commands(LEGACY, COMMANDS_OUT, AUDIT_OUT)
    print(f"Migration id: {result.migration_id}")
    print(f"Migrated {len(result.migrated)} commands:")
    for cid, name in result.migrated:
        print(f"  + {cid}  {name}")
    print(f"Skipped {len(result.skipped)} records:")
    for func, name, reason in result.skipped:
        print(f"  - func={func}  {name}  ({reason})")
    if result.dropped_aliases:
        print(f"Dropped {result.dropped_aliases} conflicting aliases.")
    if result.audit_error:
        print(f"ERROR: commands written but audit write failed: {result.audit_error}")
        print("Re-run to backfill the audit record.")
        return 1
    if result.audit_already_present:
        state = "skipped (already present)"
    else:
        state = "written"
    print(f"Audit: {state} -> {AUDIT_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
