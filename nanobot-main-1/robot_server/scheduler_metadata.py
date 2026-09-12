"""Deprecated compatibility helpers for cron delivery metadata."""

from __future__ import annotations

from typing import Any

from agent_contracts.turn_metadata import proactive_delivery_metadata


def cron_proactive_delivery_metadata(
    metadata: dict[str, Any] | None,
    *,
    turn_seed: str,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Return metadata for a fresh proactive cron delivery turn."""
    return proactive_delivery_metadata(
        metadata,
        turn_seed=turn_seed,
        source_kind="cron",
        source_label=source_label,
    )
