"""Versioned command/flow export validation shared by engineer transfer routes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable


def build_transfer_payload(
    *, commands: Iterable[dict[str, Any]], flows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build a portable payload without audit queues or registry timestamps."""
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "commands": [deepcopy(item) for item in commands],
        "flows": [deepcopy(item) for item in flows],
    }


def validate_transfer_payload(payload: Any, *, component_ids: set[str]) -> list[str]:
    """Return all structural errors before an import is allowed to mutate data."""
    if not isinstance(payload, dict):
        return ["payload must be an object"]
    if payload.get("schema_version") != 1:
        return ["schema_version must be 1"]
    errors: list[str] = []
    commands = payload.get("commands")
    flows = payload.get("flows")
    if not isinstance(commands, list):
        errors.append("commands must be a list")
        commands = []
    if not isinstance(flows, list):
        errors.append("flows must be a list")
        flows = []
    _validate_entities(commands, "commands", "command_id", errors, component_ids)
    _validate_entities(flows, "flows", "flow_id", errors, component_ids, flow=True)
    return errors


def _validate_entities(
    items: list[Any],
    collection: str,
    id_key: str,
    errors: list[str],
    component_ids: set[str],
    *,
    flow: bool = False,
) -> None:
    first_seen: dict[str, int] = {}
    for index, item in enumerate(items):
        prefix = f"{collection}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        entity_id = item.get(id_key)
        if not isinstance(entity_id, str) or not entity_id.strip():
            errors.append(f"{prefix}.{id_key} is required")
            continue
        if entity_id in first_seen:
            errors.append(f"{prefix}.{id_key} duplicates {collection}[{first_seen[entity_id]}].{id_key}: {entity_id}")
        else:
            first_seen[entity_id] = index
        versions = item.get("versions", {})
        drafts_and_versions = [item.get("draft")] + (list(versions.values()) if isinstance(versions, dict) else [])
        for candidate in drafts_and_versions:
            if not isinstance(candidate, dict):
                continue
            if flow:
                steps = candidate.get("steps", [])
                if not isinstance(steps, list):
                    errors.append(f"{prefix}.steps must be a list")
                continue
            component_id = candidate.get("component_id")
            if isinstance(component_id, str) and component_id not in component_ids:
                location = "draft" if candidate is item.get("draft") else "versions"
                errors.append(f"{prefix}.{location}.component_id is unknown: {component_id}")
