from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.robot_flow import RobotFlowTool  # noqa: E402
from robot_ai.flow.aliases import FlowAlias, migrate_aliases  # noqa: E402
from robot_ai.models import ToolResult  # noqa: E402
from robot_platform.flow import FlowEntry, FlowRegistry, FlowStep


def _write_aliases(path, aliases) -> None:
    path.write_text(
        json.dumps({"version": "1.0", "aliases": aliases}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_alias_resolve_by_name(tmp_path) -> None:
    p = tmp_path / "flow_aliases.json"
    _write_aliases(
        p,
        [
            {"name": "上料", "canonical_flow": "上料流程", "keywords": ["上料", "送料"]},
            {"name": "点头", "canonical_flow": "点头", "keywords": ["点头"]},
        ],
    )
    alias = FlowAlias(p)
    assert alias.resolve("上料") == "上料流程"
    assert alias.resolve("送料") == "上料流程"  # keyword match
    assert alias.resolve("请上料吧") == "上料流程"  # substring


def test_alias_resolve_case_insensitive_and_unknown(tmp_path) -> None:
    p = tmp_path / "flow_aliases.json"
    _write_aliases(p, [{"name": "Pick", "canonical_flow": "PickFlow", "keywords": []}])
    alias = FlowAlias(p)
    assert alias.resolve("pick") == "PickFlow"
    assert alias.resolve("PICK") == "PickFlow"
    assert alias.resolve("totally-unknown") is None


def test_alias_resolve_missing_file(tmp_path) -> None:
    alias = FlowAlias(tmp_path / "nope.json")
    assert alias.resolve("anything") is None


def test_migrate_aliases_from_legacy(tmp_path) -> None:
    src = tmp_path / "old"
    src.mkdir()
    # Legacy shape: {aliases: {phrase: [{command, func_id, axis_no, direction}]}}
    (src / "flow_phrase_aliases.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "aliases": {
                    "点头": [
                        {"command": "Ry正转", "func_id": 107, "axis_no": 10, "direction": 1}
                    ],
                    "小臂上下点头": [
                        {"command": "Ry正转", "func_id": 107, "axis_no": 10, "direction": 1}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    # Legacy phrase "点头" maps to flow named "点头" (canonical_flow = phrase when a
    # matching flow exists; here we don't pass flows so canonical_flow falls back
    # to the phrase itself — recorded for re-teaching).
    out = tmp_path / "flow_aliases.json"
    count = migrate_aliases(src, out)
    assert count == 2
    alias = FlowAlias(out)
    assert alias.resolve("点头") == "点头"


def _run(tool: RobotFlowTool, **kwargs) -> dict:
    return json.loads(asyncio.run(tool.execute(**kwargs)))


def _delay_step() -> dict:
    return {"step_id": 1, "action": "delay", "func_id": 110, "params": {"seconds": 1}}


def test_robot_flow_run_with_flow_alias(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    flows_path = tmp_path / "flows.json"
    aliases_path = tmp_path / "flow_aliases.json"
    tool = RobotFlowTool(str(flows_path), alias_path=str(aliases_path))
    FlowRegistry(flows_path).add(
        FlowEntry(name="上料流程", steps=[FlowStep.from_dict(_delay_step())])
    )
    _write_aliases(
        aliases_path,
        [{"name": "上料", "canonical_flow": "上料流程", "keywords": ["送料"]}],
    )

    captured: dict = {}

    def fake_runner(**kwargs):
        captured["called"] = True
        return ToolResult.success(state="zmotion_operator_dry_run", data={}).to_dict()

    import robot_platform.flow.executor as executor_module

    monkeypatch.setattr(executor_module, "run_operator_command", fake_runner)

    result = _run(tool, action="run", flow_alias="上料")
    assert result["ok"] is True
    assert result["state"] == "flow_completed"
    assert captured.get("called") is True


def test_robot_flow_run_alias_not_found(tmp_path) -> None:
    flows_path = tmp_path / "flows.json"
    aliases_path = tmp_path / "flow_aliases.json"
    tool = RobotFlowTool(str(flows_path), alias_path=str(aliases_path))
    _write_aliases(aliases_path, [{"name": "x", "canonical_flow": "X", "keywords": []}])
    result = _run(tool, action="run", flow_alias="不存在的别名")
    assert result["ok"] is False
    assert result["state"] == "flow_alias_not_found"
