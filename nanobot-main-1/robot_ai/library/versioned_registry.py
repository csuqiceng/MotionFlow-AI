"""Versioned command registry (schema 2.0).

Stores logical command entities with immutable published versions + a single
editable draft + a root ``pending_audits`` outbox for all command state changes
(create/draft/publish/archive). Replaces the A1 single-record CommandRegistry
for engineer write operations.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_ai.library.storage import atomic_write_json


class ConflictError(Exception):
    """Optimistic concurrency conflict or archive blocked."""
    def __init__(self, message: str, *, current_revision: int | None = None) -> None:
        super().__init__(message)
        self.current_revision = current_revision


class VersionedCommandRegistry:

    def __init__(self, path: str | Path, *, audit_path: str | Path | None = None) -> None:
        self.path = Path(path)
        if audit_path is None:
            from nanobot.config.paths import get_robot_ai_dir

            self.audit_path = get_robot_ai_dir() / "audit.jsonl"
        else:
            self.audit_path = Path(os.path.expanduser(audit_path))
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {"schema_version": "2.0", "commands": {}, "pending_audits": []}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        sv = raw.get("schema_version") or raw.get("version")
        if sv != "2.0":
            raise ValueError(
                f"Expected schema_version 2.0, got {sv!r}. Run migrate_commands_schema_if_needed() first."
            )
        raw["schema_version"] = "2.0"
        raw.setdefault("pending_audits", [])
        self._data = raw

    def _save(self) -> None:
        self._data["updated_at"] = datetime.now().isoformat()
        atomic_write_json(self.path, self._data)

    def _commit_with_audit(
        self, action: str, actor: str, target: dict[str, Any], payload: dict[str, Any],
    ) -> str:
        """Append pending_audit + save atomically + drain. Returns audit_id."""
        import secrets
        audit_id = secrets.token_urlsafe(16)
        self._data["pending_audits"].append({
            "audit_id": audit_id, "action": action, "actor": actor,
            "target": target, "payload": payload, "timestamp": datetime.now().isoformat(),
        })
        self._save()
        self.drain_pending_audits()
        return audit_id

    def drain_pending_audits(self) -> list[str]:
        """Flush pending_audits to audit.jsonl. Idempotent (dedup by audit_id)."""
        from robot_ai.library.migration import _audit_append
        pending = self._data.get("pending_audits", [])
        if not pending:
            return []
        existing_ids: set[str] = set()
        if self.audit_path.exists():
            for line in self.audit_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    eid = entry.get("audit_id") or entry.get("migration_id")
                    if eid:
                        existing_ids.add(eid)
                except json.JSONDecodeError:
                    continue
        written: list[str] = []
        remaining: list[dict[str, Any]] = []
        for item in pending:
            aid = item.get("audit_id")
            if aid and aid in existing_ids:
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

    def create_entity(
        self, command_id: str, component_id: str, name: str,
        parameters: dict[str, Any], *, aliases: list[str] | None = None,
        description: str = "", actor: str = "engineer",
    ) -> dict[str, Any]:
        if command_id in self._data["commands"]:
            raise ValueError(f"Command '{command_id}' already exists.")
        now = datetime.now().isoformat()
        cleaned_aliases = [a.strip() for a in (aliases or []) if a and a.strip()]
        entity = {
            "command_id": command_id,
            "published_version": None,
            "versions": {},
            "draft": {
                "revision": 1, "base_version": None,
                "name": name, "aliases": cleaned_aliases, "description": description,
                "component_id": component_id, "parameters": parameters,
                "risk_level": "", "status": "draft", "version": 0,
                "source": "engineer", "created_by": actor,
                "created_at": now, "updated_at": now, "published_at": "",
            },
            "updated_at": now,
        }
        self._data["commands"][command_id] = entity
        self._commit_with_audit(
            "command_create", actor,
            {"command_id": command_id},
            {"name": name, "component_id": component_id, "aliases": cleaned_aliases},
        )
        return entity

    def get_entity(self, command_id: str) -> dict[str, Any] | None:
        return self._data["commands"].get(command_id)

    def list_summaries(self) -> list[dict[str, Any]]:
        result = []
        for cid in sorted(self._data["commands"]):
            e = self._data["commands"][cid]
            draft = e.get("draft")
            pv = e.get("published_version")
            pub_name = ""
            if pv is not None:
                pub_name = e["versions"].get(str(pv), {}).get("name", "")
            result.append({
                "command_id": e["command_id"],
                "name": (draft or {}).get("name") or pub_name or cid,
                "published_version": pv,
                "has_draft": draft is not None,
                "draft_revision": (draft or {}).get("revision"),
                "updated_at": e.get("updated_at", ""),
            })
        return result

    # -- draft / publish / archive --

    def update_draft(
        self, command_id: str, *, expected_revision: int,
        name: str, aliases: list[str], description: str,
        component_id: str, parameters: dict[str, Any],
        actor: str = "engineer",
    ) -> dict[str, Any]:
        entity = self.get_entity(command_id)
        if entity is None or entity.get("draft") is None:
            raise ValueError(f"No active draft for '{command_id}'.")
        draft = entity["draft"]
        if draft["revision"] != expected_revision:
            raise ConflictError(
                f"Draft revision mismatch: expected {expected_revision}, got {draft['revision']}",
                current_revision=draft["revision"],
            )
        if not name or not name.strip():
            raise ValueError("Draft name must not be empty.")
        draft["name"] = name
        draft["aliases"] = [a.strip() for a in aliases if a and a.strip()]
        draft["description"] = description
        draft["component_id"] = component_id
        draft["parameters"] = parameters
        draft["revision"] += 1
        now = datetime.now().isoformat()
        draft["updated_at"] = now
        entity["updated_at"] = now
        self._commit_with_audit(
            "draft_update", actor,
            {"command_id": command_id, "revision": draft["revision"]},
            {"before_revision": expected_revision, "after_revision": draft["revision"],
             "name": name, "component_id": component_id},
        )
        return entity

    def start_draft(self, command_id: str, *, actor: str = "engineer") -> dict[str, Any]:
        entity = self.get_entity(command_id)
        if entity is None:
            raise ValueError(f"Command '{command_id}' not found.")
        if entity.get("draft") is not None:
            raise ValueError(f"Command '{command_id}' already has an active draft.")
        pv = entity.get("published_version")
        if pv is None:
            raise ValueError(f"Command '{command_id}' has no published version to base a draft on.")
        base = entity["versions"][str(pv)]
        now = datetime.now().isoformat()
        entity["draft"] = {
            "revision": 1, "base_version": pv,
            "name": base["name"], "aliases": list(base.get("aliases", [])),
            "description": base.get("description", ""),
            "component_id": base["component_id"],
            "parameters": dict(base.get("parameters", {})),
            "risk_level": "", "status": "draft", "version": 0,
            "source": "engineer", "created_by": actor,
            "created_at": now, "updated_at": now, "published_at": "",
        }
        entity["updated_at"] = now
        self._commit_with_audit(
            "draft_start", actor,
            {"command_id": command_id, "base_version": pv},
            {"base_version": pv, "name": base["name"], "component_id": base["component_id"]},
        )
        return entity

    @staticmethod
    def _norm(s: str) -> str:
        return (s or "").strip().casefold()

    def _check_publish_namespace(self, command_id: str, name: str, aliases: list[str]) -> None:
        name_n = self._norm(name)
        if not name_n:
            raise ValueError("Command name must not be empty.")
        alias_ns: list[str] = []
        for a in aliases:
            an = self._norm(a)
            if not an:
                continue
            if an == name_n:
                raise ValueError("Alias conflicts with the command name.")
            if an in alias_ns:
                raise ValueError("Duplicate alias within draft.")
            alias_ns.append(an)
        for cid, entity in self._data["commands"].items():
            if cid == command_id:
                continue
            pv = entity.get("published_version")
            if pv is None:
                continue
            pub = entity["versions"][str(pv)]
            pub_name_n = self._norm(pub["name"])
            pub_alias_ns = {self._norm(a) for a in pub.get("aliases", [])}
            if name_n == pub_name_n or name_n in pub_alias_ns:
                raise ValueError(f"Name conflicts with published command '{cid}'.")
            for an in alias_ns:
                if an == pub_name_n or an in pub_alias_ns:
                    raise ValueError(f"Alias conflicts with published command '{cid}'.")

    def publish(self, command_id: str, *, component_risk_level: str, actor: str = "engineer") -> dict[str, Any]:
        entity = self.get_entity(command_id)
        if entity is None or entity.get("draft") is None:
            raise ValueError(f"No active draft for '{command_id}'.")
        draft = entity["draft"]
        self._check_publish_namespace(command_id, draft["name"], draft.get("aliases", []))
        pv = entity.get("published_version")
        next_v = (pv or 0) + 1
        now = datetime.now().isoformat()
        published = {
            "id": command_id,
            "name": draft["name"], "aliases": list(draft.get("aliases", [])),
            "description": draft.get("description", ""),
            "component_id": draft["component_id"],
            "parameters": dict(draft.get("parameters", {})),
            "risk_level": component_risk_level, "status": "published",
            "version": next_v, "source": "engineer", "created_by": actor,
            "created_at": draft.get("created_at", now), "updated_at": now, "published_at": now,
        }
        entity["versions"][str(next_v)] = published
        entity["published_version"] = next_v
        entity["draft"] = None
        entity["updated_at"] = now
        self._commit_with_audit(
            "command_publish", actor,
            {"command_id": command_id, "version": next_v},
            {"before_version": pv, "after_version": next_v},
        )
        return entity

    def archive(self, command_id: str, *, actor: str = "engineer") -> None:
        entity = self.get_entity(command_id)
        if entity is None:
            raise ValueError(f"Command '{command_id}' not found.")
        if entity.get("published_version") is not None:
            raise ConflictError(
                f"Cannot archive '{command_id}': has a published version. Published-command archive is B2."
            )
        draft_summary = entity.get("draft") or {}
        del self._data["commands"][command_id]
        self._commit_with_audit(
            "command_archive", actor,
            {"command_id": command_id},
            {"name": draft_summary.get("name", ""),
             "component_id": draft_summary.get("component_id", ""),
             "revision": draft_summary.get("revision"),
             "had_published_version": entity.get("published_version")},
        )
