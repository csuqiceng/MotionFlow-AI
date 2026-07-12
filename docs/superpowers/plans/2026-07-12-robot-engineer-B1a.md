# Engineer B1a — Backend Implementation Plan (Tasks 1-5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Engineer command management backend — version-tree registry, draft/publish/archive with transactional outbox, pbkdf2 auth with CLI + config write-back, schema migration.

**Spec:** `docs/superpowers/specs/2026-07-12-robot-engineer-B1-design.md`

**No-git rule:** No `git add`/`commit`. Each task ends with verify-checkpoint.

**Test env:** `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest ...`

---

## Task 1: ComponentCatalog risk_level

**Files:**
- Modify: `robot_ai/library/models.py`
- Modify: `robot_ai/library/catalog.py`
- Test: `tests/robot_ai/test_component_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/robot_ai/test_component_catalog.py`:

```python
def test_each_component_has_risk_level() -> None:
    from robot_ai.library.catalog import ComponentCatalog
    catalog = ComponentCatalog()
    risks = {c.id: c.risk_level for c in catalog.list_all()}
    assert risks["system_action"] == "high"
    assert risks["linear_move"] == "high"
    assert risks["delay"] == "low"
    assert risks["io_write"] == "medium"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_component_catalog.py::test_each_component_has_risk_level -v`
Expected: FAIL `AttributeError`

- [ ] **Step 3: Add `risk_level` to Component**

In `robot_ai/library/models.py`, change the `Component` dataclass:

```python
@dataclass
class Component:
    id: str
    func_num: int
    name: str
    parameters: list[ParameterField] = field(default_factory=list)
    required_safety_state: str = ""
    flow_eligible: bool = True
    risk_level: str = "medium"
    description: str = ""

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "Component":
        return cls(
            id=str(p.get("id", "")),
            func_num=int(p.get("func_num", 0)),
            name=str(p.get("name", "")),
            parameters=[ParameterField.from_dict(dict(x)) for x in p.get("parameters", [])],
            required_safety_state=str(p.get("required_safety_state", "")),
            flow_eligible=bool(p.get("flow_eligible", True)),
            risk_level=str(p.get("risk_level", "medium")),
            description=str(p.get("description", "")),
        )
```

In `robot_ai/library/catalog.py`, add `risk_level=` to each factory:

```python
# _system_action: add  risk_level="high",
# _linear_move:   add  risk_level="high",
# _delay:         add  risk_level="low",
# _io_write:      add  risk_level="medium",
```

(Insert `risk_level="..."` before `description=` in each `Component(...)` call. Keep all `parameters=[...]` unchanged.)

- [ ] **Step 4: Run + checkpoint**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_component_catalog.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/models.py robot_ai/library/catalog.py`
Expected: all pass; ruff clean.

---

## Task 2: VersionedCommandRegistry — storage + create + get + list_summaries

**Files:**
- Create: `robot_ai/library/versioned_registry.py`
- Test: `tests/robot_ai/test_versioned_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/robot_ai/test_versioned_registry.py
from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.versioned_registry import VersionedCommandRegistry


def _reg(tmp_path: Path) -> VersionedCommandRegistry:
    return VersionedCommandRegistry(
        tmp_path / "commands.json",
        audit_path=tmp_path / "audit.jsonl",
    )


def test_create_entity_with_draft(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    entity = reg.create_entity("pick-place", "linear_move", "Pick & Place", {"target_x": 100.0})
    assert entity["command_id"] == "pick-place"
    assert entity["published_version"] is None
    assert entity["draft"]["revision"] == 1
    assert entity["draft"]["name"] == "Pick & Place"


def test_get_entity(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    assert reg.get_entity("home") is not None
    assert reg.get_entity("missing") is None


def test_list_summaries_excludes_version_tree(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    summaries = reg.list_summaries()
    assert len(summaries) == 1
    assert summaries[0]["command_id"] == "home"
    assert "versions" not in summaries[0]
    assert "draft" not in summaries[0]


def test_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    VersionedCommandRegistry(path, audit_path=tmp_path / "audit.jsonl").create_entity(
        "home", "linear_move", "Home", {})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2.0"
    assert "pending_audits" in payload
    reloaded = VersionedCommandRegistry(path, audit_path=tmp_path / "audit.jsonl")
    assert reloaded.get_entity("home") is not None
```

- [ ] **Step 2: Run to verify fail**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_versioned_registry.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement VersionedCommandRegistry (storage + create + get + list)**

```python
# robot_ai/library/versioned_registry.py
"""Versioned command registry (schema 2.0).

Stores logical command entities with immutable published versions + a single
editable draft + a root ``pending_audits`` outbox for all command state changes (create/draft/publish/archive).
Replaces the A1 single-record CommandRegistry for engineer write operations.
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
        self.audit_path = Path(os.path.expanduser(audit_path or "~/.nanobot/robot_ai/audit.jsonl"))
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
                continue  # already in audit.jsonl → remove from outbox (drop)
            try:
                _audit_append(self.audit_path, item)
                written.append(aid)
            except OSError:
                remaining.append(item)  # append failed → keep for retry
        self._data["pending_audits"] = remaining
        if len(remaining) != len(pending):
            self._save()
        return written

    # -- entity CRUD --

    def create_entity(
        self, command_id: str, component_id: str, name: str,
        parameters: dict[str, Any], *, aliases: list[str] | None = None,
        description: str = "", actor: str = "engineer",
    ) -> dict[str, Any]:
        if command_id in self._data["commands"]:
            raise ValueError(f"Command '{command_id}' already exists.")
        now = datetime.now().isoformat()
        entity = {
            "command_id": command_id,
            "published_version": None,
            "versions": {},
            "draft": {
                "revision": 1, "base_version": None,
                "name": name, "aliases": [a.strip() for a in (aliases or []) if a and a.strip()], "description": description,
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
            {"name": name, "component_id": component_id, "aliases": entity["draft"]["aliases"]},
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

    # -- draft / publish / archive — implemented in Task 3 --
```

- [ ] **Step 4: Run + checkpoint**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_versioned_registry.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/versioned_registry.py`
Expected: 4 PASS; ruff clean.

---

## Task 3: Draft update + start_draft + publish (namespace + outbox) + archive

**Files:**
- Modify: `robot_ai/library/versioned_registry.py`
- Test: `tests/robot_ai/test_versioned_registry.py` (extend)

- [ ] **Step 1: Write the failing tests (append)**

```python
import json as _json

from robot_ai.library.versioned_registry import ConflictError


# -- _commit_with_audit ordering: state → pending same atomic_write → drain → remove/keep --

def test_commit_writes_audit_and_drains(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    lines = [ln for ln in reg.audit_path.read_text("utf-8").splitlines() if ln.strip()]
    assert any(_json.loads(ln)["action"] == "command_create" for ln in lines)
    assert reg._data["pending_audits"] == []


def test_commit_drain_failure_keeps_pending(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    reg.audit_path = blocker / "audit.jsonl"
    reg.create_entity("home", "linear_move", "Home", {})
    assert reg.get_entity("home") is not None  # state changed
    assert len(reg._data["pending_audits"]) == 1  # drain failed → retained
    reg.audit_path = tmp_path / "audit.jsonl"
    written = reg.drain_pending_audits()
    assert len(written) == 1
    assert reg._data["pending_audits"] == []


def test_commit_crash_recovery_disk_level(tmp_path: Path) -> None:
    """Audit already written, outbox not removed → reload from DISK → drain removes."""
    from robot_ai.library.versioned_registry import VersionedCommandRegistry
    path = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    reg = VersionedCommandRegistry(path, audit_path=audit)
    reg.create_entity("home", "linear_move", "Home", {})
    # simulate crash: re-add the audit_id to pending in the FILE
    last = _json.loads(audit.read_text("utf-8").strip().splitlines()[-1])
    reg._data["pending_audits"].append({**last})
    reg._save()
    # reload from DISK — should see the stale pending
    reg2 = VersionedCommandRegistry(path, audit_path=audit)
    assert len(reg2._data["pending_audits"]) == 1
    # drain — audit_id already in audit.jsonl → remove without re-appending
    written = reg2.drain_pending_audits()
    assert written == []
    assert reg2._data["pending_audits"] == []
    # reload again — clean, audit not duplicated
    reg3 = VersionedCommandRegistry(path, audit_path=audit)
    assert reg3._data["pending_audits"] == []
    lines = [ln for ln in audit.read_text("utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1


# -- update_draft (full replacement) --

def test_update_draft_full_replacement(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 0.0})
    reg.update_draft("home", expected_revision=1, name="Home v2", aliases=["go"],
        description="d", component_id="linear_move", parameters={"target_x": 100.0})
    d = reg.get_entity("home")["draft"]
    assert d["revision"] == 2 and d["name"] == "Home v2" and d["aliases"] == ["go"]


def test_update_draft_stale_revision(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    try:
        reg.update_draft("home", expected_revision=99, name="X", aliases=[],
            description="", component_id="linear_move", parameters={})
        assert False
    except ConflictError as e:
        assert e.current_revision == 1


def test_update_draft_missing_field_rejected(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    try:
        reg.update_draft("home", expected_revision=1, name="X")  # missing required fields
        assert False
    except TypeError:
        pass


# -- start_draft --

def test_start_draft_from_published(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 100.0})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    d = reg.get_entity("home")["draft"]
    assert d["base_version"] == 1 and d["parameters"]["target_x"] == 100.0


def test_start_draft_already_exists(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    try:
        reg.start_draft("home")
        assert False
    except ValueError:
        pass


# -- publish (immutable + id + self-exclusion) --

def test_publish_immutable_with_id(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.publish("home", component_risk_level="high")
    v1 = reg.get_entity("home")["versions"]["1"]
    assert v1["status"] == "published" and v1["id"] == "home" and v1["risk_level"] == "high"
    assert reg.get_entity("home")["draft"] is None


def test_publish_v2_v1_immutable(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 100.0})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    reg.update_draft("home", expected_revision=1, name="Home", aliases=[],
        description="", component_id="linear_move", parameters={"target_x": 200.0})
    reg.publish("home", component_risk_level="high")
    e = reg.get_entity("home")
    assert e["versions"]["1"]["parameters"]["target_x"] == 100.0
    assert e["versions"]["2"]["parameters"]["target_x"] == 200.0
    assert e["versions"]["2"]["id"] == "home"


def test_publish_self_namespace_ok(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    reg.publish("home", component_risk_level="high")
    assert reg.get_entity("home")["published_version"] == 2


# -- namespace conflict matrix --

def _assert_conflict(reg, cid: str) -> None:
    try:
        reg.publish(cid, component_risk_level="high")
        assert False, f"Should conflict"
    except ValueError:
        pass


def test_ns_name_vs_name(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Home", {})
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "linear_move", "Home", {})
    _assert_conflict(reg, "b")


def test_ns_name_vs_alias(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["gohome"])
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "linear_move", "GoHome", {})
    _assert_conflict(reg, "b")


def test_ns_alias_vs_name(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Rest", {})
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "io_write", "Other", {}, aliases=["rest"])
    _assert_conflict(reg, "b")


def test_ns_alias_vs_alias(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["stop"])
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "io_write", "Bravo", {}, aliases=["stop"])
    _assert_conflict(reg, "b")


def test_ns_empty_name_rejected(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "", {})
    try:
        reg.publish("a", component_risk_level="high")
        assert False
    except ValueError as e:
        assert "empty" in str(e).lower()


# -- archive (draft-only) --

def test_archive_draft_only(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.archive("home")
    assert reg.get_entity("home") is None
    reg.create_entity("io", "io_write", "IO", {})
    reg.publish("io", component_risk_level="medium")
    try:
        reg.archive("io")
        assert False
    except ConflictError:
        pass


# -- all state changes audited via outbox --

def test_all_state_changes_audited(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    reg.update_draft("home", expected_revision=1, name="Home v2", aliases=[],
        description="", component_id="linear_move", parameters={})
    reg.publish("home", component_risk_level="high")
    reg.create_entity("tmp", "delay", "Temp", {})
    reg.archive("tmp")
    actions = [_json.loads(ln)["action"]
               for ln in reg.audit_path.read_text("utf-8").splitlines() if ln.strip()]
    assert "command_create" in actions
    assert "command_publish" in actions
    assert "draft_start" in actions
    assert "draft_update" in actions
    assert "command_archive" in actions


# -- namespace: whitespace evasion + within-draft --

def test_ns_whitespace_evasion(tmp_path: Path) -> None:
    """Alias ' home ' (spaces) conflicts with published 'Home' via strip+casefold."""
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Home", {})
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "io_write", "Other", {}, aliases=[" home "])
    _assert_conflict(reg, "b")


def test_ns_within_draft_alias_dup(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["x", "x"])
    try:
        reg.publish("a", component_risk_level="high")
        assert False
    except ValueError:
        pass


def test_ns_within_draft_alias_equals_name(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Home", {}, aliases=["Home"])
    try:
        reg.publish("a", component_risk_level="high")
        assert False
    except ValueError:
        pass


def test_blank_aliases_stripped_on_create(tmp_path: Path) -> None:
    """Blank/whitespace-only aliases are stripped + discarded, not persisted."""
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["valid", "", "  "])
    assert reg.get_entity("a")["draft"]["aliases"] == ["valid"]


# -- outbox persistence (disk-level crash recovery) --

def test_commit_drain_failure_persists_to_disk(tmp_path: Path) -> None:
    """Drain failure persists pending to DISK; reload sees it; retry clears + audit unique."""
    from robot_ai.library.versioned_registry import VersionedCommandRegistry
    path = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    VersionedCommandRegistry(path, audit_path=blocker / "audit.jsonl").create_entity(
        "home", "linear_move", "Home", {})
    # reload from DISK — pending must be persisted (not just in-memory)
    reg2 = VersionedCommandRegistry(path, audit_path=blocker / "audit.jsonl")
    assert len(reg2._data["pending_audits"]) == 1
    # fix audit path + drain
    reg2.audit_path = audit
    written = reg2.drain_pending_audits()
    assert len(written) == 1
    # reload again — pending cleared, audit has exactly 1 entry (not duplicated)
    reg3 = VersionedCommandRegistry(path, audit_path=audit)
    assert reg3._data["pending_audits"] == []
    lines = [ln for ln in audit.read_text("utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
```

- [ ] **Step 2: Run to verify fail**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_versioned_registry.py -q`
Expected: FAIL — methods not implemented (run full file, no -k filter, so ALL new tests red).

- [ ] **Step 3: Implement update_draft, start_draft, publish, archive**

Replace the `# -- draft / publish / archive — implemented in Task 3 --` comment in `versioned_registry.py` with:

```python
    def update_draft(
        self, command_id: str, *, expected_revision: int,
        name: str, aliases: list[str], description: str,
        component_id: str, parameters: dict[str, Any],
        actor: str = "engineer",
    ) -> dict[str, Any]:
        """Full-replacement draft update. All content fields required; server-
        controlled fields (risk_level/version/status/timestamps) NOT accepted."""
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
        """Create a new draft from the current published version."""
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
        """Unified normalization: strip + casefold for all name/alias comparisons."""
        return (s or "").strip().casefold()

    def _check_publish_namespace(self, command_id: str, name: str, aliases: list[str]) -> None:
        """Reject name/aliases conflicting with OTHER published commands (exclude
        self). Also rejects empty name, within-draft alias duplicates, alias=name
        self-conflict. All comparisons use strip().casefold() — blocks whitespace
        evasion like ' home ' vs 'Home'."""
        name_n = self._norm(name)
        if not name_n:
            raise ValueError("Command name must not be empty.")
        alias_ns: list[str] = []
        for a in aliases:
            an = self._norm(a)
            if not an:
                continue  # skip blank aliases
            if an == name_n:
                raise ValueError(f"Alias '{a}' conflicts with the command name.")
            if an in alias_ns:
                raise ValueError(f"Duplicate alias '{a}' within draft.")
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
                raise ValueError(f"Name '{name}' conflicts with published command '{cid}'.")
            for an in alias_ns:
                if an == pub_name_n or an in pub_alias_ns:
                    raise ValueError(f"Alias conflicts with published command '{cid}'.")

    def publish(self, command_id: str, *, component_risk_level: str, actor: str = "engineer") -> dict[str, Any]:
        """Validate namespace + publish draft → immutable version N+1 + outbox audit."""
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
        """Archive. B1: only if no published version (draft-only)."""
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
```

- [ ] **Step 4: Run + checkpoint**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_versioned_registry.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/versioned_registry.py`
Expected: all pass; ruff clean.

---

## Task 4: Schema migration 1.0→2.0 + startup order

**Files:**
- Modify: `robot_ai/library/migration.py`
- Modify: `nanobot/cli/commands.py`
- Test: `tests/robot_ai/test_library_migration.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/robot_ai/test_library_migration.py`:

```python
def test_migrate_schema_1_to_2(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    commands.write_text(json.dumps({
        "version": "1.0", "updated_at": "2026-07-11T00:00:00",
        "commands": [
            {"id": "home", "name": "home", "component_id": "linear_move", "parameters": {},
             "aliases": [], "description": "", "risk_level": "high", "status": "published",
             "version": 1, "source": "legacy-import", "created_by": "system:migration",
             "created_at": "", "updated_at": "", "published_at": ""},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    from robot_ai.library.migration import migrate_commands_schema_if_needed
    migrated = migrate_commands_schema_if_needed(str(commands))
    assert migrated is True
    data = json.loads(commands.read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.0"
    assert "home" in data["commands"]
    assert data["commands"]["home"]["published_version"] == 1
    assert "1" in data["commands"]["home"]["versions"]
    assert data["commands"]["home"]["draft"] is None
    assert data["pending_audits"] == []


def test_migrate_schema_already_2_is_noop(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    commands.write_text(json.dumps({
        "schema_version": "2.0", "commands": {}, "pending_audits": [],
    }, ensure_ascii=False), encoding="utf-8")
    from robot_ai.library.migration import migrate_commands_schema_if_needed
    assert migrate_commands_schema_if_needed(str(commands)) is False


def test_migrate_schema_missing_file_is_noop(tmp_path: Path) -> None:
    from robot_ai.library.migration import migrate_commands_schema_if_needed
    assert migrate_commands_schema_if_needed(str(tmp_path / "nonexistent.json")) is False


def test_migrate_schema_unknown_version_raises(tmp_path: Path) -> None:
    """Unknown schema version → ValueError, original data preserved (not overwritten)."""
    commands = tmp_path / "commands.json"
    commands.write_text(json.dumps({
        "schema_version": "9.9", "commands": [],
    }, ensure_ascii=False), encoding="utf-8")
    from robot_ai.library.migration import migrate_commands_schema_if_needed
    try:
        migrate_commands_schema_if_needed(str(commands))
        assert False, "Should raise ValueError"
    except ValueError:
        pass
    # data preserved — not silently overwritten
    data = json.loads(commands.read_text(encoding="utf-8"))
    assert data["schema_version"] == "9.9"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_library_migration.py -q`
Expected: FAIL — `ImportError: cannot import name 'migrate_commands_schema_if_needed'` (full file, all tests red).

- [ ] **Step 3: Implement migrate_commands_schema_if_needed**

Append to `robot_ai/library/migration.py`:

```python
def migrate_commands_schema_if_needed(commands_path: str | Path | None = None) -> bool:
    """Migrate commands.json from schema 1.0 (A1 list) to 2.0 (version tree).

    Idempotent: already 2.0 or file missing → no-op.
    Called at gateway startup AFTER seed_command_library_if_missing (seed→migrate order).
    Returns True if migrated, False if skipped.
    """
    from robot_ai.library.storage import atomic_write_json

    cpath = Path(os.path.expanduser(commands_path or DEFAULT_COMMANDS_PATH))
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
```

- [ ] **Step 4: Run migration function tests + ruff**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_library_migration.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/migration.py`
Expected: all pass (incl. 4 schema tests); ruff clean.

- [ ] **Step 5: Add `initialize_robot_libraries` startup helper + wire `_run_gateway` + test**

Append to `robot_ai/library/migration.py`:

```python
def initialize_robot_libraries(
    commands_path: str | Path | None = None,
    audit_path: str | Path | None = None,
) -> None:
    """Startup sequence: seed → migrate → drain. Idempotent + crash-recovery.

    Called once at gateway startup (``_run_gateway``). On first install:
    seed creates schema 1.0 → migrate converts to 2.0 → drain flushes any
    pending outbox from a prior crash.
    """
    import os
    from robot_ai.library.versioned_registry import VersionedCommandRegistry

    cpath = os.path.expanduser(commands_path or DEFAULT_COMMANDS_PATH)
    apath = os.path.expanduser(audit_path or DEFAULT_AUDIT_PATH)
    seed_command_library_if_missing(commands_path=cpath, audit_path=apath)
    migrate_commands_schema_if_needed(cpath)
    VersionedCommandRegistry(cpath, audit_path=apath).drain_pending_audits()
```

In `_run_gateway` (`nanobot/cli/commands.py`), replace the existing `seed_command_library_if_missing()` call (and its import) with:

```python
    from robot_ai.library.migration import initialize_robot_libraries
    initialize_robot_libraries()
```

Append to `tests/robot_ai/test_library_migration.py`:

```python
def test_startup_sequence_drain_is_called(tmp_path: Path) -> None:
    """First install: seed → migrate → drain CALLED (spy). Second call: all no-op."""
    from unittest.mock import patch
    from robot_ai.library.migration import initialize_robot_libraries
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    with patch(
        "robot_ai.library.versioned_registry.VersionedCommandRegistry.drain_pending_audits",
        return_value=[],
    ) as mock_drain:
        initialize_robot_libraries(str(commands), str(audit))
        assert mock_drain.call_count == 1  # drain WAS called
    data = json.loads(commands.read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.0"
    assert len(data["commands"]) == 16
    # second call: already 2.0 → all no-op
    initialize_robot_libraries(str(commands), str(audit))
    data2 = json.loads(commands.read_text(encoding="utf-8"))
    assert len(data2["commands"]) == 16
```

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_library_migration.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/migration.py nanobot/cli/commands.py`
Expected: all pass (incl. startup sequence test); ruff clean.

---

## Task 5: pbkdf2 auth helpers + config schema + CLI set-password

**Files:**
- Create: `robot_ai/library/auth.py`
- Modify: `nanobot/config/schema.py`
- Modify: `nanobot/cli/commands.py` (add engineer_app)
- Modify: `nanobot/config/loader.py` (add save_config_atomic)
- Test: `tests/robot_ai/test_engineer_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/robot_ai/test_engineer_auth.py
from __future__ import annotations

from robot_ai.library.auth import (
    hash_password, verify_password, extract_iterations, EngineerTokenStore,
)


def test_hash_and_verify() -> None:
    h = hash_password("secret123", iterations=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_format_round_trips() -> None:
    h = hash_password("pw", iterations=5000)
    parts = h.split("$")
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) == 5000
    assert len(parts) == 4


def test_extract_iterations() -> None:
    h = hash_password("pw", iterations=3000)
    assert extract_iterations(h) == 3000
    assert extract_iterations("garbage") == 0


def test_token_store_issue_check_revoke() -> None:
    store = EngineerTokenStore(ttl_seconds=3600)
    token = store.issue()
    assert store.check(token) is True
    store.revoke(token)
    assert store.check(token) is False


def test_token_store_rejects_unknown() -> None:
    store = EngineerTokenStore()
    assert store.check("bogus") is False


def test_config_schema_engineer_section() -> None:
    from nanobot.config.schema import Config
    cfg = Config()
    assert hasattr(cfg, "robot_ai")
    assert hasattr(cfg.robot_ai, "engineer")
    assert cfg.robot_ai.engineer.password_hash == ""
    assert cfg.robot_ai.engineer.pbkdf2_iterations == 200_000


def test_engineer_password_config_round_trip(tmp_path: Path) -> None:
    """hash → save_config → reload → verify (no plaintext in file)."""
    from robot_ai.library.auth import hash_password, verify_password
    from nanobot.config.schema import Config
    from nanobot.config.loader import save_config, load_config
    cfg_path = tmp_path / "config.json"
    pw = "test-secret-123"
    cfg = Config()
    cfg.robot_ai.engineer.password_hash = hash_password(pw, iterations=1000)
    save_config(cfg, cfg_path)
    raw = cfg_path.read_text(encoding="utf-8")
    assert "test-secret-123" not in raw  # no plaintext
    assert "pbkdf2_sha256" in raw
    cfg2 = load_config(cfg_path)
    assert verify_password(pw, cfg2.robot_ai.engineer.password_hash) is True
    assert verify_password("wrong", cfg2.robot_ai.engineer.password_hash) is False


def test_cli_set_password_match(tmp_path: Path) -> None:
    """CliRunner + mock getpass: matching passwords → exit 0, hash in config, no plaintext."""
    from typer.testing import CliRunner
    from unittest.mock import patch
    from nanobot.cli.commands import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["mypw123", "mypw123"]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 0
    raw = cfg.read_text(encoding="utf-8")
    assert "mypw123" not in raw
    assert "pbkdf2_sha256" in raw
    # reload + verify_password
    from nanobot.config.loader import load_config
    from robot_ai.library.auth import verify_password
    cfg2 = load_config(cfg)
    assert verify_password("mypw123", cfg2.robot_ai.engineer.password_hash) is True


def test_cli_set_password_mismatch(tmp_path: Path) -> None:
    """Mismatched passwords → exit 1, config not written."""
    from typer.testing import CliRunner
    from unittest.mock import patch
    from nanobot.cli.commands import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["pw1", "pw2"]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 1
    assert not cfg.exists()  # config not written


def test_cli_set_password_empty(tmp_path: Path) -> None:
    """Empty password → exit 1, config not written."""
    from typer.testing import CliRunner
    from unittest.mock import patch
    from nanobot.cli.commands import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["", ""]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 1
    assert not cfg.exists()  # config not written


def test_cli_output_no_password(tmp_path: Path) -> None:
    """CLI output must not contain the password."""
    from typer.testing import CliRunner
    from unittest.mock import patch
    from nanobot.cli.commands import engineer_app
    cfg = tmp_path / "config.json"
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["secret-pw-99", "secret-pw-99"]):
        result = runner.invoke(engineer_app, ["set-password", "--config", str(cfg)])
    assert result.exit_code == 0  # command succeeded
    assert "secret-pw-99" not in result.output


def test_config_schema_engineer_from_dict() -> None:
    from nanobot.config.schema import Config
    cfg = Config.model_validate({
        "robot_ai": {"engineer": {"password_hash": "pbkdf2_sha256$200000$abc$def", "pbkdf2_iterations": 200_000}},
    })
    assert cfg.robot_ai.engineer.password_hash == "pbkdf2_sha256$200000$abc$def"
    assert cfg.robot_ai.engineer.pbkdf2_iterations == 200_000


def test_pbkdf2_iterations_below_minimum_rejected() -> None:
    """pbkdf2_iterations < 100_000 (incl 0, negative) → ValidationError."""
    from pydantic import ValidationError
    from nanobot.config.schema import EngineerConfig
    for bad in [0, -1, 99_999]:
        try:
            EngineerConfig(pbkdf2_iterations=bad)
            assert False, f"Should reject iterations={bad}"
        except ValidationError:
            pass
```

- [ ] **Step 2: Run to verify fail**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_auth.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement auth.py**

```python
# robot_ai/library/auth.py
"""Engineer authentication: pbkdf2 password hashing + in-memory session tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

DEFAULT_ITERATIONS = 200_000


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2])
        stored_dk = base64.b64decode(parts[3])
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, stored_dk)
    except Exception:
        return False


def extract_iterations(stored_hash: str) -> int:
    try:
        return int(stored_hash.split("$")[1])
    except (IndexError, ValueError):
        return 0


@dataclass
class EngineerTokenStore:
    ttl_seconds: int = 8 * 3600
    _tokens: dict[str, float] = field(default_factory=dict)

    def issue(self) -> str:
        self._purge()
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.monotonic() + self.ttl_seconds
        return token

    def check(self, token: str) -> bool:
        self._purge()
        expiry = self._tokens.get(token)
        if expiry is None or time.monotonic() > expiry:
            self._tokens.pop(token, None)
            return False
        return True

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)

    def _purge(self) -> None:
        now = time.monotonic()
        for key in list(self._tokens):
            if now > self._tokens[key]:
                del self._tokens[key]
```

- [ ] **Step 4: Add config schema**

In `nanobot/config/schema.py`, add two new Pydantic model classes (place before the root `Config` class):

```python
class EngineerConfig(Base):
    """Engineer authentication configuration."""
    password_hash: str = Field(default="", validation_alias=AliasChoices("passwordHash", "password_hash"))
    pbkdf2_iterations: int = Field(
        default=200_000,
        validation_alias=AliasChoices("pbkdf2Iterations", "pbkdf2_iterations"),
        ge=100_000,
    )


class RobotAiConfig(Base):
    """Robot AI subsystem configuration."""
    engineer: EngineerConfig = Field(default_factory=EngineerConfig)
```

Then in the root `Config` class (the `Config(BaseSettings)` class), add:

```python
    robot_ai: RobotAiConfig = Field(
        default_factory=RobotAiConfig,
        validation_alias=AliasChoices("robot_ai", "robotAi"),
    )
```

Also add `save_config_atomic` to `nanobot/config/loader.py`:

```python
def save_config_atomic(config: Config, config_path: Path | None = None) -> None:
    """Save config atomically (temp + fsync + replace). For engineer password writes."""
    from robot_ai.library.storage import atomic_write_json
    path = config_path or get_config_path()
    data = config.model_dump(mode="json", by_alias=True)
    if config.providers.openai_codex.proxy is not None:
        data.setdefault("providers", {})["openaiCodex"] = {
            "proxy": config.providers.openai_codex.proxy,
        }
    atomic_write_json(path, data)
```

- [ ] **Step 5: Add CLI set-password command**

In `nanobot/cli/commands.py`, add `import getpass` to the **top-level imports** (before `app = typer.Typer(...)`), then add:

```python
engineer_app = typer.Typer(help="Engineer account management.")
app.add_typer(engineer_app, name="engineer")


@engineer_app.command("set-password")
def engineer_set_password(
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Set the engineer password (hidden input, hashed with pbkdf2)."""
    from robot_ai.library.auth import hash_password
    from nanobot.config.loader import load_config, save_config_atomic
    from nanobot.config.paths import get_config_path
    from pathlib import Path as _Path

    config_path = _Path(config).expanduser().resolve() if config else get_config_path()
    cfg = load_config(config_path)
    pw = getpass.getpass("Enter engineer password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw != pw2:
        console.print("[red]Passwords do not match.[/red]")
        raise typer.Exit(1)
    if not pw:
        console.print("[red]Password must not be empty.[/red]")
        raise typer.Exit(1)
    iterations = cfg.robot_ai.engineer.pbkdf2_iterations
    cfg.robot_ai.engineer.password_hash = hash_password(pw, iterations=iterations)
    save_config_atomic(cfg, config_path)
    console.print(f"[green]Engineer password set (pbkdf2_sha256, {iterations} iterations).[/green]")
```

- [ ] **Step 6: Run + checkpoint**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_auth.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/auth.py nanobot/config/schema.py nanobot/config/loader.py nanobot/cli/commands.py`
Expected: all pass; ruff clean.

---

## Self-Review (Tasks 1-5)

**Spec coverage:**
- §3 ComponentCatalog risk_level → Task 1.
- §2 version tree storage + create/get/list → Task 2.
- §2 draft + optimistic concurrency + start_draft → Task 3.
- §8 publish (namespace-excluding-self + immutable N+1 + outbox) → Task 3.
- §8 archive (draft-only, 409) → Task 3.
- §8 drain (idempotent via audit_id) → Task 3.
- §4 migration 1.0→2.0 + startup order seed→migrate → Task 4.
- §5 pbkdf2 (hash/verify/extract_iterations) → Task 5.
- §5 config schema (EngineerConfig + RobotAiConfig) → Task 5.
- §5 CLI set-password (getpass, no plaintext arg) → Task 5.
- §5 EngineerTokenStore (issue/check/revoke/purge) → Task 5.

**Remaining for Tasks 6-9 (next segment):**
- §5 login process function (throttle 429 + fail-closed audit + PBKDF2 server-side upgrade via config write-back).
- §5 logout process function.
- §6-7 API endpoints (commands CRUD + draft/start + publish + archive + audit pagination composite cursor).
- §6 ws_http mount (GET + body-header + engineer-token gate + no-store headers).
- §6 access-log no-body-header (confirmed by Explore — already safe).
- A2 read API update (process_robot_library_commands projects published_version from schema 2.0).
- Final verification.

**Bug fixes from review:**
- `self._data` (not `reg._data`) ✓ — publish uses `self._data`.
- drain logic ✓ — `aid in existing_ids` → `continue` (drop); else try append → success: written; fail: remaining.
- namespace excluding self ✓ — `_check_publish_namespace` skips `cid == command_id`.
- start_draft implemented + tested ✓.
- function name unified `migrate_commands_schema_if_needed` ✓.
- config schema full Pydantic code ✓.
- CLI full typer code (getpass, hash, save_config) ✓.
- PBKDF2 upgrade: handled in Task 6 (login process function — server-side config write-back, NOT returned to client).
