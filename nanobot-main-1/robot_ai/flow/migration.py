"""Migrate legacy named flows into the new FlowRegistry JSON.

Reads the legacy ``flow_registry.json`` (ported from the Qt project) and
converts each flow into a :class:`FlowEntry`. Legacy steps come in two
flavours:

- **structured / executable** — ``func_id`` ∈ {104, 108, 110, 120}; kept
  as-is so ``run_flow`` can map them to operator commands.
- **free-text / non-portable** — ``func_id`` == 0 (the action is a Chinese
  description that needs the NLP layer to resolve) or any ``func_id``
  outside the whitelist. These are preserved with ``func_id`` forced to 0
  so the flow is kept for reference / re-teaching, but ``run_flow`` will
  report the step as ``unsupported`` (it won't execute).
"""

from __future__ import annotations

import json
from pathlib import Path

from robot_ai.flow.models import FlowEntry, FlowStep
from robot_ai.flow.registry import FlowRegistry

# func_ids that map 1:1 to a restricted ZMotion operator command. Any other
# func_id (including legacy 0 / 107 / ...) is treated as non-executable.
EXECUTABLE_FUNC_IDS: frozenset[int] = frozenset({104, 108, 110, 120})


def migrate_flows(src_dir: str | Path, out_path: str | Path) -> int:
    """Read legacy ``flow_registry.json`` from ``src_dir``, write all flows to
    ``out_path`` (a FlowRegistry JSON), and return the flow count.

    Steps whose ``func_id`` is outside :data:`EXECUTABLE_FUNC_IDS` are kept but
    have their ``func_id`` normalized to 0 (non-executable) — their
    ``description``/``action`` are preserved so an operator can re-teach them.
    """
    src = Path(src_dir)
    legacy = src / "flow_registry.json"
    if not legacy.exists():
        # Nothing to migrate — write an empty registry so callers get a
        # well-formed file regardless.
        FlowRegistry(out_path).replace([])
        return 0

    payload = json.loads(legacy.read_text(encoding="utf-8"))
    entries: list[FlowEntry] = []
    for raw in payload.get("flows", []):
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        steps = [_convert_step(dict(s)) for s in raw.get("steps", []) if isinstance(s, dict)]
        entries.append(
            FlowEntry(
                name=str(raw["name"]),
                description=str(raw.get("description", "")),
                steps=steps,
                step_delay_ms=int(raw.get("step_delay_ms", 1000)),
                rehearsal_spd=int(raw.get("rehearsal_spd", 20)),
                confirmed=bool(raw.get("confirmed", False)),
                created_by=str(raw.get("created_by", "operator")),
                version=int(raw.get("version", 1)),
                state=str(raw.get("state", "idle")),
                current_step=int(raw.get("current_step", 0)),
                created_at=str(raw.get("created_at", "")),
                updated_at=str(raw.get("updated_at", "")),
            )
        )

    FlowRegistry(out_path).replace(entries)
    return len(entries)


def _convert_step(raw: dict) -> FlowStep:
    func_id = int(raw.get("func_id", 0))
    if func_id not in EXECUTABLE_FUNC_IDS:
        # Free-text / out-of-whitelist: keep the step for reference but mark it
        # non-executable so run_flow reports it as unsupported rather than
        # silently doing nothing or guessing a command.
        func_id = 0
    return FlowStep(
        step_id=int(raw.get("step_id", 0)),
        action=str(raw.get("action", "")),
        func_id=func_id,
        params=dict(raw.get("params", {})),
        position_name=raw.get("position_name"),
        spd_pct=int(raw.get("spd_pct", raw.get("speed_pct", 50))),
        description=str(raw.get("description", "")),
    )
