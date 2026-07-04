from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.runtime_smoke import run_robot_desktop_smoke


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Robot AI desktop runtime.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    result = run_robot_desktop_smoke()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["message"])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
