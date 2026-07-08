from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.backends.factory import RobotBackendConfig
from robot_ai.zmotion_readonly_smoke import run_zmotion_readonly_smoke


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ZMotion controller read-only status access.")
    parser.add_argument(
        "--read-only-diagnostics",
        action="store_true",
        help="Allow one read-only controller status check. No motion writes are issued.",
    )
    parser.add_argument("--host", help="Override ROBOT_CONTROLLER_HOST.")
    parser.add_argument("--wrapper-path", help="Override ROBOT_ZMOTION_WRAPPER_PATH.")
    parser.add_argument("--dll-dir", help="Override ROBOT_ZMOTION_DLL_DIR.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    config = RobotBackendConfig.from_env()
    config = RobotBackendConfig(
        mode=config.mode,
        controller_host=args.host or config.controller_host,
        zmotion_wrapper_path=args.wrapper_path or config.zmotion_wrapper_path,
        zmotion_dll_dir=args.dll_dir or config.zmotion_dll_dir,
    )
    result = run_zmotion_readonly_smoke(
        confirmed_readonly_diagnostics=args.read_only_diagnostics,
        config=config,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["message"])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
