"""CommandRegistry: atomic JSON persistence + global-namespace uniqueness.

Mirrors ``robot_ai.flow.registry`` structure (load/save/add/get/list) but for
commands, keyed by stable ``id``. Invariant: the global namespace — every
command's ``name`` and ``aliases`` — is unique (case-insensitive), so name/alias
queries are never ambiguous. ``add`` enforces it; migration pre-filters so it
never hits a rejection unexpectedly.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from robot_ai.library.models import Command, CommandStatus
from robot_ai.library.storage import atomic_write_json


class CommandRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._commands: dict[str, Command] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for item in payload.get("commands", []):
            cmd = Command.from_dict(dict(item))
            if cmd.id:
                self._commands[cmd.id] = cmd

    def _save(self) -> None:
        payload = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "commands": [c.to_dict() for c in self._sorted()],
        }
        atomic_write_json(self.path, payload)

    def _sorted(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.id)

    def namespace(self) -> set[str]:
        """All existing names + aliases, lowercased (the global namespace)."""
        seen: set[str] = set()
        for c in self._commands.values():
            seen.add(c.name.lower())
            for a in c.aliases:
                seen.add(a.lower())
        return seen

    def add(self, command: Command) -> tuple[bool, str]:
        cid = command.id
        if not cid:
            return False, "Command id must not be empty."
        if cid in self._commands:
            return False, f"Command '{cid}' already exists."
        name_l = command.name.lower()
        if not name_l:
            return False, "Command name must not be empty."
        ns = self.namespace()
        if name_l in ns:
            return False, f"Command name '{command.name}' conflicts with an existing name or alias."
        seen_in_this = {name_l}
        for alias in command.aliases:
            al = alias.lower()
            if not al:
                continue
            if al in ns or al in seen_in_this:
                return False, f"Alias '{alias}' conflicts with an existing name or alias."
            seen_in_this.add(al)
        now = datetime.now().isoformat()
        command.created_at = command.created_at or now
        command.updated_at = now
        if command.status == CommandStatus.PUBLISHED.value and not command.published_at:
            command.published_at = now
        self._commands[cid] = command
        self._save()
        return True, f"Command '{cid}' saved."

    def get(self, command_id: str) -> Command | None:
        return self._commands.get(command_id)

    def list_all(self) -> list[Command]:
        return self._sorted()

    def list(
        self,
        *,
        component_id: str | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> list[Command]:
        items = self._sorted()
        if component_id:
            items = [c for c in items if c.component_id == component_id]
        if risk_level:
            items = [c for c in items if c.risk_level == risk_level]
        if status:
            items = [c for c in items if c.status == status]
        if q:
            ql = q.lower()
            items = [
                c for c in items
                if ql in c.name.lower() or any(ql in a.lower() for a in c.aliases)
            ]
        return items
