from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from robot_platform.backends.factory import RobotBackend, RobotBackendConfig
from robot_platform.backends.product_wiring import create_product_robot_backend
from robot_platform.models import RobotState, ToolResult


BackendFactory = Callable[[RobotBackendConfig], RobotBackend]


def run_zmotion_readonly_smoke(
    *,
    confirmed_readonly_diagnostics: bool = False,
    config: RobotBackendConfig | None = None,
    backend_factory: BackendFactory = create_product_robot_backend,
) -> dict[str, Any]:
    if not confirmed_readonly_diagnostics:
        return ToolResult.failure(
            state="readonly_diagnostics_confirmation_required",
            message=(
                "Refusing to contact the ZMotion controller until "
                "--read-only-diagnostics is supplied. This check only reads controller state."
            ),
            errors=[{"code": "readonly_diagnostics_confirmation_required"}],
        ).to_dict()

    resolved_config = replace(config or RobotBackendConfig.from_env(), mode="zmotion_readonly")
    missing = _missing_required_config(resolved_config)
    if missing:
        return ToolResult.failure(
            state="zmotion_readonly_configuration_missing",
            message=format_zmotion_readonly_setup_help(resolved_config),
            data={"config": _safe_config(resolved_config), "missing": missing},
            errors=[{"code": "zmotion_readonly_configuration_missing", "missing": missing}],
        ).to_dict()

    try:
        backend = backend_factory(resolved_config)
        robot_state = backend.get_state()
    except Exception as exc:
        return ToolResult.failure(
            state="zmotion_readonly_smoke_failed",
            message=f"ZMotion read-only smoke check failed: {exc}",
            data={"config": _safe_config(resolved_config)},
            errors=[{"code": "zmotion_readonly_smoke_failed", "detail": str(exc)}],
        ).to_dict()

    robot_state_data = _robot_state_to_dict(robot_state)
    if not robot_state_data.get("connected_real_device"):
        return ToolResult.failure(
            state="zmotion_readonly_smoke_failed",
            message="ZMotion read-only smoke check did not confirm a connected real device.",
            data={"config": _safe_config(resolved_config), "robot_state": robot_state_data},
            errors=[{"code": "real_device_not_connected"}],
        ).to_dict()

    return ToolResult.success(
        state="zmotion_readonly_smoke_passed",
        message="ZMotion read-only smoke check passed.",
        data={"config": _safe_config(resolved_config), "robot_state": robot_state_data},
    ).to_dict()


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    config = _config_from_args(args)
    result = run_zmotion_readonly_smoke(
        confirmed_readonly_diagnostics=args.read_only_diagnostics,
        config=config,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["message"])
    return 0 if result.get("ok") else 1


def _config_from_args(args: argparse.Namespace) -> RobotBackendConfig:
    config = RobotBackendConfig.from_env()
    return replace(
        config,
        controller_host=args.host or config.controller_host,
        zmotion_wrapper_path=args.wrapper_path or config.zmotion_wrapper_path,
        zmotion_dll_dir=args.dll_dir or config.zmotion_dll_dir,
    )


def format_zmotion_readonly_setup_help(config: RobotBackendConfig | None = None) -> str:
    resolved = config or RobotBackendConfig.from_env()
    host = resolved.controller_host or "10.168.3.21"
    return "\n".join(
        [
            "ZMotion read-only diagnostics need the controller host and SDK paths before connecting.",
            "Set these variables in the same PowerShell session:",
            "$env:ROBOT_AI_BACKEND=zmotion_readonly",
            f"$env:ROBOT_CONTROLLER_HOST={host}",
            "$env:ROBOT_ZMOTION_WRAPPER_PATH=C:\\path\\to\\zauxdllPython.py",
            "$env:ROBOT_ZMOTION_DLL_DIR=C:\\path\\to\\zauxdll\\directory",
            "Then run:",
            ".venv-robot-desktop\\Scripts\\python.exe tools\\verify_zmotion_readonly.py --read-only-diagnostics --json",
            "This diagnostic only reads pose/status registers and does not write IEEE(32) or issue motion commands.",
        ]
    )


def _missing_required_config(config: RobotBackendConfig) -> list[str]:
    missing: list[str] = []
    if not config.controller_host.strip():
        missing.append("ROBOT_CONTROLLER_HOST")
    if not config.zmotion_wrapper_path.strip():
        missing.append("ROBOT_ZMOTION_WRAPPER_PATH")
    if not config.zmotion_dll_dir.strip():
        missing.append("ROBOT_ZMOTION_DLL_DIR")
    return missing


def _robot_state_to_dict(robot_state: RobotState | dict[str, Any]) -> dict[str, Any]:
    if isinstance(robot_state, RobotState):
        return robot_state.to_dict()
    return dict(robot_state)


def _safe_config(config: RobotBackendConfig) -> dict[str, str]:
    return {
        "mode": config.mode,
        "controller_host": config.controller_host,
        "zmotion_wrapper_path": config.zmotion_wrapper_path,
        "zmotion_dll_dir": config.zmotion_dll_dir,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
