"""Vendor-neutral, deployment-owned digital-output policy primitives."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

# The physical controller/profile allowlist is authoritative. This upper bound
# only prevents values that cannot be represented as a sensible controller IO
# address; ZMotion local and mapped expansion IOs both remain supported.
MAX_CONTROLLER_IO_CHANNEL = 65_535


def normalize_io_output_channels(value: Any) -> tuple[int, ...]:
    """Validate and canonicalize a trusted output-channel collection."""
    if not isinstance(value, Collection) or isinstance(value, (str, bytes, dict)):
        raise ValueError("allowed IO output channels must be a collection")
    channels = list(value)
    if any(
        not isinstance(channel, int)
        or isinstance(channel, bool)
        or not 0 <= channel <= MAX_CONTROLLER_IO_CHANNEL
        for channel in channels
    ):
        raise ValueError("allowed IO output channels contain an invalid channel")
    if len(set(channels)) != len(channels):
        raise ValueError("allowed IO output channels contain duplicates")
    return tuple(sorted(channels))


def valid_io_channel(value: Any) -> bool:
    return bool(
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_CONTROLLER_IO_CHANNEL
    )
