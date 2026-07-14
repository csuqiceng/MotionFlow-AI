"""Versioned, JSON-backed registry for immutable published robot flows."""

from __future__ import annotations

import copy
import json
import math
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_ai.library.storage import atomic_write_json
from robot_ai.library.versioned_registry import ConflictError


class VersionedFlowRegistry:
    """Store one draft and immutable published versions for each flow."""

    def __init__(self, path: str | Path, *, audit_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.audit_path = Path(os.path.expanduser(audit_path or "~/.nanobot/robot_ai/audit.jsonl"))
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {"schema_version": "2.0", "flows": {}, "pending_audits": []}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        schema_version = raw.get("schema_version") or raw.get("version")
        if schema_version == "1.1":
            self._data = self._migrate_legacy_payload(raw)
            self._save()
            return
        if schema_version != "2.0":
            raise ValueError(f"Expected schema_version 2.0, got {schema_version!r}.")
        raw["schema_version"] = "2.0"
        raw.setdefault("flows", {})
        raw.setdefault("pending_audits", [])
        self._data = raw

    @staticmethod
    def _migrate_legacy_payload(raw: dict[str, Any]) -> dict[str, Any]:
        """Convert the pre-workbench list registry into immutable baseline versions.

        Legacy flows have no independent draft/version history.  Treat every
        readable legacy entry as version 1 so the existing runtime library
        continues to expose it, while future engineer edits start a new draft.
        """
        now = datetime.now().isoformat()
        flows: dict[str, dict[str, Any]] = {}
        for raw_flow in raw.get("flows", []):
            if not isinstance(raw_flow, dict):
                continue
            name = str(raw_flow.get("name", "")).strip()
            if not name:
                continue
            base_id = "_".join(name.lower().split()) or "legacy_flow"
            flow_id = base_id
            suffix = 2
            while flow_id in flows:
                flow_id = f"{base_id}_{suffix}"
                suffix += 1
            created_at = str(raw_flow.get("created_at") or now)
            updated_at = str(raw_flow.get("updated_at") or created_at)
            published = {
                "flow_id": flow_id,
                "name": name,
                "description": str(raw_flow.get("description", "")),
                "steps": copy.deepcopy(raw_flow.get("steps", [])),
                "step_delay_ms": raw_flow.get("step_delay_ms", 1000),
                "rehearsal_spd": raw_flow.get("rehearsal_spd", 20),
                "status": "published",
                "version": 1,
                "source": "legacy-import",
                "created_by": str(raw_flow.get("created_by", "operator")),
                "created_at": created_at,
                "updated_at": updated_at,
                "published_at": updated_at,
            }
            flows[flow_id] = {
                "flow_id": flow_id,
                "published_version": 1,
                "versions": {"1": published},
                "draft": None,
                "updated_at": updated_at,
            }
        return {"schema_version": "2.0", "flows": flows, "pending_audits": []}

    def _save(self) -> None:
        self._data["updated_at"] = datetime.now().isoformat()
        atomic_write_json(self.path, self._data)

    def _commit_with_audit(
        self, action: str, actor: str, target: dict[str, Any], payload: dict[str, Any]
    ) -> str:
        audit_id = secrets.token_urlsafe(16)
        self._data["pending_audits"].append(
            {
                "audit_id": audit_id,
                "action": action,
                "actor": actor,
                "target": target,
                "payload": payload,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self._save()
        self.drain_pending_audits()
        return audit_id

    def drain_pending_audits(self) -> list[str]:
        """Write undelivered audit records, deduplicating records already on disk."""
        from robot_ai.library.migration import _audit_append

        pending = self._data.get("pending_audits", [])
        if not pending:
            return []
        existing_ids: set[str] = set()
        if self.audit_path.exists():
            try:
                lines = self.audit_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
            for line in lines:
                try:
                    audit_id = json.loads(line).get("audit_id")
                except json.JSONDecodeError:
                    continue
                if audit_id:
                    existing_ids.add(audit_id)
        written: list[str] = []
        remaining: list[dict[str, Any]] = []
        for record in pending:
            audit_id = record.get("audit_id")
            if audit_id in existing_ids:
                continue
            try:
                _audit_append(self.audit_path, record)
                written.append(audit_id)
            except OSError:
                remaining.append(record)
        self._data["pending_audits"] = remaining
        if len(remaining) != len(pending):
            self._save()
        return written

    def get_entity(self, flow_id: str) -> dict[str, Any] | None:
        return self._data["flows"].get(flow_id)

    def create_entity(
        self,
        flow_id: str,
        name: str,
        steps: list[dict[str, Any]],
        *,
        step_delay_ms: float = 1000,
        rehearsal_spd: float = 20,
        description: str = "",
        actor: str = "engineer",
    ) -> dict[str, Any]:
        if flow_id in self._data["flows"]:
            raise ValueError(f"Flow '{flow_id}' already exists.")
        now = datetime.now().isoformat()
        entity = {
            "flow_id": flow_id,
            "published_version": None,
            "versions": {},
            "draft": {
                "revision": 1,
                "base_version": None,
                "name": name,
                "description": description,
                "steps": copy.deepcopy(steps),
                "step_delay_ms": step_delay_ms,
                "rehearsal_spd": rehearsal_spd,
                "status": "draft",
                "version": 0,
                "source": "engineer",
                "created_by": actor,
                "created_at": now,
                "updated_at": now,
                "published_at": "",
            },
            "updated_at": now,
        }
        self._data["flows"][flow_id] = entity
        self._commit_with_audit("flow_create", actor, {"flow_id": flow_id}, {"name": name})
        return entity

    def update_draft(
        self,
        flow_id: str,
        *,
        expected_revision: int,
        name: str,
        steps: list[dict[str, Any]],
        step_delay_ms: float,
        rehearsal_spd: float,
        description: str = "",
        actor: str = "engineer",
    ) -> dict[str, Any]:
        entity = self.get_entity(flow_id)
        if entity is None or entity.get("draft") is None:
            raise ValueError(f"No active draft for '{flow_id}'.")
        draft = entity["draft"]
        if draft["revision"] != expected_revision:
            raise ConflictError(
                f"Draft revision mismatch: expected {expected_revision}, got {draft['revision']}",
                current_revision=draft["revision"],
            )
        draft.update(
            {
                "name": name,
                "description": description,
                "steps": copy.deepcopy(steps),
                "step_delay_ms": step_delay_ms,
                "rehearsal_spd": rehearsal_spd,
                "revision": draft["revision"] + 1,
                "updated_at": datetime.now().isoformat(),
            }
        )
        entity["updated_at"] = draft["updated_at"]
        self._commit_with_audit(
            "flow_draft_update",
            actor,
            {"flow_id": flow_id, "revision": draft["revision"]},
            {"before_revision": expected_revision, "after_revision": draft["revision"]},
        )
        return entity

    def validate_draft(self, flow_id: str) -> list[str]:
        entity = self.get_entity(flow_id)
        if entity is None or entity.get("draft") is None:
            raise ValueError(f"No active draft for '{flow_id}'.")
        draft = entity["draft"]
        errors: list[str] = []
        if not str(draft.get("name", "")).strip():
            errors.append("Flow name must not be empty.")
        steps = draft.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append("Flow must contain at least one step.")
        else:
            if not all(isinstance(step, dict) for step in steps):
                errors.append("Every flow step must be a mapping.")
            elif any("step_id" not in step for step in steps):
                errors.append("Every flow step must include step_id.")
            else:
                step_ids = [step["step_id"] for step in steps]
                try:
                    unique_step_ids = set(step_ids)
                except TypeError:
                    errors.append("Every flow step_id must be hashable.")
                else:
                    if len(unique_step_ids) != len(step_ids):
                        errors.append("Flow step IDs must be unique.")
        delay = draft.get("step_delay_ms")
        if not self._is_finite_number(delay):
            errors.append("Step delay must be finite.")
        elif delay < 0:
            errors.append("Step delay must be nonnegative.")
        speed = draft.get("rehearsal_spd")
        if not self._is_finite_number(speed) or speed <= 0:
            errors.append("Rehearsal speed must be finite and positive.")
        return errors

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def start_draft(self, flow_id: str, *, actor: str = "engineer") -> dict[str, Any]:
        entity = self.get_entity(flow_id)
        if entity is None:
            raise ValueError(f"Flow '{flow_id}' not found.")
        if entity.get("draft") is not None:
            raise ValueError(f"Flow '{flow_id}' already has an active draft.")
        published_version = entity.get("published_version")
        if published_version is None:
            raise ValueError(f"Flow '{flow_id}' has no published version to base a draft on.")
        now = datetime.now().isoformat()
        draft = copy.deepcopy(entity["versions"][str(published_version)])
        draft.update(
            {
                "revision": 1,
                "base_version": published_version,
                "status": "draft",
                "version": 0,
                "created_by": actor,
                "created_at": now,
                "updated_at": now,
                "published_at": "",
            }
        )
        entity["draft"] = draft
        entity["updated_at"] = now
        self._commit_with_audit(
            "flow_draft_start", actor, {"flow_id": flow_id, "base_version": published_version}, {}
        )
        return entity

    def publish(self, flow_id: str, *, actor: str = "engineer") -> dict[str, Any]:
        entity = self.get_entity(flow_id)
        if entity is None or entity.get("draft") is None:
            raise ValueError(f"No active draft for '{flow_id}'.")
        errors = self.validate_draft(flow_id)
        if errors:
            raise ValueError("; ".join(errors))
        prior_version = entity.get("published_version")
        version = (prior_version or 0) + 1
        now = datetime.now().isoformat()
        published = copy.deepcopy(entity["draft"])
        published.update(
            {
                "flow_id": flow_id,
                "status": "published",
                "version": version,
                "updated_at": now,
                "published_at": now,
            }
        )
        published.pop("revision", None)
        published.pop("base_version", None)
        entity["versions"][str(version)] = published
        entity["published_version"] = version
        entity["draft"] = None
        entity["updated_at"] = now
        self._commit_with_audit(
            "flow_publish",
            actor,
            {"flow_id": flow_id, "version": version},
            {"before_version": prior_version, "after_version": version},
        )
        return entity

    def archive(self, flow_id: str, *, actor: str = "engineer") -> None:
        entity = self.get_entity(flow_id)
        if entity is None:
            raise ValueError(f"Flow '{flow_id}' not found.")
        if entity.get("published_version") is not None:
            raise ConflictError(f"Cannot archive '{flow_id}': it has a published version.")
        del self._data["flows"][flow_id]
        self._commit_with_audit("flow_archive", actor, {"flow_id": flow_id}, {})
