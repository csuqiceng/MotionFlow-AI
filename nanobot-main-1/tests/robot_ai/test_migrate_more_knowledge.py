from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.knowledge.loader import KnowledgeStore  # noqa: E402
from robot_ai.knowledge.models import KnowledgeEntry  # noqa: E402

# Import the migration script as a module (its name starts with a digit-free
# path under tools/). We exec it to reuse the helpers without packaging tools/.
import importlib.util  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "migrate_more_knowledge", ROOT / "tools" / "migrate_more_knowledge.py"
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
migrate_more = _MOD  # type: ignore[assignment]


def _seed_legacy(src: Path) -> None:
    (src / "controller_error_map.json").write_text(
        json.dumps(
            {
                "Z_LIMIT": {"message": "Z 超限", "suggestion": "回安全高度"},
                "NEW_CODE": {"message": "新错误", "suggestion": "重启"},
            }
        ),
        encoding="utf-8",
    )
    (src / "avoidance_rules.json").write_text(
        json.dumps(
            {
                "mode": "off",
                "low_z_threshold": 150.0,
                "safe_points": {
                    "SAFE_POINT": {"name": "SAFE_POINT", "z": 200.0},
                },
                "rules": [],
            }
        ),
        encoding="utf-8",
    )
    (src / "query_table.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "query_key": "home",
                        "func_num": 108,
                        "description": "回到 Home 位",
                    },
                    {
                        "query_key": "位置A",
                        "func_num": 108,
                        "description": "移动到位置A",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_appends_new_sources(tmp_path, monkeypatch) -> None:
    src = tmp_path / "legacy"
    src.mkdir()
    _seed_legacy(src)
    monkeypatch.setattr(migrate_more, "LEGACY", src)

    out = tmp_path / "knowledge.json"
    monkeypatch.setattr(migrate_more, "OUT", out)
    KnowledgeStore(out).replace(
        [
            # Pre-existing: one error_code (Z_LIMIT) that should be deduped,
            # plus one unrelated general entry.
            KnowledgeEntry(
                category="error_code",
                title="Z_LIMIT",
                content="old",
                source="controller_error_map.json",
            ),
            KnowledgeEntry(
                category="general",
                title="stub",
                content="x",
                source="test",
            ),
        ]
    )

    before, added, after = migrate_more.migrate()
    assert (before, added, after) == (2, 5, 7)

    entries = KnowledgeStore(out).load()
    cats = [e.category for e in entries]
    assert cats.count("error_code") == 2  # Z_LIMIT deduped, NEW_CODE added
    assert cats.count("safety") == 2  # avoidance_rules:config + safe_point:SAFE_POINT
    assert cats.count("dashboard") == 2  # home + 位置A
    titles = {e.title for e in entries}
    assert "NEW_CODE" in titles
    assert "avoidance_rules:config" in titles
    assert "safe_point:SAFE_POINT" in titles
    assert "home" in titles
    assert "位置A" in titles


def test_idempotent_on_rerun(tmp_path, monkeypatch) -> None:
    src = tmp_path / "legacy"
    src.mkdir()
    _seed_legacy(src)
    monkeypatch.setattr(migrate_more, "LEGACY", src)
    out = tmp_path / "knowledge.json"
    monkeypatch.setattr(migrate_more, "OUT", out)
    KnowledgeStore(out).replace([])

    migrate_more.migrate()
    _, added_second, after_second = migrate_more.migrate()
    assert added_second == 0  # nothing new on re-run
    # Count unchanged
    entries = KnowledgeStore(out).load()
    assert len(entries) == after_second


def test_dedup_preserves_existing_error_codes(tmp_path, monkeypatch) -> None:
    """The 3 core error codes are normally already migrated; they must not duplicate."""
    src = tmp_path / "legacy"
    src.mkdir()
    _seed_legacy(src)
    monkeypatch.setattr(migrate_more, "LEGACY", src)
    out = tmp_path / "knowledge.json"
    monkeypatch.setattr(migrate_more, "OUT", out)
    KnowledgeStore(out).replace(
        [
            KnowledgeEntry(
                category="error_code",
                title="Z_LIMIT",
                content="existing",
                source="controller_error_map.json",
            )
        ]
    )

    migrate_more.migrate()
    entries = KnowledgeStore(out).load()
    z_limits = [e for e in entries if e.title == "Z_LIMIT" and e.category == "error_code"]
    assert len(z_limits) == 1
    assert z_limits[0].content == "existing"  # original preserved
