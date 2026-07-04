from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from robot_ai.bridge import RobotApi
from robot_ai.models import ToolResult
from robot_ai.runtime import (
    desktop_runtime_dependency_status,
    format_desktop_dependency_help,
)


DependencyStatusProvider = Callable[[], dict[str, Any]]
ApiFactory = Callable[[], RobotApi]


def run_robot_desktop_smoke(
    *,
    dependency_status_provider: DependencyStatusProvider = desktop_runtime_dependency_status,
    api_factory: ApiFactory = RobotApi,
) -> dict[str, Any]:
    status = dependency_status_provider()
    if not status.get("ready"):
        return ToolResult.failure(
            state="runtime_dependencies_missing",
            message=format_desktop_dependency_help(status),
            data=status,
            errors=[{"code": "runtime_dependencies_missing"}],
        ).to_dict()

    try:
        api = api_factory()
        health = api.health()
        move_axis = api.move_axis("x", 5.0)
        robot_state = api.get_robot_state()
        voice = api.get_voice_state()
    except Exception as exc:
        return ToolResult.failure(
            state="runtime_smoke_failed",
            message=f"Robot desktop runtime smoke check failed: {exc}",
            errors=[{"code": "runtime_smoke_failed", "detail": str(exc)}],
        ).to_dict()

    checks = {
        "health": health,
        "move_axis": move_axis,
        "robot_state": robot_state,
        "voice": voice,
        "dependencies": status,
    }
    if not health.get("ok") or not move_axis.get("ok") or not voice.get("ok"):
        return ToolResult.failure(
            state="runtime_smoke_failed",
            message="Robot desktop runtime smoke check returned an unhealthy result.",
            data=checks,
            errors=[{"code": "runtime_smoke_unhealthy"}],
        ).to_dict()

    return ToolResult.success(
        state="runtime_smoke_passed",
        message="Robot desktop runtime smoke check passed.",
        data=checks,
    ).to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Robot AI desktop runtime.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = run_robot_desktop_smoke()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["message"])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
