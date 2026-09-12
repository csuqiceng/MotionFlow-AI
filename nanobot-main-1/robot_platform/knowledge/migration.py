from __future__ import annotations

import json
from pathlib import Path

from robot_platform.knowledge.loader import KnowledgeStore
from robot_platform.knowledge.models import KnowledgeEntry


def migrate_knowledge(
    src_dir: str | Path, out_path: str | Path
) -> list[KnowledgeEntry]:
    """Read legacy knowledge JSONs from src_dir, write unified knowledge.json, return entries."""
    src = Path(src_dir)
    entries: list[KnowledgeEntry] = []

    def _load(name: str) -> dict | None:
        p = src / name
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _stringify(v) -> str:
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

    kb = _load("assistant_knowledge_base.json")
    if kb and isinstance(kb.get("entries"), list):
        for e in kb["entries"]:
            # Legacy KB entries use ``id`` as the primary key (not title/name);
            # fall back through title -> name -> id -> "entry" so real data keeps
            # meaningful titles while the spec's title-based test still passes.
            title = e.get("title", e.get("name", e.get("id", "entry")))
            entries.append(
                KnowledgeEntry(
                    category="general",
                    title=str(title),
                    content=_stringify(e.get("content", e)),
                    source="assistant_knowledge_base.json",
                )
            )

    oak = _load("operator_agent_knowledge.json")
    if oak:
        for cat in ("motion", "safety", "answering"):
            block = oak.get(cat)
            if isinstance(block, dict):
                entries.append(
                    KnowledgeEntry(
                        category="safety" if cat == "safety" else cat,
                        title=f"operator:{cat}",
                        content=json.dumps(block, ensure_ascii=False),
                        source="operator_agent_knowledge.json",
                    )
                )

    skills = _load("operator_agent_skills.json")
    if skills and isinstance(skills.get("skills"), list):
        for s in skills["skills"]:
            # Legacy skills use ``id`` (not name) and ``content`` (not desc);
            # fall back through name -> id -> "skill" and content -> desc -> s.
            title = s.get("name", s.get("id", "skill"))
            content = s.get("content", s.get("desc", s))
            entries.append(
                KnowledgeEntry(
                    category="skill",
                    title=str(title),
                    content=_stringify(content),
                    source="operator_agent_skills.json",
                )
            )

    errs = _load("controller_error_map.json")
    if errs and isinstance(errs, dict):
        for key, val in errs.items():
            entries.append(
                KnowledgeEntry(
                    category="error_code",
                    title=key,
                    content=(
                        json.dumps(val, ensure_ascii=False)
                        if isinstance(val, dict)
                        else str(val)
                    ),
                    source="controller_error_map.json",
                )
            )

    KnowledgeStore(out_path).replace(entries)
    return entries
