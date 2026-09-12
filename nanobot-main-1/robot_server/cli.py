"""Foreground entry point for the single-process robot server."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from aiohttp import web

from robot_platform import get_robot_data_dir
from robot_server.app import RobotServerConfig, create_robot_server_app
from robot_server.bootstrap import (
    build_product_platform,
    compose_product_runtime_container,
)


def bundled_webui_dist() -> Path | None:
    """Locate the robot-specific single-page UI from source or PyInstaller."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    candidate = bundle_root / "robot_server" / "webui"
    return candidate if (candidate / "index.html").is_file() else None


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
    try:
        container = compose_product_runtime_container(RobotServerConfig(
            access_token=args.access_token,
            static_dist_path=args.static_dist or bundled_webui_dist(),
            deployment_config_path=args.config,
            robot_data_dir=runtime_data_dir,
        ))
    except ValueError as exc:
        parser.error(str(exc))
    app = create_robot_server_app(container=container)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
