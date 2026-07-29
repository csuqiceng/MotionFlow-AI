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
import hmac
import json
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from robot_platform.library.catalog import ComponentCatalog
from robot_platform.library.models import Command, RiskLevel, normalize_id
from robot_platform.library.registry import CommandRegistry

DEFAULT_COMMANDS_PATH = "~/.nanobot/robot_ai/commands.json"
DEFAULT_AUDIT_PATH = "~/.nanobot/robot_ai/audit.jsonl"
SEED_RESOURCE_NAME = "seed_query_table.json"
_audit_locks_guard = RLock()
_audit_locks: dict[Path, RLock] = {}

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
    try:
        appended = _audit_append_once(audit_path, audit_entry)
        result.audit_written = True
        result.audit_already_present = not appended
    except OSError as e:  # noqa: BLE001 — commands succeeded; audit must be backfillable
        result.audit_error = str(e)
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
    for entry in read_verified_audit_records(audit_path):
        if (
            entry.get("_audit_alg") == "hmac-sha256"
            and entry.get("migration_id") == migration_id
        ):
            return True
    return False


def _audit_append(audit_path: str | Path, entry: dict[str, Any]) -> None:
    p = Path(audit_path).resolve()
    with _audit_process_lock(p):
        with _audit_locks_guard:
            lock = _audit_locks.setdefault(p, RLock())
        with lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            _audit_append_locked(p, entry)


def _audit_append_once(audit_path: str | Path, entry: dict[str, Any]) -> bool:
    """Atomically verify, deduplicate a signed identity, and append."""
    p = Path(audit_path).resolve()
    with _audit_process_lock(p):
        with _audit_locks_guard:
            lock = _audit_locks.setdefault(p, RLock())
        with lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            _verify_audit_chain_locked(p)
            identity = (
                ("audit_id", str(entry["audit_id"])) if entry.get("audit_id")
                else (("migration_id", str(entry["migration_id"]))
                      if entry.get("migration_id") else None)
            )
            if identity is not None and p.exists():
                for record in _read_audit_records_locked(p):
                    if (
                        record.get("_audit_alg") == "hmac-sha256"
                        and str(record.get(identity[0], "")) == identity[1]
                    ):
                        return False
            _audit_append_locked(p, entry)
            return True


def _audit_append_locked(path: Path, entry: dict[str, Any]) -> None:
    previous_hash, next_sequence = _verify_audit_chain_locked(path)
    chained = dict(entry)
    chained["_audit_seq"] = next_sequence
    chained["_audit_prev_hash"] = previous_hash
    key = _ensure_audit_integrity_key(path)
    if _load_audit_head(path, key) is None:
        _write_audit_head(path, key, next_sequence - 1, previous_hash)
    chained["_audit_alg"] = "hmac-sha256"
    chained["_audit_key_id"] = hashlib.sha256(key).hexdigest()[:16]
    canonical = _canonical_audit_json(chained)
    material = f"{previous_hash}|{canonical}".encode("utf-8")
    chained["_audit_hash"] = hmac.new(key, material, hashlib.sha256).hexdigest()
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(chained, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    _write_audit_head(path, key, next_sequence, chained["_audit_hash"])


class AuditIntegrityError(RuntimeError):
    pass


class AuditUnavailableError(AuditIntegrityError, OSError):
    """Audit storage is unavailable without implying a forged valid chain."""


def _canonical_audit_json(record: dict[str, Any]) -> str:
    """Return the stable on-disk representation used by the hash chain.

    JSON object keys are strings after persistence.  Normalizing through a
    round-trip before hashing prevents integer dictionary keys from producing
    a different sort order when the record is read back.
    """
    normalized = json.loads(json.dumps(record, ensure_ascii=False))
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def verify_audit_chain(audit_path: str | Path) -> tuple[str, int]:
    p = Path(audit_path).resolve()
    with _audit_process_lock(p):
        with _audit_locks_guard:
            lock = _audit_locks.setdefault(p, RLock())
        with lock:
            return _verify_audit_chain_locked(p)


def read_verified_audit_records(audit_path: str | Path) -> tuple[dict[str, Any], ...]:
    """Read audit entries only while holding the same lock used for verification."""
    p = Path(audit_path).resolve()
    with _audit_process_lock(p):
        with _audit_locks_guard:
            lock = _audit_locks.setdefault(p, RLock())
        with lock:
            _verify_audit_chain_locked(p)
            return _read_audit_records_locked(p)


@contextmanager
def _audit_process_lock(audit_path: Path):
    """Serialize audit verification and writes across server processes."""
    lock_path = audit_path.with_suffix(audit_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_audit_records_locked(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditIntegrityError("Audit log contains invalid JSON") from exc
        if not isinstance(record, dict):
            raise AuditIntegrityError("Audit record must be an object")
        records.append(record)
    return tuple(records)


def ensure_audit_chain(audit_path: str | Path) -> None:
    p = Path(audit_path).resolve()
    with _audit_process_lock(p):
        with _audit_locks_guard:
            lock = _audit_locks.setdefault(p, RLock())
        with lock:
            try:
                _verify_audit_chain_locked(p)
            except AuditIntegrityError:
                if not _is_legacy_public_hash_log(p):
                    raise
                raw = p.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                quarantine = p.with_name(
                    f"{p.stem}.untrusted-legacy-sha256-{digest[:16]}{p.suffix}"
                )
                if quarantine.exists():
                    raise AuditIntegrityError(
                        "Legacy audit quarantine target already exists"
                    )
                p.replace(quarantine)
                _audit_append_locked(p, {
                    "action": "audit_legacy_sha_quarantined",
                    "actor": "system:bootstrap",
                    "legacy_file": quarantine.name,
                    "legacy_file_sha256": digest,
                    "timestamp": datetime.now().isoformat(),
                })
                return
            _ensure_audit_integrity_key(p)
            records = _read_audit_records_locked(p)
            last_is_protected = bool(records) and (
                records[-1].get("_audit_alg") == "hmac-sha256"
            )
            if not last_is_protected:
                _audit_append_locked(p, {
                    "action": "audit_chain_checkpoint",
                    "actor": "system:bootstrap",
                    "timestamp": datetime.now().isoformat(),
                })


def _is_legacy_public_hash_log(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        records = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return False
    if not records or any(not isinstance(record, dict) for record in records):
        return False
    previous = "0" * 64
    for sequence, original in enumerate(records, 1):
        record = dict(original)
        stored_hash = record.pop("_audit_hash", None)
        if stored_hash is None:
            # Quarantine is only safe for the exact historical format that
            # emitted a complete public-SHA chain from record one.  An
            # unchained prefix followed by SHA records is ambiguous and must
            # fail closed instead of being rewritten as trusted history.
            return False
        if record.get("_audit_alg") is not None:
            return False
        if (
            record.get("_audit_seq") != sequence
            or record.get("_audit_prev_hash") != previous
        ):
            return False
        expected = hashlib.sha256(
            f"{previous}|{_canonical_audit_json(record)}".encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(str(stored_hash), expected):
            return False
        previous = str(stored_hash)
    return True


def _verify_audit_chain_locked(path: Path) -> tuple[str, int]:
    previous = "0" * 64
    sequence = 0
    chain_started = False
    if not path.exists():
        if _audit_head_path(path).exists():
            key = _load_audit_integrity_key(path)
            if key is None:
                raise AuditIntegrityError("Audit integrity key is unavailable")
            head = _load_audit_head(path, key)
            if head is None or not (
                int(head.get("sequence", -1)) == 0
                and head.get("head_hash") == "0" * 64
            ):
                raise AuditIntegrityError("Audit log was deleted or rolled back")
        return previous, 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AuditUnavailableError("Audit log cannot be read") from exc
    last_record_previous = ""
    for line in lines:
        if not line.strip():
            continue
        sequence += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditIntegrityError("Audit log contains invalid JSON") from exc
        if not isinstance(record, dict):
            raise AuditIntegrityError("Audit record must be an object")
        stored_hash = record.pop("_audit_hash", None)
        stored_previous = record.get("_audit_prev_hash")
        stored_sequence = record.get("_audit_seq")
        if stored_hash is None:
            if chain_started:
                raise AuditIntegrityError("Unchained audit record follows protected records")
            canonical = _canonical_audit_json(record)
            previous = hashlib.sha256(
                f"{previous}|{canonical}".encode("utf-8")
            ).hexdigest()
            continue
        if stored_previous != previous or stored_sequence != sequence:
            raise AuditIntegrityError("Audit chain linkage is invalid")
        canonical = _canonical_audit_json(record)
        material = f"{previous}|{canonical}".encode("utf-8")
        algorithm = record.get("_audit_alg")
        if algorithm == "hmac-sha256":
            key = _load_audit_integrity_key(path)
            if key is None:
                raise AuditIntegrityError("Audit integrity key is unavailable")
            if record.get("_audit_key_id") != hashlib.sha256(key).hexdigest()[:16]:
                raise AuditIntegrityError("Audit integrity key id does not match")
            expected = hmac.new(key, material, hashlib.sha256).hexdigest()
        elif algorithm is None:
            raise AuditIntegrityError(
                "Authenticated audit records must use hmac-sha256"
            )
        else:
            raise AuditIntegrityError("Audit record algorithm is unsupported")
        if stored_hash != expected:
            raise AuditIntegrityError("Audit record hash is invalid")
        last_record_previous = str(stored_previous)
        previous = stored_hash
        chain_started = True
    if chain_started:
        key = _load_audit_integrity_key(path)
        if key is None:
            raise AuditIntegrityError("Audit integrity key is unavailable")
        _verify_or_recover_audit_head(
            path, key, sequence, previous, last_record_previous,
        )
    elif _audit_head_path(path).exists():
        key = _load_audit_integrity_key(path)
        if key is None:
            raise AuditIntegrityError("Audit integrity key is unavailable")
        head = _load_audit_head(path, key)
        if head is None or not (
            int(head.get("sequence", -1)) == sequence
            and head.get("head_hash") == previous
        ):
            raise AuditIntegrityError(
                "Audit log truncation removed authenticated records"
            )
    return previous, sequence + 1


def _audit_integrity_key_path(audit_path: Path) -> Path:
    configured = os.environ.get("MOTIONFLOW_AUDIT_KEY_PATH", "").strip()
    if configured:
        key_path = Path(os.path.expanduser(configured)).resolve()
    else:
        key_path = (
            audit_path.parent.parent / ".motionflow-secrets" / "audit-integrity.key"
        ).resolve()
    try:
        key_path.relative_to(audit_path.parent.resolve())
    except ValueError:
        return key_path
    raise AuditIntegrityError(
        "Audit integrity key must be stored outside the audit log directory"
    )


def _audit_head_path(audit_path: Path) -> Path:
    digest = hashlib.sha256(str(audit_path.resolve()).encode()).hexdigest()[:16]
    return (
        _audit_integrity_key_path(audit_path).parent /
        f"audit-{digest}.head.json"
    ).resolve()


def _write_audit_head(
    audit_path: Path, key: bytes, sequence: int, head_hash: str,
) -> None:
    from robot_platform.library.storage import atomic_write_json

    payload: dict[str, Any] = {
        "schema_version": 1,
        "audit_path_hash": hashlib.sha256(
            str(audit_path.resolve()).encode()
        ).hexdigest(),
        "sequence": int(sequence),
        "head_hash": str(head_hash),
    }
    payload["_integrity_mac"] = hmac.new(
        key, _canonical_audit_json(payload).encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    head_path = _audit_head_path(audit_path)
    head_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(head_path, payload)


def _load_audit_head(audit_path: Path, key: bytes) -> dict[str, Any] | None:
    path = _audit_head_path(audit_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        stored_mac = str(payload.pop("_integrity_mac"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AuditIntegrityError("Audit sealed head is invalid") from exc
    expected = hmac.new(
        key, _canonical_audit_json(payload).encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    if (
        payload.get("schema_version") != 1
        or payload.get("audit_path_hash") != hashlib.sha256(
            str(audit_path.resolve()).encode()
        ).hexdigest()
        or not hmac.compare_digest(stored_mac, expected)
    ):
        raise AuditIntegrityError("Audit sealed head integrity failed")
    return payload


def _verify_or_recover_audit_head(
    audit_path: Path, key: bytes, sequence: int, head_hash: str,
    last_record_previous: str,
) -> None:
    head = _load_audit_head(audit_path, key)
    if head is None:
        raise AuditIntegrityError(
            "Authenticated audit log requires an external sealed head"
        )
    try:
        sealed_sequence = int(head["sequence"])
        sealed_hash = str(head["head_hash"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuditIntegrityError("Audit sealed head is invalid") from exc
    if sequence == sealed_sequence and head_hash == sealed_hash:
        return
    if sequence == sealed_sequence + 1 and last_record_previous == sealed_hash:
        # The one-record-forward state is a safe append/head crash window: a
        # valid HMAC record cannot be forged by a data-directory attacker.
        _write_audit_head(audit_path, key, sequence, head_hash)
        return
    raise AuditIntegrityError("Audit log truncation or rollback was detected")


def _ensure_audit_integrity_key(audit_path: Path) -> bytes:
    key_path = _audit_integrity_key_path(audit_path)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        from robot_platform.library.storage import atomic_write_json

        encoded = secrets.token_hex(32)
        atomic_write_json(key_path, {"schema_version": 1, "key": encoded})
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    key = _load_audit_integrity_key(audit_path)
    if key is None:
        raise AuditIntegrityError("Audit integrity key cannot be initialized")
    return key


def _load_audit_integrity_key(audit_path: Path) -> bytes | None:
    key_path = _audit_integrity_key_path(audit_path)
    if not key_path.is_file():
        return None
    try:
        payload = json.loads(key_path.read_text(encoding="utf-8"))
        encoded = str(payload.get("key", ""))
        key = bytes.fromhex(encoded)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AuditIntegrityError("Audit integrity key is invalid") from exc
    if len(key) < 32:
        raise AuditIntegrityError("Audit integrity key is too short")
    return key


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
