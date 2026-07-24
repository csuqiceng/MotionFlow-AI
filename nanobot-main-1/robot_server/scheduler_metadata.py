"""Transport-neutral metadata helpers for cron deliveries."""

from __future__ import annotations

import uuid
from typing import Any

from ai_runtime.turn_metadata import MESSAGE_SOURCE_METADATA_KEY, RUNTIME_TURN_METADATA_KEY


def cron_proactive_delivery_metadata(
    metadata: dict[str, Any] | None,
    *,
    turn_seed: str,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Return metadata for a fresh proactive cron delivery turn."""
    out = dict(metadata or {})
    out.pop("webui_turn_id", None)
    out.pop(RUNTIME_TURN_METADATA_KEY, None)
    out[RUNTIME_TURN_METADATA_KEY] = f"{turn_seed}:{uuid.uuid4().hex}"
    source: dict[str, str] = {"kind": "cron"}
    if source_label:
        source["label"] = source_label
    out[MESSAGE_SOURCE_METADATA_KEY] = source
    return out
