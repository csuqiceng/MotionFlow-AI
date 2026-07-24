"""Migrate legacy ``query_table.json`` into the CommandRegistry + audit log.

Rules (spec §6):
- Only func 104/108/110/120 map to a v1 component; others are SKIPPED + reported.
- Migrated commands are ``published`` v1, ``source=legacy-import``, audited.
- Idempotent: re-run is a no-op for already-imported ids; audit deduped by a
  stable ``migration_id`` (sha256 of the source bytes).
- Two-file failure semantics: commands write first, audit append second. If the
  audit append fails, the run returns failure (``audit_error`` set); a re-run
  backfills the missing audit without duplicating commands — so the system
  never ends in "commands imported but permanently no audit".
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_platform.library.catalog import ComponentCatalog
from robot_platform.library.models import Command, RiskLevel, normalize_id
from robot_platform.library.registry import CommandRegistry

DEFAULT_COMMANDS_PATH = "~/.nanobot/robot_ai/commands.json"
DEFAULT_AUDIT_PATH = "~/.nanobot/robot_ai/audit.jsonl"
SEED_RESOURCE_NAME = "seed_query_table.json"

_SKIP_REASONS: dict[int, str] = {
    106: "v1 component set has no joint_move (Func106)",
    107: "v1 component set has no virtual-axis relative move (Func107)",
    109: "delay maps to Func110 only; Func109 not mapped",
    11: "v1 component set has no continuous interpolation (Func11)",
}

_PY_TYPES: dict[str, type | tuple[type, ...]] = {
    "int": int,
    "float": (int, float),
    "str": str,
    "bool": bool,
}


def _default_commands_path() -> Path:
    from robot_platform.runtime import get_robot_data_dir

    return get_robot_data_dir() / "commands.json"


def _default_audit_path() -> Path:
    from robot_platform.runtime import get_robot_data_dir

    return get_robot_data_dir() / "audit.jsonl"


@dataclass
class MigrationResult:
    migration_id: str
    migrated: list[tuple[str, str]] = field(default_factory=list)  # (id, name)
    skipped: list[tuple[int, str, str]] = field(default_factory=list)  # (func, name, reason)
    dropped_aliases: int = 0
    audit_written: bool = False
    audit_already_present: bool = False
    audit_error: str | None = None


def migrate_commands(
    src_path: str | Path,
    commands_path: str | Path,
    audit_path: str | Path,
) -> MigrationResult:
    raw = Path(src_path).read_bytes()
    migration_id = "legacy-import:" + hashlib.sha256(raw).hexdigest()[:12]
    records = json.loads(raw.decode("utf-8")).get("records", [])

    catalog = ComponentCatalog()
    registry = CommandRegistry(commands_path)
    seen = registry.namespace()  # existing names + aliases (lowercased)
    result = MigrationResult(migration_id=migration_id)

    for rec in records:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("query_key", "")).strip()
        if not name:
            continue
        cid = normalize_id(name)
        if registry.get(cid) is not None:
            continue  # already imported — idempotent no-op
        func_num = int(rec.get("func_num", 0))
        component_id = catalog.func_to_id(func_num)
        if component_id is None:
            result.skipped.append((func_num, name, _skip_reason(func_num)))
            continue
        params = dict(rec.get("params", {}))
        ok, reason = _validate_params(catalog.get(component_id), params)
        if not ok:
            result.skipped.append((func_num, name, reason))
            continue
        if name.lower() in seen:
            result.skipped.append((func_num, name, "name conflicts with existing command/alias"))
            continue
        aliases: list[str] = []
        seen_this = {name.lower()}
        for kw in str(rec.get("keywords", "")).split():
            kl = kw.lower()
            if kl == name.lower() or kl in seen or kl in seen_this:
                result.dropped_aliases += 1
                continue
            seen_this.add(kl)
            aliases.append(kw)
        cmd = Command(
            id=cid,
            name=name,
            component_id=component_id,
            parameters=params,
            aliases=aliases,
            description=str(rec.get("description", "")),
            risk_level=_map_risk(rec.get("safety_level")),
            status="published",
            version=1,
            source="legacy-import",
            created_by="system:migration",
        )
        added, _ = registry.add(cmd)
        if added:
            result.migrated.append((cid, name))
            seen.add(name.lower())
            seen.update(a.lower() for a in aliases)
        else:
            result.skipped.append((func_num, name, "registry rejected (namespace conflict)"))

    audit_entry = {
        "action": "legacy_import",
        "actor": "system:migration",
        "migration_id": migration_id,
        "after": {
            "migrated": len(result.migrated),
            "skipped": len(result.skipped),
            "skipped_by_func": _count_by_func(result.skipped),
            "skipped_reasons": [r for _f, _n, r in result.skipped],
            "dropped_aliases": result.dropped_aliases,
        },
        "timestamp": datetime.now().isoformat(),
    }
    if not _audit_has(audit_path, migration_id):
        try:
            _audit_append(audit_path, audit_entry)
            result.audit_written = True
        except OSError as e:  # noqa: BLE001 — commands succeeded; audit must be backfillable
            result.audit_error = str(e)
    else:
        result.audit_written = True  # already present (dedup)
        result.audit_already_present = True
    return result


def _skip_reason(func_num: int) -> str:
    return _SKIP_REASONS.get(func_num, f"Func{func_num} not in v1 component allowlist")


def _map_risk(safety_level: Any) -> str:
    try:
        level = int(safety_level)
    except (TypeError, ValueError):
        return RiskLevel.MEDIUM.value
    return RiskLevel.HIGH.value if level >= 4 else RiskLevel.MEDIUM.value


def _validate_params(component: Any, params: dict[str, Any]) -> tuple[bool, str]:
    for pf in component.parameters:
        if pf.required and pf.name not in params:
            return False, f"missing required parameter '{pf.name}'"
    for pf in component.parameters:
        if pf.name not in params:
            continue
        val = params[pf.name]
        expected = _PY_TYPES.get(pf.type)
        if expected is None:
            continue
        if pf.type in ("int", "float") and isinstance(val, bool):
            return False, f"parameter '{pf.name}' must be {pf.type}, not bool"
        if not isinstance(val, expected):
            return False, f"parameter '{pf.name}' must be {pf.type}"
    return True, ""


def _count_by_func(skipped: list[tuple[int, str, str]]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for func, _name, _reason in skipped:
        counts[func] = counts.get(func, 0) + 1
    return counts


def _audit_has(audit_path: str | Path, migration_id: str) -> bool:
    p = Path(audit_path)
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("migration_id") == migration_id:
            return True
    return False


def _audit_append(audit_path: str | Path, entry: dict[str, Any]) -> None:
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def seed_command_library_if_missing(
    commands_path: str | Path | None = None,
    audit_path: str | Path | None = None,
    *,
    seed_path: str | Path | None = None,
    log: Any = None,
) -> bool:
    """Idempotently seed the command library from the packaged seed.

    Called once at robot-server startup. Rules (spec §3.1):
    - ``commands.json`` already exists -> never overwrite (no-op), return False.
    - missing -> migrate from the packaged ``seed_query_table.json`` (16 published).
    - seed resource missing or migration fails -> log an explicit error and leave
      the library empty; return False. Never silently end up with an empty library.
    Returns True only when the seed wrote commands this call.
    """
    import importlib.resources

    from loguru import logger

    cpath = Path(os.path.expanduser(commands_path)) if commands_path else _default_commands_path()
    if cpath.exists():
        return False  # never overwrite an existing library
    apath = Path(os.path.expanduser(audit_path)) if audit_path else _default_audit_path()
    try:
        if seed_path is None:
            with importlib.resources.as_file(
                importlib.resources.files("robot_platform.library") / SEED_RESOURCE_NAME
            ) as resolved:
                result = migrate_commands(resolved, cpath, apath)
        else:
            result = migrate_commands(seed_path, cpath, apath)
    except FileNotFoundError as e:
        (log or logger).error(
            "command library seed resource missing; library left empty: {}", e
        )
        return False
    except Exception as e:  # noqa: BLE001
        (log or logger).error("command library seed failed; library left empty: {}", e)
        return False
    (log or logger).info(
        "command library seeded from packaged resource: {} migrated, {} skipped",
        len(result.migrated),
        len(result.skipped),
    )
    return True


def migrate_commands_schema_if_needed(commands_path: str | Path | None = None) -> bool:
    """Migrate commands.json from schema 1.0 (A1 list) to 2.0 (version tree).

    Idempotent: already 2.0 or file missing -> no-op.
    Called at gateway startup AFTER seed_command_library_if_missing (seed->migrate order).
    Returns True if migrated, False if skipped.
    """
    from robot_platform.library.storage import atomic_write_json

    cpath = Path(os.path.expanduser(commands_path)) if commands_path else _default_commands_path()
    if not cpath.exists():
        return False
    raw = json.loads(cpath.read_text(encoding="utf-8"))
    sv = raw.get("schema_version") or raw.get("version")
    if sv == "2.0":
        return False  # already migrated
    if sv != "1.0":
        raise ValueError(
            f"Unknown commands.json schema version {sv!r}; expected '1.0' or '2.0'. "
            "Refusing to migrate — original data preserved."
        )
    old_commands = raw.get("commands", [])
    new_commands: dict[str, Any] = {}
    for cmd in old_commands:
        cid = cmd.get("id", "")
        if not cid:
            continue
        new_commands[cid] = {
            "command_id": cid,
            "published_version": 1,
            "versions": {"1": dict(cmd)},
            "draft": None,
            "updated_at": cmd.get("updated_at", ""),
        }
    new_data = {
        "schema_version": "2.0",
        "updated_at": datetime.now().isoformat(),
        "commands": new_commands,
        "pending_audits": [],
    }
    atomic_write_json(cpath, new_data)
    return True


def initialize_robot_libraries(
    commands_path: str | Path | None = None,
    audit_path: str | Path | None = None,
) -> None:
    """Startup sequence: seed -> migrate -> drain. Idempotent + crash-recovery.

    Called once at gateway startup (``_run_gateway``). On first install:
    seed creates schema 1.0 -> migrate converts to 2.0 -> drain flushes any
    pending outbox from a prior crash.
    """
    from robot_platform.library.versioned_registry import VersionedCommandRegistry

    cpath = str(Path(os.path.expanduser(commands_path))) if commands_path else str(_default_commands_path())
    apath = str(Path(os.path.expanduser(audit_path))) if audit_path else str(_default_audit_path())
    seed_command_library_if_missing(commands_path=cpath, audit_path=apath)
    migrate_commands_schema_if_needed(cpath)
    VersionedCommandRegistry(cpath, audit_path=apath).drain_pending_audits()
