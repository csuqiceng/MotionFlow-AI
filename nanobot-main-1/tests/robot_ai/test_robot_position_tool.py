from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.robot_position import RobotPositionTool  # noqa: E402
from robot_ai.positions.registry import (  # noqa: E402
    NamedPosition,
    PositionRegistry,
)


def _run(tool, **kw):
    return json.loads(asyncio.run(tool.execute(**kw)))


def test_list_get_resolve(tmp_path) -> None:
    p = tmp_path / "pos.json"
    PositionRegistry(p).replace(
        [NamedPosition(name="A", pose=[1000.0, 0.0, 800.0, 0.0, 90.0, 0.0])]
    )
    tool = RobotPositionTool(str(p))
    assert _run(tool, action="list")["data"]["count"] == 1
    assert _run(tool, action="get", name="a")["data"]["position"]["pose"][0] == 1000.0
    r = _run(tool, action="resolve", name="A")
    assert r["data"]["pose"]["x"] == 1000.0


def test_unknown_position_not_found(tmp_path) -> None:
    tool = RobotPositionTool(str(tmp_path / "pos.json"))
    r = _run(tool, action="resolve", name="ghost")
    assert r["ok"] is False
    assert r["state"] == "position_not_found"


def test_reads_published_position_command_and_flow(tmp_path) -> None:
    (tmp_path / "positions.json").write_text('{"positions": []}', encoding="utf-8")
    (tmp_path / "commands.json").write_text(
        json.dumps({
            "schema_version": "2.0",
            "commands": {
                "position-a": {
                    "command_id": "position-a", "published_version": 1, "draft": None,
                    "versions": {"1": {
                        "id": "position-a", "name": "位置A", "aliases": ["A"],
                        "component_id": "linear_move", "parameters": {
                            "target_x": 1000, "target_y": 0, "target_z": 800,
                            "target_rx": 0, "target_ry": 90, "target_rz": 0,
                        },
                    }},
                },
            },
        }),
        encoding="utf-8",
    )
    (tmp_path / "flows.json").write_text(
        json.dumps({
            "schema_version": "2.0",
            "flows": {"搬运": {"flow_id": "搬运", "published_version": 1, "draft": None,
                "versions": {"1": {"name": "搬运流程", "steps": [{"step_id": 1}]}}}},
        }),
        encoding="utf-8",
    )
    tool = RobotPositionTool(data_dir=tmp_path)

    listing = _run(tool, action="list")
    assert listing["data"]["position_commands"][0]["name"] == "位置A"
    assert listing["data"]["flows"][0]["name"] == "搬运流程"
    assert _run(tool, action="resolve", name="A")["data"]["pose"]["x"] == 1000.0
    flow = _run(tool, action="get", name="搬运流程")
    assert flow["data"]["resource_type"] == "flow"
    assert _run(tool, action="resolve", name="搬运流程")["state"] == "position_not_single_pose"
