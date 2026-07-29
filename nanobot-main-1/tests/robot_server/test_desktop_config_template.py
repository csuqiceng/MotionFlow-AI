from __future__ import annotations

import json
import shutil
from pathlib import Path

from robot_platform.adapters import FileRobotPositionLibraryAdapter
from robot_platform.application import RobotLibraryCatalogApplicationService
from robot_server.library_api import RobotLibraryService

ROOT = Path(__file__).resolve().parents[2]


def test_desktop_template_omits_chat_transport_and_gateway_configuration() -> None:
    template = ROOT / "desktop" / "electron" / "config.default.template.json"
    config = json.loads(template.read_text(encoding="utf-8"))

    assert "channels" not in config
    assert "gateway" not in config
    assert "api" not in config
    assert config["providers"]["dashscope"]["apiKey"] == "__ORGANIZATION_API_KEY__"
    assert all(
        provider.get("apiKey") in {None, "__ORGANIZATION_API_KEY__"}
        for provider in config["providers"].values()
    )
    assert config["tools"]["enabled_tools"] == [
        "robot_arm", "robot_flow", "robot_knowledge", "robot_position", "robot_library", "cron",
    ]


def test_desktop_robot_defaults_are_project_configuration_assets() -> None:
    defaults = ROOT / "desktop" / "electron" / "defaults" / "robot_ai"
    packaged_positions = json.loads((defaults / "positions.json").read_text(encoding="utf-8"))
    canonical_positions = json.loads(
        (ROOT / "robot_platform" / "positions" / "seed_positions.json").read_text(encoding="utf-8")
    )
    flows = json.loads((defaults / "flows.json").read_text(encoding="utf-8"))

    assert packaged_positions["positions"] == canonical_positions["positions"]
    assert flows["version"] == "1.1"
    assert flows["flows"]


def test_packaged_project_flow_configuration_is_visible_in_library(tmp_path) -> None:
    seed = ROOT / "desktop" / "electron" / "defaults" / "robot_ai" / "flows.json"
    shutil.copyfile(seed, tmp_path / "flows.json")

    status, body = RobotLibraryService(
        RobotLibraryCatalogApplicationService(
            FileRobotPositionLibraryAdapter(tmp_path),
        )
    ).list_flows()

    assert status == 200
    assert body["data"]["total"] == 4
    assert (tmp_path / "flows.json").read_text(encoding="utf-8").find('"schema_version": "2.0"') >= 0
