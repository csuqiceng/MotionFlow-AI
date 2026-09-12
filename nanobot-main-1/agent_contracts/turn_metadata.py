"""Transport-neutral metadata helpers for agent-originated turns."""

from __future__ import annotations

import uuid
from typing import Any


RUNTIME_TURN_METADATA_KEY = "_runtime_turn_id"
MESSAGE_SOURCE_METADATA_KEY = "_runtime_message_source"


def proactive_delivery_metadata(
    metadata: dict[str, Any] | None,
    *,
    turn_seed: str,
    source_kind: str,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Create fresh metadata for a session-bound proactive delivery."""
    out = dict(metadata or {})
    out.pop("webui_turn_id", None)
    out.pop(RUNTIME_TURN_METADATA_KEY, None)
    out[RUNTIME_TURN_METADATA_KEY] = f"{turn_seed}:{uuid.uuid4().hex}"
    source: dict[str, str] = {"kind": source_kind}
    if source_label:
        source["label"] = source_label
    out[MESSAGE_SOURCE_METADATA_KEY] = source
    return out
