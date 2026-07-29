from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from robot_ai.positions.registry import (  # noqa: E402
    NamedPosition,
    PositionRegistry,
)

from nanobot.agent.tools.robot_arm import RobotArmTool  # noqa: E402
from robot_platform.adapters import FileRobotPositionLibraryAdapter  # noqa: E402
from robot_platform.application import RobotPositionApplicationService  # noqa: E402


def _run(tool, **kw):
    return json.loads(asyncio.run(tool.execute(**kw)))


def test_linear_move_with_named_position_resolves(tmp_path) -> None:
    p = tmp_path / "pos.json"
    PositionRegistry(p).replace(
        [NamedPosition(name="A", pose=[1000.0, 0.0, 800.0, 0.0, 90.0, 0.0])]
    )
    captured: dict = {}

    class FakeDryRunApplication:
        def preview_command(self, command, parameters):
            captured["pose"] = parameters.get("target_pose")
            return SimpleNamespace(
                ok=True,
                payload={
                    "ok": True,
                    "state": "zmotion_operator_dry_run",
                    "data": {"real_execution": False},
                    "errors": [],
                },
                error=None,
            )

    tool = RobotArmTool(
        dry_run_application=FakeDryRunApplication(),
        position_application=RobotPositionApplicationService(
            FileRobotPositionLibraryAdapter(tmp_path, positions_path=p),
        ),
    )
    r = _run(tool, action="linear_move", position="A", speed_pct=50.0)
    assert r["ok"] is True
    assert captured["pose"]["x"] == 1000.0


def test_linear_move_unknown_position_returns_not_found(tmp_path) -> None:
    tool = RobotArmTool(
        position_application=RobotPositionApplicationService(
            FileRobotPositionLibraryAdapter(
                tmp_path, positions_path=tmp_path / "pos.json",
            ),
        )
    )
    r = _run(tool, action="linear_move", position="ghost", speed_pct=50.0)
    assert r["ok"] is False
    assert r["state"] == "position_not_found"


def test_effect_identity_normalizes_named_position_numbers_defaults_and_noise() -> None:
    class PositionApplication:
        def query(self, _request):
            return SimpleNamespace(
                ok=True,
                payload={"pose": {
                    "x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6,
                }},
                error=None,
            )

    tool = RobotArmTool(position_application=PositionApplication())
    named = tool.canonical_effect_parameters({
        "action": "linear_move", "position": "A", "ignored_noise": "x",
    })
    direct = tool.canonical_effect_parameters({
        "action": "linear_move",
        "target_pose": {
            "x": 1.0, "y": 2.0, "z": 3.0,
            "rx": 4.0, "ry": 5.0, "rz": 6.0,
        },
    })

    assert named == direct
