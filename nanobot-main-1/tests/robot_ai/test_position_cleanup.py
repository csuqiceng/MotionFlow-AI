from __future__ import annotations

import json

import pytest

from robot_ai.positions.cleanup import (
    backup_and_apply,
    build_cleanup_plan,
    classify_temporary,
)


def test_cleanup_plan_removes_only_unreferenced_temporary_positions() -> None:
    positions = {
        "version": "1.0",
        "positions": [
            {"name": "home", "pose": [0, 0, 0, 0, 0, 0]},
            {"name": "flowdraft:unused", "pose": [1, 0, 0, 0, 0, 0]},
            {"name": "agent:unused", "pose": [2, 0, 0, 0, 0, 0]},
            {"name": "ai_first:unused", "pose": [3, 0, 0, 0, 0, 0]},
            {"name": "flowdraft:in-use", "pose": [4, 0, 0, 0, 0, 0]},
        ],
    }

    plan = build_cleanup_plan(positions, {"flowdraft:in-use"})

    assert plan == {
        "remove": ["agent:unused", "ai_first:unused", "flowdraft:unused"],
        "preserve": ["flowdraft:in-use", "home"],
    }
    assert classify_temporary("flowdraft:any")
    assert classify_temporary("agent:any")
    assert classify_temporary("ai_first:any")
    assert not classify_temporary("home")


def test_backup_and_apply_backs_up_before_removing_planned_positions(tmp_path) -> None:
    registry_path = tmp_path / "position_registry.json"
    original = {
        "version": "1.0",
        "positions": [
            {"name": "home", "pose": [0, 0, 0, 0, 0, 0]},
            {"name": "agent:unused", "pose": [1, 0, 0, 0, 0, 0]},
        ],
    }
    registry_path.write_text(json.dumps(original), encoding="utf-8")

    details = backup_and_apply(registry_path, {"remove": ["agent:unused"], "preserve": ["home"]})

    backup_path = details["backup_path"]
    assert backup_path is not None
    assert backup_path.exists()
    assert json.loads(backup_path.read_text(encoding="utf-8")) == original
    assert details["removed"] == ["agent:unused"]
    assert [item["name"] for item in json.loads(registry_path.read_text(encoding="utf-8"))["positions"]] == [
        "home"
    ]


def test_backup_and_apply_does_not_overwrite_malformed_registry(tmp_path) -> None:
    registry_path = tmp_path / "position_registry.json"
    malformed = "{not valid JSON"
    registry_path.write_text(malformed, encoding="utf-8")

    with pytest.raises(ValueError, match="valid JSON mapping"):
        backup_and_apply(registry_path, {"remove": ["agent:unused"], "preserve": []})

    assert registry_path.read_text(encoding="utf-8") == malformed
    assert not list(tmp_path.glob("*.bak.json"))
