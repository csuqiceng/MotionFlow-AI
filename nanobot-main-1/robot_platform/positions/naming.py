"""Canonical name and alias helpers for saved robot positions."""

from __future__ import annotations

import re

_LOCATION_PREFIXES = ("位置", "工位", "点")


def normalize_position_reference(value: str) -> str:
    """Normalize a user reference without changing its stored display name."""
    normalized = re.sub(r"\s+", "", str(value or "")).casefold()
    for prefix in _LOCATION_PREFIXES:
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            return normalized[len(prefix):]
    return normalized


def generated_position_aliases(name: str) -> list[str]:
    """Return safe aliases for the common ``位置A``/``位置1`` naming pattern."""
    canonical = str(name or "").strip()
    normalized = normalize_position_reference(canonical)
    if not canonical or not normalized or normalized == canonical.casefold():
        return []
    return [normalized]
