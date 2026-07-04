from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.runtime import (
    desktop_runtime_dependency_status,
    format_desktop_dependency_help,
)
from robot_desktop import launch_desktop_window


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the Robot AI pywebview window.")
    parser.add_argument("--auto-close", action="store_true", help="Close the window after startup.")
    parser.add_argument(
        "--auto-close-delay",
        type=float,
        default=1.0,
        help="Seconds to wait before auto-closing the probe window.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    status = desktop_runtime_dependency_status()
    if not status["ready"]:
        result = {
            "ok": False,
            "state": "runtime_dependencies_missing",
            "message": format_desktop_dependency_help(status),
            "data": status,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["message"])
        return 1

    import webview

    try:
        launch_desktop_window(
            webview_module=webview,
            start=True,
            auto_close=args.auto_close,
            auto_close_delay_sec=args.auto_close_delay,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "state": "desktop_window_probe_failed",
            "message": f"Robot desktop window probe failed: {exc}",
            "errors": [{"code": "desktop_window_probe_failed", "detail": str(exc)}],
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["message"])
        return 1

    result = {
        "ok": True,
        "state": "desktop_window_probe_passed",
        "message": "Robot desktop pywebview window probe passed.",
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
