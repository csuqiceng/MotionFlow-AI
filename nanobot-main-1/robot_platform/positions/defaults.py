"""Idempotently import the packaged position configuration."""

from __future__ import annotations

import json
import importlib.resources
from pathlib import Path

from robot_platform.positions.registry import AXIS_NAMES, NamedPosition, PositionRegistry


def ensure_default_positions(path: str | Path) -> list[NamedPosition]:
    """Import missing rows from ``seed_positions.json`` without overwriting."""
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
        importlib.resources.files("robot_platform.positions") / "seed_positions.json"
    ) as resource:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    positions: list[NamedPosition] = []
    for record in payload.get("positions", []):
        if not isinstance(record, dict):
            continue
        name = str(record.get("name", "")).strip()
        if not name:
            continue
        try:
            pose = [float(record["pose"][index]) for index, _axis in enumerate(AXIS_NAMES)]
        except (KeyError, TypeError, ValueError):
            continue
        positions.append(
            NamedPosition(
                name=name,
                pose=pose,
                spd=float(record.get("spd", 50.0)),
                move_type=int(record.get("move_type", 0)),
            )
        )
    return positions
