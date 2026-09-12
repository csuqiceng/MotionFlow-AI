"""Phrase → canonical-flow aliases.

Reads ``~/.nanobot/robot_ai/flow_aliases.json`` with shape::

    {"version": "1.0", "aliases": [{"name": ..., "canonical_flow": ..., "keywords": [...]}]}

``resolve(phrase)`` matches the phrase against each alias's ``name`` and
``keywords`` (case-insensitive substring) and returns the first matching
``canonical_flow``. This lets the LLM say "run 上料" instead of recalling the
exact registered flow name.

Migration: the legacy ``flow_phrase_aliases.json`` has a different shape —
``{aliases: {phrase: [{command, func_id, axis_no, direction}]}}`` — it maps
phrases to axis-level command sequences, NOT to flow names. There is no
canonical-flow information in the legacy file. The migration therefore records
each legacy phrase with ``canonical_flow`` set to the phrase itself (the common
case: a phrase like ``点头`` is also the registered flow name). Phrases that
don't correspond to a registered flow are still recorded for re-teaching; their
``canonical_flow`` is the phrase and ``resolve`` will return it (callers can
detect the dangling reference via FlowRegistry.get).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FlowAlias:
    """Phrase → canonical-flow resolver backed by a JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._aliases: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload.get("aliases", []) if isinstance(payload, dict) else []
        self._aliases = [dict(item) for item in items if isinstance(item, dict)]

    def resolve(self, phrase: str) -> str | None:
        """Return the canonical flow name for ``phrase``, or ``None``.

        Matching is case-insensitive substring against each alias's ``name``
        and each of its ``keywords``. The first alias that matches wins.
        """
        needle = str(phrase or "").strip().lower()
        if not needle:
            return None
        # Pass 1: exact (case-insensitive) match against name or keyword. This
        # avoids an overlapping longer alias swallowing a short exact phrase
        # (e.g. legacy "点头" vs "小臂上下点头").
        for alias in self._aliases:
            canonical = str(alias.get("canonical_flow", "")).strip()
            if not canonical:
                continue
            candidates = [str(alias.get("name", ""))]
            candidates.extend(str(k) for k in alias.get("keywords", []) if isinstance(k, str))
            for candidate in candidates:
                if needle == candidate.lower():
                    return canonical
        # Pass 2: bidirectional substring. A spoken phrase like "请上料吧" should
        # match the keyword "上料" in either direction.
        for alias in self._aliases:
            canonical = str(alias.get("canonical_flow", "")).strip()
            if not canonical:
                continue
            candidates = [str(alias.get("name", ""))]
            candidates.extend(str(k) for k in alias.get("keywords", []) if isinstance(k, str))
            for candidate in candidates:
                hay = candidate.lower()
                if needle in hay or hay in needle:
                    return canonical
        return None


def migrate_aliases(src_dir: str | Path, out_path: str | Path) -> int:
    """Read legacy ``flow_phrase_aliases.json`` → write ``flow_aliases.json``.

    Each legacy phrase becomes one alias with ``name`` = phrase,
    ``canonical_flow`` = phrase, and an empty ``keywords`` list. Returns the
    alias count.
    """
    src = Path(src_dir)
    legacy = src / "flow_phrase_aliases.json"
    if not legacy.exists():
        _write(out_path, [])
        return 0

    payload = json.loads(legacy.read_text(encoding="utf-8"))
    raw = payload.get("aliases", {}) if isinstance(payload, dict) else {}
    aliases: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for phrase in raw.keys():
            aliases.append(
                {
                    "name": str(phrase),
                    "canonical_flow": str(phrase),
                    "keywords": [],
                }
            )
    _write(out_path, aliases)
    return len(aliases)


def _write(out_path: str | Path, aliases: list[dict[str, Any]]) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": "1.0", "aliases": aliases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
