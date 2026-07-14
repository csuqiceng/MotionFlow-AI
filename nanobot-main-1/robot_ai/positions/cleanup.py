from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TEMPORARY_PREFIXES = ("flowdraft:", "agent:", "ai_first:")


def classify_temporary(name: str) -> bool:
    """Return whether *name* uses one of the supported temporary prefixes."""
    return name.startswith(_TEMPORARY_PREFIXES)


def build_cleanup_plan(
    positions: Mapping[str, Any] | Iterable[Mapping[str, Any]], referenced_names: Iterable[str]
) -> dict[str, list[str]]:
    """Plan removal of unreferenced temporary positions without changing the registry."""
    entries = positions.get("positions") if isinstance(positions, Mapping) else positions
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
        raise ValueError("position registry positions must be an iterable of mappings")
    entries = list(entries)
    if not all(isinstance(entry, Mapping) for entry in entries):
        raise ValueError("position registry positions must be an iterable of mappings")

    references = {str(name).strip().casefold() for name in referenced_names}
    remove: list[str] = []
    preserve: list[str] = []

    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        if classify_temporary(name) and name.strip().casefold() not in references:
            remove.append(name)
        else:
            preserve.append(name)

    return {"remove": sorted(remove), "preserve": sorted(preserve)}


def backup_and_apply(path: str | Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    """Back up a valid position registry, then remove the names in *plan*.

    The registry is parsed and validated before any backup or write, so malformed
    source data is never replaced.
    """
    registry_path = Path(path)
    source = registry_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError("position registry must be a valid JSON mapping") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("version"), str):
        raise ValueError("position registry must be a valid JSON mapping with a string version")
    if not isinstance(payload.get("positions"), list):
        raise ValueError("position registry must be a valid JSON mapping with a positions list")
    if any(
        not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
        for entry in payload["positions"]
    ):
        raise ValueError("position registry positions must be mappings with string names")

    requested = plan.get("remove") if isinstance(plan, Mapping) else None
    if not isinstance(requested, list) or not all(isinstance(name, str) for name in requested):
        raise ValueError("cleanup plan must contain a remove list of position names")
    remove_keys = {name.strip().casefold() for name in requested}
    removed = sorted(
        entry["name"]
        for entry in payload["positions"]
        if classify_temporary(entry["name"]) and entry["name"].strip().casefold() in remove_keys
    )
    if not removed:
        return {"backup_path": None, "removed": []}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = registry_path.with_name(f"{registry_path.stem}.{timestamp}.bak.json")
    backup_path.write_text(source, encoding="utf-8")
    payload["positions"] = [
        entry
        for entry in payload["positions"]
        if not (
            classify_temporary(entry["name"])
            and entry["name"].strip().casefold() in remove_keys
        )
    ]
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"backup_path": backup_path, "removed": removed}
