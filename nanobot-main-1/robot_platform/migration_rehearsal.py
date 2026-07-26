"""Safe, offline rehearsal for the legacy robot-data directory migration."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from robot_platform.runtime import migrate_legacy_robot_data_dir


def _manifest(root: Path) -> list[dict[str, Any]]:
    """Return a deterministic file inventory without changing ``root``."""
    items: list[dict[str, Any]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        raw = path.read_bytes()
        item: dict[str, Any] = {
            "path": path.relative_to(root).as_posix(),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if path.suffix.lower() == ".json":
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                item["json"] = "invalid"
            else:
                item["json"] = "object" if isinstance(decoded, dict) else "array" if isinstance(decoded, list) else "scalar"
                item["json_top_level_items"] = len(decoded) if isinstance(decoded, (dict, list)) else 1
        items.append(item)
    return items


def _is_inside(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
    except ValueError:
        return False
    return True


def rehearse_legacy_runtime_migration(
    source_runtime: str | Path,
    scratch_root: str | Path,
) -> dict[str, Any]:
    """Copy a runtime to scratch and verify its legacy-data migration offline.

    The source is never written to, the scratch directory must be empty, and
    no server/backend is started.  The returned report is also persisted next
    to the scratch copy for release evidence.
    """
    source = Path(source_runtime).expanduser().resolve(strict=True)
    scratch = Path(scratch_root).expanduser().resolve(strict=False)
    legacy_source = source / "robot_ai"
    if not source.is_dir() or not legacy_source.is_dir():
        raise ValueError("source runtime must contain a robot_ai directory")
    if _is_inside(scratch, source):
        raise ValueError("scratch directory must not be inside the source runtime")
    if scratch.exists() and not scratch.is_dir():
        raise ValueError("scratch path must be a directory")
    if scratch.exists() and any(scratch.iterdir()):
        raise ValueError("scratch directory must be empty")

    source_before = _manifest(legacy_source)
    scratch.mkdir(parents=True, exist_ok=True)
    copied_runtime = scratch / "runtime"
    shutil.copytree(source, copied_runtime)

    legacy_copy = copied_runtime / "robot_ai"
    source_has_canonical_data = (copied_runtime / "robot_platform").exists()
    replay_root = scratch / "legacy-replay"
    replay_legacy = replay_root / "robot_ai"
    shutil.copytree(legacy_copy, replay_legacy)
    target = replay_root / "robot_platform"
    migrated = migrate_legacy_robot_data_dir(target)
    legacy_after = _manifest(legacy_copy)
    target_manifest = _manifest(target) if target.is_dir() else []
    source_after = _manifest(legacy_source)
    report = {
        "version": 1,
        "simulation_only": True,
        "source_runtime": str(source),
        "scratch_runtime": str(copied_runtime),
        "scratch_legacy_replay": str(replay_root),
        "source_has_canonical_data": source_has_canonical_data,
        "migration_performed": migrated,
        "legacy_preserved": source_before == source_after and legacy_after == source_before,
        "target_matches_legacy": target_manifest == source_before,
        "source_legacy_manifest": source_before,
        "target_manifest": target_manifest,
    }
    report["ok"] = bool(
        report["migration_performed"]
        and report["legacy_preserved"]
        and report["target_matches_legacy"]
    )
    (scratch / "runtime-migration-rehearsal.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
