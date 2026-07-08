from __future__ import annotations

import json

from robot_ai.flow.migration import migrate_flows
from robot_ai.flow.registry import FlowRegistry


def _legacy_registry(src_dir, *, flows) -> None:
    (src_dir / "flow_registry.json").write_text(
        json.dumps({"version": "1.1", "updated_at": "2026-07-05", "flows": flows}),
        encoding="utf-8",
    )


def test_migrate_structured_and_freetext_steps(tmp_path) -> None:
    src = tmp_path / "old"
    src.mkdir()
    _legacy_registry(
        src,
        flows=[
            {
                "name": "结构化流程",
                "description": "linear move + delay",
                "steps": [
                    {
                        "step_id": 1,
                        "action": "linear_move",
                        "func_id": 108,
                        "params": {"target_pose": {"x": 1, "y": 2, "z": 3, "rx": 0, "ry": 0, "rz": 0}},
                        "spd_pct": 60,
                        "description": "到抓取位",
                    },
                    {
                        "step_id": 2,
                        "action": "delay",
                        "func_id": 110,
                        "params": {"seconds": 1.5},
                        "description": "等1.5秒",
                    },
                ],
                "step_delay_ms": 500,
            },
            {
                "name": "自由文本流程",
                "description": "needs NLP — not portable",
                "steps": [
                    {
                        "step_id": 1,
                        "action": "移动到位置A",
                        "func_id": 0,
                        "params": {"query_key": "移动到位置A"},
                        "description": "移动到位置A",
                    },
                    {
                        "step_id": 2,
                        "action": "等待1秒",
                        "func_id": 999,  # out of whitelist
                        "params": {},
                        "description": "等待1秒",
                    },
                ],
                "step_delay_ms": 1000,
            },
        ],
    )
    out = tmp_path / "flows.json"

    count = migrate_flows(src, out)
    assert count == 2

    registry = FlowRegistry(out)
    structured = registry.get("结构化流程")
    assert structured is not None
    assert structured.steps[0].func_id == 108  # kept as-is
    assert structured.steps[1].func_id == 110
    assert structured.step_delay_ms == 500

    freetext = registry.get("自由文本流程")
    assert freetext is not None
    # func_id=0 step kept as non-executable, description preserved for re-teaching
    assert freetext.steps[0].func_id == 0
    assert freetext.steps[0].description == "移动到位置A"
    # out-of-whitelist func_id (999) is normalized to 0 (non-executable)
    assert freetext.steps[1].func_id == 0
    assert freetext.steps[1].description == "等待1秒"


def test_migrate_missing_legacy_file_returns_zero(tmp_path) -> None:
    src = tmp_path / "empty"
    src.mkdir()
    out = tmp_path / "flows.json"
    count = migrate_flows(src, out)
    assert count == 0
