"""Append additional legacy knowledge sources into ``knowledge.json``.

Sources migrated by this script (the original ``migrate_robot_knowledge.py``
only covered ``assistant_knowledge_base.json``, ``operator_agent_knowledge.json``,
``operator_agent_skills.json`` and ``controller_error_map.json``):

* ``controller_error_map.json``  -> category ``error_code``  (deduped — the
  three core entries Z_LIMIT / SPEED_LIMIT / ALARM_ACTIVE are usually already
  present from the first migration; only missing ones are appended).
* ``avoidance_rules.json``       -> category ``safety``
* ``query_table.json``           -> category ``dashboard``

Each legacy record becomes one knowledge entry. Re-running is idempotent:
entries are deduped on ``(category, title, source)`` so existing records are
kept and only genuinely new ones are appended.

Usage::

    .venv-robot-desktop/Scripts/python.exe tools/migrate_more_knowledge.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.knowledge.loader import KnowledgeStore
from robot_ai.knowledge.models import KnowledgeEntry

LEGACY = Path(
    os.environ.get(
        "ROBOT_LEGACY_DATA_DIR",
        r"data/legacy",
    )
)
OUT = Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai" / "knowledge.json"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"WARN: failed to parse {path}: {exc}", file=sys.stderr)
        return None


def _stringify(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _build_entries() -> list[KnowledgeEntry]:
    entries: list[KnowledgeEntry] = []

    # --- controller_error_map.json -> error_code ---------------------------
    errs = _load_json(LEGACY / "controller_error_map.json")
    if isinstance(errs, dict):
        for key, val in errs.items():
            entries.append(
                KnowledgeEntry(
                    category="error_code",
                    title=str(key),
                    content=_stringify(val),
                    source="controller_error_map.json",
                )
            )

    # --- avoidance_rules.json -> safety ------------------------------------
    av = _load_json(LEGACY / "avoidance_rules.json")
    if isinstance(av, dict):
        # Top-level scalars (mode, thresholds) go in as one summary entry so
        # they don't bloat the knowledge base; the structured payload stays
        # queryable via category=safety.
        entries.append(
            KnowledgeEntry(
                category="safety",
                title="avoidance_rules:config",
                content=_stringify(av),
                source="avoidance_rules.json",
            )
        )
        # Also surface each declared safe point as its own entry so they can be
        # looked up by name (SAFE_POINT, etc.).
        safe_points = av.get("safe_points") or {}
        if isinstance(safe_points, dict):
            for name, point in safe_points.items():
                if not isinstance(point, dict):
                    continue
                entries.append(
                    KnowledgeEntry(
                        category="safety",
                        title=f"safe_point:{name}",
                        content=_stringify(point),
                        source="avoidance_rules.json",
                    )
                )

    # --- query_table.json -> dashboard -------------------------------------
    qt = _load_json(LEGACY / "query_table.json")
    if isinstance(qt, dict):
        for rec in qt.get("records", []) or []:
            if not isinstance(rec, dict):
                continue
            key = str(rec.get("query_key", "")).strip()
            if not key:
                continue
            entries.append(
                KnowledgeEntry(
                    category="dashboard",
                    title=key,
                    content=_stringify(rec),
                    source="query_table.json",
                )
            )

    return entries


def _dedupe_key(e: KnowledgeEntry) -> tuple[str, str, str]:
    return (e.category, e.title, e.source)


def migrate() -> tuple[int, int, int]:
    """Append new entries to ``knowledge.json``; return (before, added, after)."""
    store = KnowledgeStore(OUT)
    existing = store.load()
    existing_keys = {_dedupe_key(e) for e in existing}

    new_entries = _build_entries()
    added = [e for e in new_entries if _dedupe_key(e) not in existing_keys]

    merged = existing + added
    store.replace(merged)
    return len(existing), len(added), len(merged)


if __name__ == "__main__":
    before, added, after = migrate()
    print(f"knowledge.json: {before} -> {after} entries (appended {added})")
    print(f"output: {OUT}")
