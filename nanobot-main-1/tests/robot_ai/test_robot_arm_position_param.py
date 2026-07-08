from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.robot_arm import RobotArmTool  # noqa: E402
from robot_ai.positions.registry import (  # noqa: E402
    NamedPosition,
    PositionRegistry,
)


def _run(tool, **kw):
    return json.loads(asyncio.run(tool.execute(**kw)))


def test_linear_move_with_named_position_resolves(tmp_path) -> None:
    p = tmp_path / "pos.json"
    PositionRegistry(p).replace(
        [NamedPosition(name="A", pose=[1000.0, 0.0, 800.0, 0.0, 90.0, 0.0])]
    )
    captured: dict = {}

    def fake_runner(*, request, config=None, client_factory=None, executor_factory=None):
        captured["pose"] = request.parameters.get("target_pose")
        return {
            "ok": True,
            "state": "zmotion_operator_dry_run",
            "data": {"real_execution": False},
            "errors": [],
        }

    tool = RobotArmTool(operator_runner=fake_runner, positions_path=str(p))
    r = _run(tool, action="linear_move", position="A", speed_pct=50.0)
    assert r["ok"] is True
    assert captured["pose"]["x"] == 1000.0


def test_linear_move_unknown_position_returns_not_found(tmp_path) -> None:
    tool = RobotArmTool(positions_path=str(tmp_path / "pos.json"))
    r = _run(tool, action="linear_move", position="ghost", speed_pct=50.0)
    assert r["ok"] is False
    assert r["state"] == "position_not_found"
