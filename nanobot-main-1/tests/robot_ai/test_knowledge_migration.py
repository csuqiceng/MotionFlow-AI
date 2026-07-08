from __future__ import annotations

import json

from robot_ai.knowledge.loader import KnowledgeStore
from robot_ai.knowledge.migration import migrate_knowledge


def test_migration_maps_old_sources(tmp_path) -> None:
    src = tmp_path / "old"
    src.mkdir()
    (src / "assistant_knowledge_base.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "entries": [{"title": "安全边界", "content": "Z<=2500"}],
            }
        ),
        encoding="utf-8",
    )
    (src / "controller_error_map.json").write_text(
        json.dumps(
            {"Z_LIMIT": {"message": "Z 超限", "suggestion": "回安全高度"}}
        ),
        encoding="utf-8",
    )
    (src / "operator_agent_knowledge.json").write_text(
        json.dumps(
            {
                "version": 1,
                "safety": {"lower_controller_is_authority": "下位机是最终权威"},
            }
        ),
        encoding="utf-8",
    )
    (src / "operator_agent_skills.json").write_text(
        json.dumps(
            {"version": 1, "skills": [{"name": "查状态", "desc": "调 status"}]}
        ),
        encoding="utf-8",
    )
    out = tmp_path / "knowledge.json"
    entries = migrate_knowledge(src, out)
    cats = {e.category for e in entries}
    assert "general" in cats and "error_code" in cats and "safety" in cats and "skill" in cats
    assert any(e.title == "Z_LIMIT" for e in entries if e.category == "error_code")
    assert KnowledgeStore(out).load()  # round-trip
