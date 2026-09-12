"""Display-only timestamp fields for durable diagnostic records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def with_readable_timestamp(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a numeric timestamp into a human-readable UTC field."""
    rendered = dict(record)
    timestamp = rendered.get("timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        rendered.setdefault(
            "timestamp_iso",
            datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
        )
    return rendered
