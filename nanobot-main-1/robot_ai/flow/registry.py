"""Named-flow registry with JSON persistence.

Ported from the legacy Qt project (``robot_modbus_lite/flow_registry.py``)
with two adaptations:
- the legacy ``PermissionService`` dependency is dropped (this project has no
  permission service yet; add a gate later if needed);
- persistence is atomic (temp file + ``os.replace``) to match the durability
  pattern used elsewhere in this project.

Lookup is case-insensitive. Confirmed flows can only be edited by bumping a
draft version (``create_draft=True``), matching the legacy behaviour.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_ai.flow.models import VALID_TRANSITIONS, FlowEntry, FlowState, FlowStep


class FlowRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._flows: dict[str, FlowEntry] = {}
        self._load()

    @staticmethod
    def _key(name: str) -> str:
        return str(name or "").strip().lower()

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for item in payload.get("flows", []):
            flow = FlowEntry.from_dict(dict(item))
            if flow.name:
                self._flows[self._key(flow.name)] = flow

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "1.1",
            "updated_at": datetime.now().isoformat(),
            "flows": [flow.to_dict() for flow in self._sorted_flows()],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        # Atomic write: stage in a temp file in the same directory, then rename.
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as staging:
            staging.write(text)
            staging.flush()
            os.fsync(staging.fileno())
            tmp_name = staging.name
        os.replace(tmp_name, self.path)

    def _sorted_flows(self) -> list[FlowEntry]:
        return sorted(self._flows.values(), key=lambda item: item.name)

    def add(self, entry: FlowEntry) -> tuple[bool, str]:
        key = self._key(entry.name)
        if not key:
            return False, "Flow name must not be empty."
        if key in self._flows:
            return False, f"Flow '{entry.name}' already exists."
        now = datetime.now().isoformat()
        entry.created_at = entry.created_at or now
        entry.updated_at = now
        self._flows[key] = entry
        self._save()
        return True, f"Flow '{entry.name}' saved."

    def update(
        self,
        name: str,
        *,
        create_draft: bool = False,
        **kwargs: Any,
    ) -> tuple[bool, str]:
        flow = self.get(name)
        if flow is None:
            return False, f"Flow '{name}' does not exist."
        if flow.confirmed and not create_draft:
            return False, f"Flow '{flow.name}' is confirmed; edit requires a draft version."
        if flow.confirmed and create_draft:
            flow.confirmed = False
            flow.version += 1
            flow.state = FlowState.IDLE.value
        for key in ("description", "steps", "step_delay_ms", "rehearsal_spd"):
            if key in kwargs:
                value = kwargs[key]
                if key == "steps":
                    value = [
                        step if isinstance(step, FlowStep) else FlowStep.from_dict(dict(step))
                        for step in value
                    ]
                setattr(flow, key, value)
        flow.updated_at = datetime.now().isoformat()
        self._save()
        return True, f"Flow '{flow.name}' updated."

    def remove(self, name: str) -> tuple[bool, str]:
        key = self._key(name)
        if key not in self._flows:
            return False, f"Flow '{name}' does not exist."
        del self._flows[key]
        self._save()
        return True, f"Flow '{name}' deleted."

    def confirm(self, name: str) -> tuple[bool, str]:
        flow = self.get(name)
        if flow is None:
            return False, f"Flow '{name}' does not exist."
        flow.confirmed = True
        flow.state = FlowState.READY.value
        flow.updated_at = datetime.now().isoformat()
        self._save()
        return True, f"Flow '{flow.name}' confirmed."

    def transition(self, name: str, target: FlowState) -> bool:
        flow = self.get(name)
        if flow is None:
            return False
        current = FlowState(flow.state)
        if target not in VALID_TRANSITIONS[current]:
            return False
        flow.state = target.value
        flow.updated_at = datetime.now().isoformat()
        self._save()
        return True

    def get(self, name: str) -> FlowEntry | None:
        return self._flows.get(self._key(name))

    def list_all(self) -> list[FlowEntry]:
        return self._sorted_flows()
