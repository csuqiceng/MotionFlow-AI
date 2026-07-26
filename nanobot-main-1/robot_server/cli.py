"""Foreground entry point for the single-process robot server."""

from __future__ import annotations

import argparse
from dataclasses import replace
import os
from pathlib import Path
import sys

from aiohttp import web

from robot_platform import RobotPlatform, configure_robot_runtime, get_robot_data_dir
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.product_wiring import create_product_robot_backend
from robot_platform.tools.robot_tools import RobotToolFacade
from robot_server.app import RobotServerConfig, create_robot_server_app
from robot_server.product_profile import load_product_profile
from robot_server.runtime import create_agent_runtime


def bundled_webui_dist() -> Path | None:
    """Locate the robot-specific single-page UI from source or PyInstaller."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    candidate = bundle_root / "robot_server" / "webui"
    return candidate if (candidate / "index.html").is_file() else None


def build_product_platform(data_dir: Path) -> tuple[RobotPlatform, list[str]]:
    """Compose the selected backend once, before accepting any control call.

    The persisted profile controls only product-level backend and Tool choices.
    Controller host/SDK paths remain deployment configuration, and AI settings
    never enter this composition path.
    """
    profile = load_product_profile(data_dir)
    backend_config = replace(
        RobotBackendConfig.from_env(),
        mode=profile["backend_mode"],
    )
    backend = create_product_robot_backend(backend_config)
    platform = RobotPlatform(
        facade=RobotToolFacade(backend=backend),
        backend_config=backend_config,
    )
    return platform, list(profile["enabled_tools"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local robot-control server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ROBOT_SERVER_PORT", "8765")))
    parser.add_argument("--access-token", default=os.environ.get("ROBOT_SERVER_ACCESS_TOKEN", ""))
    parser.add_argument("--static-dist", type=Path)
    parser.add_argument("--config", type=Path, help="Existing nanobot-compatible provider configuration")
    parser.add_argument("--data-dir", type=Path, help="Robot library, audit, and runtime data directory")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"} and not args.access_token.strip():
        parser.error("--access-token is required when binding beyond loopback")
    runtime_data_dir = args.data_dir or get_robot_data_dir()
    configure_robot_runtime(data_dir=runtime_data_dir)
    try:
        platform, enabled_tools = build_product_platform(runtime_data_dir)
        agent_runtime = create_agent_runtime(args.config, enabled_tools=enabled_tools)
    except ValueError as exc:
        parser.error(str(exc))
    app = create_robot_server_app(config=RobotServerConfig(
        access_token=args.access_token,
        static_dist_path=args.static_dist or bundled_webui_dist(),
        agent_runtime=agent_runtime,
        deployment_config_path=args.config,
        robot_data_dir=runtime_data_dir,
    ), platform=platform)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
