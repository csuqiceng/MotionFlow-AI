#!/usr/bin/env python
"""Re-register legacy free-text flows as structured (func_id=108) flows.

Legacy flows (created before the structured operator existed) store their
steps with ``func_id=0`` and only a ``query_key`` / ``description`` referring
to a position name. This script walks every flow in
``~/.nanobot/robot_ai/flows.json`` whose steps still have ``func_id=0``,
tries to resolve each step's position reference against
``~/.nanobot/robot_ai/positions.json`` (PositionRegistry), and re-registers
the flow with ``func_id=108`` + a concrete ``target_pose`` for every step
that resolves.

Steps that cannot be resolved (truly free-text, e.g. "小臂上下点头") are left
as ``func_id=0``. If any step in a flow cannot be resolved the whole flow is
left untouched so we never produce a half-structured flow.

Skip list: ``点头`` was already migrated manually, so it is never modified.

Run with the project venv::

    .venv-robot-desktop/Scripts/python.exe tools/reregister_flows_structured.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Make ``robot_ai`` importable when run as a script.
HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.flow.registry import FlowRegistry  # noqa: E402
from robot_ai.flow.models import FlowStep  # noqa: E402
from robot_ai.positions.registry import PositionRegistry  # noqa: E402

# Names that must never be touched by this migration.
SKIP_FLOWS = {"点头"}

# Mapping of free-text phrases to canonical position names. Keys are matched
# case-insensitively as substrings inside a step's query_key/description.
PHRASE_TO_POSITION = {
    "休息姿态": "atomic:rest_pose",
    "休息位": "atomic:rest_pose",
    "rest": "atomic:rest_pose",
    "home": "atomic:position:HOME",
    "原点": "atomic:position:HOME",
    "回家": "atomic:position:HOME",
}


def nanobot_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai"


def resolve_position_name(positions: PositionRegistry, hint: str) -> str | None:
    """Resolve a free-text hint to a concrete position name.

    Resolution order:
      1. Exact match against the position registry (case-insensitive).
      2. PHRASE_TO_POSITION substring lookup (休息位, home, ...).
      3. ``位置X`` / ``移动到位置X`` -> ``X``.
      4. Single trailing letter/digit substring match (only if exactly one
         position matches, to avoid ambiguous picks).
    """
    hint = (hint or "").strip()
    if not hint:
        return None

    # 1. Exact name match.
    if positions.get(hint) is not None:
        return hint

    low = hint.lower()

    # 2. Phrase table.
    for phrase, canonical in PHRASE_TO_POSITION.items():
        if phrase in low:
            if positions.get(canonical) is not None:
                return canonical

    # 3. 位置X / move to position X.
    m = re.search(r"位置\s*([A-Za-z0-9_:+\-]+)", hint)
    if m:
        cand = m.group(1)
        if positions.get(cand) is not None:
            return cand

    # 4. Last-resort unique substring match.
    token = hint.split(":")[-1].strip()
    if token:
        candidates = [
            p.name for p in positions.list_all() if token.lower() in p.name.lower()
        ]
        if len(candidates) == 1:
            return candidates[0]

    return None


def build_structured_step(step: FlowStep, position_name: str) -> FlowStep:
    """Return a new FlowStep mirroring the operator's func_id=108 shape."""
    raise RuntimeError("replaced inline below — kept for grep visibility")


def make_structured_step(src_step: FlowStep, position_name: str, pose_map: dict[str, float], spd: float) -> FlowStep:
    target_pose = {
        "x": pose_map.get("x", 0.0),
        "y": pose_map.get("y", 0.0),
        "z": pose_map.get("z", 0.0),
        "rx": pose_map.get("rx", 0.0),
        "ry": pose_map.get("ry", 0.0),
        "rz": pose_map.get("rz", 0.0),
    }
    spd_pct = int(round(spd)) if spd else int(src_step.spd_pct or 50)
    params = {
        "target_pose": target_pose,
        "speed_pct": spd_pct,
        "acceleration_pct": 50,
        "deceleration_pct": 50,
    }
    return FlowStep(
        step_id=src_step.step_id,
        action="linear_move",
        func_id=108,
        params=params,
        position_name=position_name,
        spd_pct=spd_pct,
        description=f"移动到位置 {position_name}",
    )


def migrate(dry_run: bool = False) -> dict:
    base = nanobot_dir()
    flows_path = base / "flows.json"
    positions_path = base / "positions.json"

    flows = FlowRegistry(flows_path)
    positions = PositionRegistry(positions_path)

    report: dict = {
        "re_registered": [],
        "unresolved": [],
        "skipped": [],
        "details": {},
    }

    for flow in flows.list_all():
        if flow.name in SKIP_FLOWS:
            report["skipped"].append(flow.name)
            continue

        legacy_steps = [s for s in flow.steps if s.func_id == 0]
        if not legacy_steps:
            continue

        resolved_steps: list[FlowStep] = []
        unresolved_hints: list[str] = []
        per_step: list[dict] = []

        for step in flow.steps:
            if step.func_id != 0:
                resolved_steps.append(step)
                per_step.append({
                    "step_id": step.step_id,
                    "func_id": step.func_id,
                    "outcome": "unchanged",
                })
                continue

            hint = step.params.get("query_key") or step.action or step.description or ""
            position_name = resolve_position_name(positions, hint)
            if position_name is None:
                unresolved_hints.append(hint)
                per_step.append({
                    "step_id": step.step_id,
                    "func_id": 0,
                    "hint": hint,
                    "outcome": "unresolved",
                })
                continue

            pose_map = positions.resolve(position_name)
            if pose_map is None:
                unresolved_hints.append(hint)
                per_step.append({
                    "step_id": step.step_id,
                    "func_id": 0,
                    "hint": hint,
                    "outcome": "unresolved",
                })
                continue

            np_entry = positions.get(position_name)
            spd = float(np_entry.spd) if np_entry else 50.0
            new_step = make_structured_step(step, position_name, pose_map, spd)
            resolved_steps.append(new_step)
            per_step.append({
                "step_id": step.step_id,
                "func_id": 0,
                "hint": hint,
                "outcome": "resolved",
                "position_name": position_name,
                "pose": pose_map,
                "spd": spd,
            })

        report["details"][flow.name] = per_step

        if unresolved_hints:
            report["unresolved"].append({
                "name": flow.name,
                "unresolved_hints": unresolved_hints,
                "step_count": len(flow.steps),
            })
            continue

        if not dry_run:
            ok, msg = flows.update(
                flow.name,
                steps=[s.to_dict() for s in resolved_steps],
                description=flow.description,
                step_delay_ms=flow.step_delay_ms,
                rehearsal_spd=flow.rehearsal_spd,
            )
            if not ok:
                report["unresolved"].append({
                    "name": flow.name,
                    "error": msg,
                    "step_count": len(flow.steps),
                })
                continue

        report["re_registered"].append({
            "name": flow.name,
            "steps": len(resolved_steps),
            "dry_run": dry_run,
        })

    return report


def _print_report(report: dict) -> None:
    print("=== Re-registered (structured, func_id=108) ===")
    for item in report["re_registered"]:
        suffix = " (dry-run)" if item.get("dry_run") else ""
        print(f"  - {item['name']}: {item['steps']} step(s){suffix}")
    if not report["re_registered"]:
        print("  (none)")

    print()
    print("=== Unresolved / kept as func_id=0 ===")
    for item in report["unresolved"]:
        if "error" in item:
            print(f"  - {item['name']}: ERROR {item['error']}")
        else:
            print(f"  - {item['name']} ({item['step_count']} step(s)):")
            for hint in item["unresolved_hints"]:
                print(f"      hint: {hint!r}")
    if not report["unresolved"]:
        print("  (none)")

    print()
    print("=== Skipped (already migrated / protected) ===")
    for name in report["skipped"]:
        print(f"  - {name}")
    if not report["skipped"]:
        print("  (none)")


def main() -> int:
    dry = "--dry-run" in sys.argv
    report = migrate(dry_run=dry)
    _print_report(report)

    # Persist a machine-readable copy next to flows.json for auditing.
    out_path = nanobot_dir() / "reregister_flows_report.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print()
    print(f"Report written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
