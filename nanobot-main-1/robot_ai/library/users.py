"""Multi-user identity store (schema 1.0).

Mirrors VersionedCommandRegistry: users.json + pending_audits outbox, atomic
writes, idempotent drain. Replaces B1a's single-engineer-password model.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_ai.library.storage import atomic_write_json

DEFAULT_USERS_PATH = "~/.nanobot/robot_ai/users.json"
DEFAULT_AUDIT_PATH = "~/.nanobot/robot_ai/audit.jsonl"


def normalize_username(name: str | None) -> str:
    """Independent of normalize_id (command-id domain). strip + casefold only."""
    return (name or "").strip().casefold()


class LastEngineerError(Exception):
    """Raised when an op would leave zero enabled engineers."""


class UserRegistry:

    def __init__(self, path: str | Path, *, audit_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.audit_path = Path(os.path.expanduser(audit_path or DEFAULT_AUDIT_PATH))
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {"schema_version": "1.0", "users": {}, "pending_audits": []}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != "1.0":
            raise ValueError(f"Expected users.json schema 1.0, got {raw.get('schema_version')!r}.")
        raw.setdefault("users", {})
        raw.setdefault("pending_audits", [])
        self._data = raw

    def _save(self) -> None:
        self._data["updated_at"] = datetime.now().isoformat()
        atomic_write_json(self.path, self._data)

    def _commit_with_audit(self, action: str, actor: dict[str, Any], target: dict[str, Any],
                            payload: dict[str, Any]) -> str:
        audit_id = secrets.token_urlsafe(16)
        entry = {
            "audit_id": audit_id, "action": action, "timestamp": datetime.now().isoformat(),
            "actor": actor.get("actor", "system"),
            "actor_user_id": actor.get("actor_user_id"),
            "actor_username": actor.get("actor_username"),
            "actor_role": actor.get("actor_role"),
            "target": target, "payload": payload,
        }
        self._data["pending_audits"].append(entry)
        self._save()
        self.drain_pending_audits()
        return audit_id

    def drain_pending_audits(self) -> list[str]:
        from robot_ai.library.migration import _audit_append
        pending = self._data.get("pending_audits", [])
        if not pending:
            return []
        existing: set[str] = set()
        if self.audit_path.exists():
            for line in self.audit_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    eid = json.loads(line).get("audit_id") or json.loads(line).get("migration_id")
                    if eid:
                        existing.add(eid)
                except json.JSONDecodeError:
                    continue
        written: list[str] = []
        remaining: list[dict[str, Any]] = []
        for item in pending:
            aid = item.get("audit_id")
            if aid and aid in existing:
                continue
            try:
                _audit_append(self.audit_path, item)
                written.append(aid)
            except OSError:
                remaining.append(item)
        self._data["pending_audits"] = remaining
        if len(remaining) != len(pending):
            self._save()
        return written

    # -- queries --

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self._data["users"].get(user_id)

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        target = normalize_username(username)
        for u in self._data["users"].values():
            if normalize_username(u["username"]) == target:
                return u
        return None

    def list_all(self) -> list[dict[str, Any]]:
        return [dict(u) for u in self._data["users"].values()]

    def enabled_engineer_count(self) -> int:
        return sum(1 for u in self._data["users"].values()
                   if u["role"] == "engineer" and u["enabled"])

    # -- mutations --

    def create(self, username: str, role: str, password_hash: str, *,
               enabled: bool = True, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        if role not in ("operator", "engineer"):
            raise ValueError(f"Invalid role {role!r}.")
        if not normalize_username(username):
            raise ValueError("Username must not be empty.")
        if self.get_by_username(username) is not None:
            raise ValueError(f"Username {username!r} already exists.")
        now = datetime.now().isoformat()
        user_id = secrets.token_urlsafe(8)
        user = {"user_id": user_id, "username": username, "role": role,
                "password_hash": password_hash, "enabled": enabled,
                "created_at": now, "updated_at": now}
        self._data["users"][user_id] = user
        self._commit_with_audit(
            "user_create", actor or {"actor": "system"}, {"user_id": user_id},
            {"username": username, "role": role, "enabled": enabled})
        return user

    def update(self, user_id: str, *, enabled: bool | None = None, role: str | None = None,
               actor: dict[str, Any] | None = None) -> dict[str, Any]:
        user = self.get(user_id)
        if user is None:
            raise ValueError(f"User {user_id!r} not found.")
        # Last-engineer protection
        will_lose_engineer = (
            (enabled is False or (role == "operator" and user["role"] == "engineer"))
            and user["role"] == "engineer" and user["enabled"]
            and self.enabled_engineer_count() <= 1
        )
        if will_lose_engineer:
            raise LastEngineerError("Refusing: would leave zero enabled engineers.")
        before = {"enabled": user["enabled"], "role": user["role"]}
        if enabled is not None:
            user["enabled"] = enabled
        if role is not None:
            if role not in ("operator", "engineer"):
                raise ValueError(f"Invalid role {role!r}.")
            user["role"] = role
        user["updated_at"] = datetime.now().isoformat()
        action = ("user_disable" if enabled is False
                  else "user_enable" if enabled is True
                  else "user_role_change" if role is not None else "user_update")
        self._commit_with_audit(action, actor or {"actor": "system"},
                                 {"user_id": user_id}, {"before": before, "after": {"enabled": user["enabled"], "role": user["role"]}})
        return user

    def set_password(self, user_id: str, password_hash: str, *, actor: dict[str, Any] | None = None,
                     action: str = "user_password_change") -> dict[str, Any]:
        user = self.get(user_id)
        if user is None:
            raise ValueError(f"User {user_id!r} not found.")
        user["password_hash"] = password_hash
        user["updated_at"] = datetime.now().isoformat()
        self._commit_with_audit(action, actor or {"actor": "system"}, {"user_id": user_id}, {})
        return user

    def bootstrap_set_password(self, user_id: str, password_hash: str, *,
                                actor: dict[str, Any] | None = None) -> dict[str, Any]:
        """Atomic: set password hash AND enable in ONE write + ONE outbox/audit entry.
        Used by CLI set-bootstrap-password and the deprecated engineer set-password alias
        (spec §6: 'password + enable same atomic write')."""
        user = self.get(user_id)
        if user is None:
            raise ValueError(f"User {user_id!r} not found.")
        user["password_hash"] = password_hash
        user["enabled"] = True
        user["updated_at"] = datetime.now().isoformat()
        self._commit_with_audit("user_bootstrap_password", actor or {"actor": "system"},
                                 {"user_id": user_id}, {"enabled": True})
        return user


def migrate_users_if_needed(*, users_path: str | Path | None = None, b1a_config_path=None,
                             gateway_secret: str = "", audit_path: str | Path | None = None) -> bool:
    """Create users.json on first run from B1a engineer hash + gateway secret. Idempotent.

    admin (engineer): B1a password_hash if present, else disabled placeholder (CLI bootstrap).
    operator: hash_password(secret) if secret readable, else disabled placeholder.
    NEVER uses a gateway API token as a password."""
    import secrets as _secrets

    upath = Path(os.path.expanduser(users_path or DEFAULT_USERS_PATH))
    if upath.exists():
        return False
    apath = Path(os.path.expanduser(audit_path or DEFAULT_AUDIT_PATH))

    admin_hash = ""
    if b1a_config_path is not None:
        try:
            from nanobot.config.loader import load_config
            admin_hash = (load_config(Path(b1a_config_path)).robot_ai.engineer.password_hash or "")
        except Exception:
            admin_hash = ""

    reg = UserRegistry(upath, audit_path=apath)
    reg.create("admin", "engineer",
               admin_hash if admin_hash else _secrets.token_urlsafe(16),
               enabled=bool(admin_hash),
               actor={"actor": "system:migration", "actor_role": "system"})
    if gateway_secret:  # persisted config field token_issue_secret/token, NOT an API token
        from robot_ai.library.auth import hash_password
        reg.create("operator", "operator", hash_password(gateway_secret), enabled=True,
                   actor={"actor": "system:migration", "actor_role": "system"})
    else:
        reg.create("operator", "operator", _secrets.token_urlsafe(16), enabled=False,
                   actor={"actor": "system:migration", "actor_role": "system"})
    reg.drain_pending_audits()
    from robot_ai.library.migration import _audit_append
    try:
        _audit_append(apath, {"action": "users_migration", "actor": "system:migration",
                              "actor_role": "system", "audit_id": _secrets.token_urlsafe(16),
                              "timestamp": datetime.now().isoformat(),
                              "payload": {"admin_from_b1a_hash": bool(admin_hash),
                                          "operator_from_secret": bool(gateway_secret)}})
    except OSError:
        pass
    return True


def initialize_user_identity(*, users_path: str | Path | None = None,
                              audit_path: str | Path | None = None,
                              b1a_config_path=None, gateway_secret: str = "") -> None:
    """Identity-domain startup: migrate_users_if_needed -> drain. Idempotent. Separate from
    initialize_robot_libraries (command-library domain). Called by _run_gateway AFTER it."""
    upath = os.path.expanduser(users_path or DEFAULT_USERS_PATH)
    apath = os.path.expanduser(audit_path or DEFAULT_AUDIT_PATH)
    migrate_users_if_needed(users_path=upath, b1a_config_path=b1a_config_path,
                             gateway_secret=gateway_secret, audit_path=apath)
    UserRegistry(upath, audit_path=apath).drain_pending_audits()
