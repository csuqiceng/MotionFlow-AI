"""Atomic JSON write helper for the robot library.

Independent of ``robot_platform.flow.registry`` (which has its own inline copy) so
A1 does not disturb the working flow persistence. temp file + fsync +
``os.replace`` — the same durability pattern, shared here for the library.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def atomic_write_json(path: str | Path, payload: Any) -> None:
    """Write ``payload`` as JSON to ``path`` atomically.

    Stages the text in a temp file in the same directory, fsyncs it, then
    ``os.replace``-moves it onto the target so a crash mid-write never leaves a
    truncated file. Parent directories are created on demand.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as staging:
        staging.write(text)
        staging.flush()
        os.fsync(staging.fileno())
        tmp_name = staging.name
    # Windows antivirus/indexing can briefly hold either the destination or
    # the just-closed temporary file.  Retrying preserves atomic replacement
    # while avoiding a spurious 500 during normal library edits.  Do not fall
    # back to a non-atomic write: callers depend on crash-safe persistence.
    try:
        for attempt in range(5):
            try:
                os.replace(tmp_name, target)
                tmp_name = ""
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)
