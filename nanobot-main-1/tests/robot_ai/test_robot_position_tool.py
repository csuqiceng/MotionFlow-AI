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
