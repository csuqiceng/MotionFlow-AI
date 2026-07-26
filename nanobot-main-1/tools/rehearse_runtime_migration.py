"""Run an offline, copy-only rehearsal of the robot runtime migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

# A build virtualenv can have another worktree installed in editable mode.
# Prefer the checkout that owns this tool.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from robot_platform.migration_rehearsal import rehearse_legacy_runtime_migration


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a legacy robot runtime to an empty scratch directory and "
            "verify robot_ai -> robot_platform migration without starting a server or backend."
        )
    )
    parser.add_argument("--source-runtime", required=True, help="Existing runtime directory; never modified.")
    parser.add_argument("--scratch-root", required=True, help="Empty directory that receives the rehearsal copy.")
    args = parser.parse_args(argv)
    try:
        report = rehearse_legacy_runtime_migration(args.source_runtime, args.scratch_root)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
