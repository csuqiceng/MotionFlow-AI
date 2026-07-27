"""Idempotent migration of the product's named motion locations.

The legacy project shipped ``home`` and positions A/B/C in its query table.
They are actual project presets, not invented UI examples, and are retained
here so a migrated runtime can resolve the same names as a fresh installation.
"""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path

from robot_platform.positions.registry import AXIS_NAMES, NamedPosition, PositionRegistry


_DEFAULT_NAMES = frozenset({"home", "休息姿态", "位置A", "位置B", "位置C"})


def ensure_default_positions(path: str | Path) -> list[NamedPosition]:
    """Add missing packaged locations without changing an operator's values."""
    registry = PositionRegistry(path)
    added = [
        position for position in _seed_positions()
        if registry.get(position.name) is None
    ]
    # Persist the migration once. Besides avoiding unnecessary file churn on
    # every status poll, this keeps the legacy preset batch atomic.
    if added:
        registry.replace([*registry.list_all(), *added])
    return added


def _seed_positions() -> list[NamedPosition]:
    with importlib.resources.as_file(
        importlib.resources.files("robot_platform.library") / "seed_query_table.json"
    ) as resource:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    positions: list[NamedPosition] = []
    for record in payload.get("records", []):
        if not isinstance(record, dict) or int(record.get("func_num", 0)) != 108:
            continue
        name = str(record.get("query_key", "")).strip()
        params = record.get("params")
        if name not in _DEFAULT_NAMES or not isinstance(params, dict):
            continue
        try:
            pose = [float(params[f"target_{axis}"]) for axis in AXIS_NAMES]
        except (KeyError, TypeError, ValueError):
            continue
        positions.append(
            NamedPosition(
                name=name,
                pose=pose,
                spd=float(params.get("spd_pct", 50.0)),
                move_type=int(params.get("move_type", 0)),
            )
        )
    return positions
