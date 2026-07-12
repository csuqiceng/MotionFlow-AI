# Robot Library A1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the A1 backend slice — a local robot command/component knowledge library (Python models, atomic CommandRegistry, read-only ComponentCatalog, legacy migration with audit, and read-only `/api/robot/library/*` endpoints) — purely backend, independently testable.

**Architecture:** New `robot_ai/library/` subpackage (models / catalog / registry / migration / storage) mirrors the existing `robot_ai/flow/` dataclass + atomic-write patterns but does **not** touch FlowRegistry. Read-only HTTP endpoints are added as `process_robot_library_*` functions in `nanobot/api/robot_routes.py` and mounted through the gateway dispatcher `ws_http._dispatch_robot_routes` so they inherit the existing central `check_api_token` gate. Migration is a standalone `tools/migrate_robot_commands.py` CLI mirroring `tools/migrate_robot_flows.py`.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, pytest (`asyncio_mode=auto`), ruff (E/F/I/N/W, E501 ignored).

**Spec:** `docs/superpowers/specs/2026-07-11-robot-library-A1-design.md`

**No-git rule (user-standing):** This plan contains **no `git add`/`git commit` steps**. Each task ends with a **Verify & checkpoint** step that runs the relevant tests + (final task) `ruff`. The user commits everything unified later. TDD discipline (failing test → implement → passing test) is preserved.

**Working directory note:** All shell commands assume cwd = `nanobot-main-1/` (the package root containing `robot_ai/`, `nanobot/`, `tools/`, `tests/`). Each command prefixes `cd nanobot-main-1 &&` because the session root is the repo parent.

**Test env note:** Use the project venv Python — `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest ...`. The base system Python lacks `aiohttp` / `pytest-asyncio` (optional `[api]` extras), so any test importing `nanobot.api.robot_routes` or `nanobot.webui.ws_http` MUST run under `.venv-robot-desktop`. Pure-`robot_ai.library` tests run under either, but use the venv for consistency.

---

## File Structure

**Create (new):**
- `robot_ai/library/__init__.py` — package exports
- `robot_ai/library/storage.py` — `atomic_write_json(path, payload)` (independent of FlowRegistry)
- `robot_ai/library/models.py` — `RiskLevel`, `CommandStatus`, `ParameterField`, `Component`, `Command`, `AuditEntry`, `normalize_id()`
- `robot_ai/library/catalog.py` — `ComponentCatalog` (4 built-in components, read-only, in-memory)
- `robot_ai/library/registry.py` — `CommandRegistry` (atomic persist, global-namespace uniqueness, query)
- `robot_ai/library/migration.py` — `migrate_commands()` + `MigrationResult` + audit dedup/backfill
- `tools/migrate_robot_commands.py` — CLI (mirrors `migrate_robot_flows.py`)
- `tests/robot_ai/test_library_storage.py`
- `tests/robot_ai/test_library_models.py`
- `tests/robot_ai/test_component_catalog.py`
- `tests/robot_ai/test_command_registry.py`
- `tests/robot_ai/test_library_migration.py`
- `tests/robot_ai/test_robot_library_routes.py`
- `tests/robot_ai/test_ws_http_library_routes.py`

**Modify (existing):**
- `nanobot/api/robot_routes.py` — add `DEFAULT_COMMANDS_PATH`, 4 `process_robot_library_*`, 4 `handle_robot_library_*`, register routes, extend `__all__`
- `nanobot/webui/ws_http.py` — add `_dispatch_robot_library_routes()` method + call it at the top of `_dispatch_robot_routes()`

**Do NOT touch:** `App.tsx`, `RobotOperatorApp.tsx`, any file under `webui/src/`, `robot_ai/flow/` (FlowRegistry), `data/legacy/query_table.json`.

---

## Task 1: `atomic_write_json` storage helper

**Files:**
- Create: `robot_ai/library/storage.py`
- Test: `tests/robot_ai/test_library_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/robot_ai/test_library_storage.py
from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.storage import atomic_write_json


def test_atomic_write_json_creates_and_reads_back(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"version": "1.0", "items": [1, 2, 3]})
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"version": "1.0", "items": [1, 2, 3]}


def test_atomic_write_json_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


def test_atomic_write_json_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"x": True})
    leftover = [p.name for p in tmp_path.iterdir() if p.name.startswith(".out.json")]
    assert leftover == []


def test_atomic_write_json_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "out.json"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robot_ai.library'`

- [ ] **Step 3: Write minimal implementation**

```python
# robot_ai/library/storage.py
"""Atomic JSON write helper for the robot library.

Independent of ``robot_ai.flow.registry`` (which has its own inline copy) so
A1 does not disturb the working flow persistence. temp file + fsync +
``os.replace`` — the same durability pattern, shared here for the library.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: str | Path, payload: Any) -> None:
    """Write ``payload`` as JSON to ``path`` atomically.

    Stages the text in a temp file in the same directory, fsyncs it, then
    ``os.replace``-moves it onto the target so a crash mid-write never leaves a
    truncated file. Parent directories are created on demand.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as staging:
        staging.write(text)
        staging.flush()
        os.fsync(staging.fileno())
        tmp_name = staging.name
    os.replace(tmp_name, target)
```

```python
# robot_ai/library/__init__.py
"""Robot command/component knowledge library (A1 backend slice)."""

from __future__ import annotations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_storage.py -v`
Expected: 4 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_storage.py -q`
Expected: `4 passed`. No git commit (user commits unified later).

---

## Task 2: Data models (`models.py`)

**Files:**
- Create: `robot_ai/library/models.py`
- Test: `tests/robot_ai/test_library_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/robot_ai/test_library_models.py
from __future__ import annotations

from robot_ai.library.models import (
    AuditEntry,
    Command,
    CommandStatus,
    Component,
    ParameterField,
    RiskLevel,
    normalize_id,
)


def test_enums_have_expected_values() -> None:
    assert RiskLevel.HIGH.value == "high"
    assert CommandStatus.PUBLISHED.value == "published"
    assert {r.value for r in RiskLevel} == {"low", "medium", "high", "critical"}
    assert {s.value for s in CommandStatus} == {"draft", "published", "archived"}


def test_command_round_trip_preserves_fields() -> None:
    cmd = Command(
        id="io0-off",
        name="IO0关闭",
        component_id="io_write",
        parameters={"io_no": 0, "io_action": 0},
        aliases=["IO0", "关闭"],
        description="set Y0 off",
        risk_level="high",
        status="published",
        version=1,
        source="legacy-import",
        created_by="system:migration",
    )
    restored = Command.from_dict(cmd.to_dict())
    assert restored == cmd


def test_command_defaults_version_one_and_published() -> None:
    cmd = Command(id="x", name="X", component_id="delay")
    assert cmd.version == 1
    assert cmd.status == "published"
    assert cmd.risk_level == "high"


def test_component_round_trip_with_parameter_fields() -> None:
    comp = Component(
        id="delay",
        func_num=110,
        name="延时",
        parameters=[ParameterField(name="delay_sec", type="float", unit="sec", minimum=0)],
        flow_eligible=True,
    )
    restored = Component.from_dict(comp.to_dict())
    assert restored == comp
    assert restored.parameters[0].name == "delay_sec"
    assert restored.parameters[0].required is True


def test_audit_entry_round_trip_with_migration_id() -> None:
    entry = AuditEntry(
        action="legacy_import",
        actor="system:migration",
        timestamp="2026-07-11T00:00:00",
        migration_id="legacy-import:abcd",
        after={"migrated": 16, "skipped": 5},
    )
    restored = AuditEntry.from_dict(entry.to_dict())
    assert restored.migration_id == "legacy-import:abcd"
    assert restored.after == {"migrated": 16, "skipped": 5}


def test_normalize_id_lowercases_and_collapses_whitespace() -> None:
    assert normalize_id("IO0关闭") == "io0关闭"
    assert normalize_id("  a   b ") == "a-b"
    assert normalize_id("Home") == "home"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robot_ai.library.models'`

- [ ] **Step 3: Write minimal implementation**

```python
# robot_ai/library/models.py
"""Robot library data models: enums, ParameterField, Component, Command, AuditEntry.

Pure data (dataclasses + from_dict/to_dict), mirroring ``robot_ai.flow.models``.
No ZMotion / Qt / permission deps. ``version`` is a forward-compatible field
(A1 stores only the single current record per command; version history is
deferred to phase B).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CommandStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


def normalize_id(name: str) -> str:
    """Stable id derived from a name: strip + lowercase + collapse whitespace to '-'."""
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return s


@dataclass
class ParameterField:
    name: str
    type: str  # "int" | "float" | "str" | "bool"
    unit: str = ""
    minimum: Any = None
    maximum: Any = None
    default: Any = None
    required: bool = True
    description: str = ""

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "ParameterField":
        return cls(
            name=str(p.get("name", "")),
            type=str(p.get("type", "str")),
            unit=str(p.get("unit", "")),
            minimum=p.get("minimum"),
            maximum=p.get("maximum"),
            default=p.get("default"),
            required=bool(p.get("required", True)),
            description=str(p.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Component:
    id: str
    func_num: int
    name: str
    parameters: list[ParameterField] = field(default_factory=list)
    required_safety_state: str = ""
    flow_eligible: bool = True
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
            description=str(p.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Command:
    id: str
    name: str
    component_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    risk_level: str = RiskLevel.HIGH.value
    status: str = CommandStatus.PUBLISHED.value
    version: int = 1
    source: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    published_at: str = ""

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "Command":
        return cls(
            id=str(p.get("id", "")),
            name=str(p.get("name", "")),
            component_id=str(p.get("component_id", "")),
            parameters=dict(p.get("parameters", {})),
            aliases=[str(a) for a in p.get("aliases", [])],
            description=str(p.get("description", "")),
            risk_level=str(p.get("risk_level", RiskLevel.HIGH.value)),
            status=str(p.get("status", CommandStatus.PUBLISHED.value)),
            version=int(p.get("version", 1)),
            source=str(p.get("source", "")),
            created_by=str(p.get("created_by", "")),
            created_at=str(p.get("created_at", "")),
            updated_at=str(p.get("updated_at", "")),
            published_at=str(p.get("published_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEntry:
    action: str
    actor: str
    timestamp: str
    target: dict[str, Any] | None = None
    migration_id: str | None = None
    before: Any = None
    after: Any = None

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "AuditEntry":
        return cls(
            action=str(p.get("action", "")),
            actor=str(p.get("actor", "")),
            timestamp=str(p.get("timestamp", "")),
            target=p.get("target"),
            migration_id=p.get("migration_id"),
            before=p.get("before"),
            after=p.get("after"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_models.py -v`
Expected: 6 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_models.py -q`
Expected: `6 passed`. No git commit.

---

## Task 3: `ComponentCatalog` (4 built-in components)

**Files:**
- Create: `robot_ai/library/catalog.py`
- Test: `tests/robot_ai/test_component_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/robot_ai/test_component_catalog.py
from __future__ import annotations

from robot_ai.library.catalog import ComponentCatalog


def test_catalog_has_four_built_in_components() -> None:
    catalog = ComponentCatalog()
    ids = {c.id for c in catalog.list_all()}
    assert ids == {"system_action", "linear_move", "delay", "io_write"}


def test_catalog_get_found_and_missing() -> None:
    catalog = ComponentCatalog()
    assert catalog.get("linear_move") is not None
    assert catalog.get("nope") is None


def test_func_to_id_maps_allowlist_only() -> None:
    catalog = ComponentCatalog()
    assert catalog.func_to_id(104) == "system_action"
    assert catalog.func_to_id(108) == "linear_move"
    assert catalog.func_to_id(110) == "delay"
    assert catalog.func_to_id(120) == "io_write"
    assert catalog.func_to_id(106) is None  # joint — not in v1
    assert catalog.func_to_id(107) is None
    assert catalog.func_to_id(109) is None
    assert catalog.func_to_id(11) is None


def test_linear_move_schema_has_expected_fields() -> None:
    catalog = ComponentCatalog()
    comp = catalog.get("linear_move")
    names = {pf.name for pf in comp.parameters}
    assert {"target_x", "target_y", "target_z", "target_rx", "target_ry", "target_rz"}.issubset(names)
    assert {"spd_pct", "acc_pct", "dec_pct", "move_type"}.issubset(names)


def test_system_action_schema_has_control_fields() -> None:
    catalog = ComponentCatalog()
    names = {pf.name for pf in catalog.get("system_action").parameters}
    assert names == {"stop_mode", "estop_ctrl", "pause_ctrl", "cancel_ctrl", "reset_ctrl"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_component_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robot_ai.library.catalog'`

- [ ] **Step 3: Write minimal implementation**

```python
# robot_ai/library/catalog.py
"""Read-only catalog of platform-controlled components (4 built-in).

Components are NOT engineer-editable (design §4.2), so the catalog is pure
in-memory dataclasses — no ``components.json`` persistence in A1.
"""

from __future__ import annotations

from robot_ai.library.models import Component, ParameterField


def _system_action() -> Component:
    return Component(
        id="system_action",
        func_num=104,
        name="系统动作",
        description="Func104 safety/control bits (estop/pause/cancel/reset).",
        required_safety_state="operator_only",
        parameters=[
            ParameterField("stop_mode", "int", minimum=0, maximum=1),
            ParameterField("estop_ctrl", "int", minimum=0, maximum=2),
            ParameterField("pause_ctrl", "int", minimum=0, maximum=2),
            ParameterField("cancel_ctrl", "int", minimum=0, maximum=2),
            ParameterField("reset_ctrl", "int", minimum=0, maximum=1),
        ],
    )


def _linear_move() -> Component:
    return Component(
        id="linear_move",
        func_num=108,
        name="直线/位姿移动",
        description="Func108 linear/pose move to a 6-DOF target.",
        parameters=[
            ParameterField("target_x", "float", unit="mm"),
            ParameterField("target_y", "float", unit="mm"),
            ParameterField("target_z", "float", unit="mm"),
            ParameterField("target_rx", "float", unit="deg"),
            ParameterField("target_ry", "float", unit="deg"),
            ParameterField("target_rz", "float", unit="deg"),
            ParameterField("spd_pct", "float", unit="%", minimum=0, maximum=100),
            ParameterField("acc_pct", "float", unit="%", minimum=0, maximum=100),
            ParameterField("dec_pct", "float", unit="%", minimum=0, maximum=100),
            ParameterField("move_type", "int", minimum=0, maximum=1),
            ParameterField("stop_cmd", "int", minimum=0, maximum=1),
            ParameterField("fuzzy_pos", "int", minimum=0, maximum=1, required=False, default=0),
            ParameterField("fuzzy_spd", "int", minimum=0, maximum=1, required=False, default=0),
            ParameterField("fuzzy_acc", "int", minimum=0, maximum=1, required=False, default=0),
            ParameterField("fuzzy_dec", "int", minimum=0, maximum=1, required=False, default=0),
        ],
    )


def _delay() -> Component:
    return Component(
        id="delay",
        func_num=110,
        name="延时",
        description="Func110 delay (can run parallel to motion).",
        parameters=[ParameterField("delay_sec", "float", unit="sec", minimum=0)],
    )


def _io_write() -> Component:
    return Component(
        id="io_write",
        func_num=120,
        name="IO 写",
        description="Func120 set a digital output.",
        parameters=[
            ParameterField("io_no", "int", minimum=0),
            ParameterField("io_action", "int", minimum=0, maximum=1),
        ],
    )


class ComponentCatalog:
    """In-memory, read-only catalog of the 4 v1 components."""

    def __init__(self) -> None:
        self._components: dict[str, Component] = {}
        for factory in (_system_action, _linear_move, _delay, _io_write):
            comp = factory()
            self._components[comp.id] = comp

    def list_all(self) -> list[Component]:
        return sorted(self._components.values(), key=lambda c: c.id)

    def get(self, component_id: str) -> Component | None:
        return self._components.get(component_id)

    def func_to_id(self, func_num: int) -> str | None:
        for comp in self._components.values():
            if comp.func_num == func_num:
                return comp.id
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_component_catalog.py -v`
Expected: 5 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_component_catalog.py -q`
Expected: `5 passed`. No git commit.

---

## Task 4: `CommandRegistry` (atomic persist + global-namespace uniqueness)

**Files:**
- Create: `robot_ai/library/registry.py`
- Test: `tests/robot_ai/test_command_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/robot_ai/test_command_registry.py
from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.models import Command
from robot_ai.library.registry import CommandRegistry


def _cmd(cid: str = "io0-off", name: str = "IO0关闭", aliases: list[str] | None = None) -> Command:
    return Command(id=cid, name=name, component_id="io_write", aliases=aliases or [])


def test_add_get_list(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    ok, _ = reg.add(_cmd("io0-off", "IO0关闭", ["IO0"]))
    assert ok is True
    assert reg.get("io0-off").name == "IO0关闭"
    assert reg.get("missing") is None
    assert [c.id for c in reg.list_all()] == ["io0-off"]


def test_add_rejects_duplicate_id(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    assert reg.add(_cmd("io0-off", "IO0关闭"))[0] is True
    assert reg.add(_cmd("io0-off", "Other"))[0] is False


def test_add_rejects_name_conflicting_with_existing_alias(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("a", "Alpha", aliases=["al"]))
    # "al" is an alias of Alpha; a new command named "al" must be rejected.
    assert reg.add(_cmd("b", "al"))[0] is False


def test_add_rejects_alias_conflicting_with_existing_name(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("a", "Alpha"))
    # "alpha" collides with the existing command name (case-insensitive).
    assert reg.add(_cmd("b", "Bravo", aliases=["alpha"]))[0] is False


def test_add_rejects_alias_conflicting_with_existing_alias(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("a", "Alpha", aliases=["shared"]))
    assert reg.add(_cmd("b", "Bravo", aliases=["shared"]))[0] is False


def test_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    reg = CommandRegistry(path)
    reg.add(_cmd("io0-off", "IO0关闭"))
    reg.add(_cmd("home", "home"))

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == "1.0"
    assert [c["id"] for c in payload["commands"]] == ["home", "io0-off"]  # sorted

    reloaded = CommandRegistry(path)
    assert [c.id for c in reloaded.list_all()] == ["home", "io0-off"]


def test_idempotent_add_does_not_duplicate_or_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    reg = CommandRegistry(path)
    reg.add(_cmd("io0-off", "IO0关闭", ["IO0"]))
    before = path.read_text(encoding="utf-8")

    # Re-adding the same id is rejected (no-op for migration to skip on).
    assert reg.add(_cmd("io0-off", "Overwrite"))[0] is False
    assert path.read_text(encoding="utf-8") == before  # file unchanged


def test_list_filters(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("io0-off", "IO0关闭", aliases=["grip"], ))
    reg.add(Command(id="home", name="home", component_id="linear_move", aliases=["回零"]))
    io_only = reg.list(component_id="io_write")
    assert [c.id for c in io_only] == ["io0-off"]
    by_q = reg.list(q="回零")
    assert [c.id for c in by_q] == ["home"]
    assert reg.list(q="grip")[0].id == "io0-off"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_command_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robot_ai.library.registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# robot_ai/library/registry.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_command_registry.py -v`
Expected: 8 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_command_registry.py -q`
Expected: `8 passed`. No git commit.

---

## Task 5: Legacy migration + audit (with failure/backfill semantics)

**Files:**
- Create: `robot_ai/library/migration.py`
- Test: `tests/robot_ai/test_library_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/robot_ai/test_library_migration.py
from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.migration import migrate_commands
from robot_ai.library.registry import CommandRegistry

# Path to the real legacy file: tests/robot_ai/ -> parents[2] = nanobot-main-1
REAL_LEGACY = Path(__file__).resolve().parents[2] / "data" / "legacy" / "query_table.json"


def _legacy(src_dir: Path, records: list[dict]) -> None:
    (src_dir / "query_table.json").write_text(
        json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8"
    )


def test_migrate_real_legacy_file_16_migrated_5_skipped(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    result = migrate_commands(REAL_LEGACY, commands, audit)

    assert len(result.migrated) == 16
    assert len(result.skipped) == 5
    skipped_funcs = sorted(func for func, _name, _reason in result.skipped)
    assert skipped_funcs == [11, 106, 106, 107, 109]  # 106 appears twice (J1到10度 + J2回正)
    assert result.audit_written is True
    assert result.audit_error is None

    reg = CommandRegistry(commands)
    assert len(reg.list_all()) == 16
    # spot-check one of each mapped component
    assert any(c.component_id == "io_write" for c in reg.list_all())
    assert any(c.component_id == "linear_move" for c in reg.list_all())
    assert any(c.component_id == "system_action" for c in reg.list_all())
    assert any(c.component_id == "delay" for c in reg.list_all())


def test_migrate_audit_record_has_migration_id_and_summary(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    result = migrate_commands(REAL_LEGACY, commands, audit)

    lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "legacy_import"
    assert entry["migration_id"] == result.migration_id
    assert entry["migration_id"].startswith("legacy-import:")
    assert entry["after"]["migrated"] == 16
    assert entry["after"]["skipped"] == 5
    assert entry["after"]["skipped_by_func"]["106"] == 2


def test_migrate_is_idempotent_rerun_is_noop(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    first = migrate_commands(REAL_LEGACY, commands, audit)
    second = migrate_commands(REAL_LEGACY, commands, audit)

    assert second.migration_id == first.migration_id
    assert second.migrated == []  # nothing new — idempotent
    # Unmappable records are re-evaluated and skipped on every run (stateless);
    # the key idempotency guarantees are: no new commands + no duplicate audit.
    assert len(second.skipped) == 5
    # audit NOT duplicated (dedup by migration_id)
    lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert second.audit_written is True


def test_migrate_skips_unmapped_and_reports_reasons(tmp_path: Path) -> None:
    src = tmp_path / "legacy"
    src.mkdir()
    _legacy(src, [
        {"query_key": "IO0打开", "func_num": 120, "keywords": "IO0 打开",
         "description": "on", "safety_level": 5, "params": {"io_no": 0, "io_action": 1}},
        {"query_key": "J1到10度", "func_num": 106, "keywords": "J1",
         "description": "joint", "safety_level": 5,
         "params": {"axis_no": 0, "pos_val": 10.0}},
    ])
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    result = migrate_commands(src / "query_table.json", commands, audit)

    assert len(result.migrated) == 1
    assert len(result.skipped) == 1
    func, name, reason = result.skipped[0]
    assert func == 106
    assert "joint" in reason


def test_migrate_failure_semantics_commands_written_audit_missing(tmp_path: Path) -> None:
    src = tmp_path / "legacy"
    src.mkdir()
    _legacy(src, [
        {"query_key": "IO0打开", "func_num": 120, "keywords": "IO0",
         "description": "on", "safety_level": 5, "params": {"io_no": 0, "io_action": 1}},
    ])
    commands = tmp_path / "commands.json"
    # Make audit path unwritable: parent is a regular file, not a directory.
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file", encoding="utf-8")
    audit = blocker / "audit.jsonl"

    result = migrate_commands(src / "query_table.json", commands, audit)
    # Commands were written...
    assert len(result.migrated) == 1
    assert CommandRegistry(commands).get("io0打开") is not None
    # ...but audit failed.
    assert result.audit_written is False
    assert result.audit_error is not None

    # Re-run against a writable audit path: backfills audit, no dup commands.
    good_audit = tmp_path / "audit.jsonl"
    result2 = migrate_commands(src / "query_table.json", commands, good_audit)
    assert result2.migrated == []  # idempotent — command already there
    assert result2.audit_written is True
    lines = [ln for ln in good_audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_migration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robot_ai.library.migration'`

- [ ] **Step 3: Write minimal implementation**

```python
# robot_ai/library/migration.py
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

from robot_ai.library.catalog import ComponentCatalog
from robot_ai.library.models import Command, RiskLevel, normalize_id
from robot_ai.library.registry import CommandRegistry

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_migration.py -v`
Expected: 5 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_migration.py -q`
Expected: `5 passed`. No git commit.

---

## Task 6: Migration CLI (`tools/migrate_robot_commands.py`)

**Files:**
- Create: `tools/migrate_robot_commands.py`
- Test: covered by Task 5 (logic) + a thin CLI smoke test added to `tests/robot_ai/test_library_migration.py`

- [ ] **Step 1: Write the failing test (CLI smoke)**

Append to `tests/robot_ai/test_library_migration.py`:

```python
def test_cli_runs_via_env_overrides(tmp_path: Path, monkeypatch) -> None:
    import importlib

    out_dir = tmp_path / "library_out"
    monkeypatch.setenv("ROBOT_LEGACY_DATA_DIR", str(REAL_LEGACY.parent))
    monkeypatch.setenv("ROBOT_LEGACY_QUERY_TABLE", str(REAL_LEGACY.name))
    monkeypatch.setenv("ROBOT_LIBRARY_OUT_DIR", str(out_dir))

    import tools.migrate_robot_commands as cli

    importlib.reload(cli)
    rc = cli.main()
    assert rc == 0
    assert (out_dir / "commands.json").exists()
    assert (out_dir / "audit.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_migration.py::test_cli_runs_via_env_overrides -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.migrate_robot_commands'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/migrate_robot_commands.py
"""Migrate legacy ``query_table.json`` into the robot command library.

Mirrors ``tools/migrate_robot_flows.py``. Reads the legacy file (default
``data/legacy/query_table.json``) and writes ``commands.json`` + ``audit.jsonl``
under ``~/.nanobot/robot_ai/`` (override both with env vars for tests / custom
installs). Idempotent and audit-deduped — safe to re-run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.library.migration import migrate_commands  # noqa: E402

LEGACY_DIR = Path(os.environ.get("ROBOT_LEGACY_DATA_DIR", r"data/legacy"))
LEGACY_FILE = Path(os.environ.get("ROBOT_LEGACY_QUERY_TABLE", "query_table.json"))
LEGACY = LEGACY_DIR / LEGACY_FILE
OUT_DIR = Path(os.environ.get("ROBOT_LIBRARY_OUT_DIR", str(Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai")))
COMMANDS_OUT = OUT_DIR / "commands.json"
AUDIT_OUT = OUT_DIR / "audit.jsonl"


def main() -> int:
    result = migrate_commands(LEGACY, COMMANDS_OUT, AUDIT_OUT)
    print(f"Migration id: {result.migration_id}")
    print(f"Migrated {len(result.migrated)} commands:")
    for cid, name in result.migrated:
        print(f"  + {cid}  {name}")
    print(f"Skipped {len(result.skipped)} records:")
    for func, name, reason in result.skipped:
        print(f"  - func={func}  {name}  ({reason})")
    if result.dropped_aliases:
        print(f"Dropped {result.dropped_aliases} conflicting aliases.")
    if result.audit_error:
        print(f"ERROR: commands written but audit write failed: {result.audit_error}")
        print("Re-run to backfill the audit record.")
        return 1
    if result.audit_already_present:
        state = "skipped (already present)"
    else:
        state = "written"
    print(f"Audit: {state} -> {AUDIT_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_migration.py -v`
Expected: 6 PASS (5 prior + 1 CLI smoke)

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_library_migration.py -q`
Expected: `6 passed`. No git commit.

---

## Task 7: Read-only library API (`robot_routes.py`)

**Files:**
- Modify: `nanobot/api/robot_routes.py` (add constants + 4 `process_*` + 4 `handle_*` + register + `__all__`)
- Test: `tests/robot_ai/test_robot_library_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/robot_ai/test_robot_library_routes.py
from __future__ import annotations

from pathlib import Path

from nanobot.api.robot_routes import (
    process_robot_library_command,
    process_robot_library_commands,
    process_robot_library_component,
    process_robot_library_components,
)
from robot_ai.library.models import Command
from robot_ai.library.registry import CommandRegistry


def _seed(path: Path) -> None:
    reg = CommandRegistry(path)
    reg.add(Command(id="io0-off", name="IO0关闭", component_id="io_write",
                    aliases=["grip"], parameters={"io_no": 0, "io_action": 0}))
    reg.add(Command(id="home", name="home", component_id="linear_move",
                    parameters={"target_x": 1400.0, "target_y": 0.0, "target_z": 1270.0,
                                "target_rx": 0.0, "target_ry": 90.0, "target_rz": 0.0,
                                "spd_pct": 50.0, "acc_pct": 60.0, "dec_pct": 60.0,
                                "move_type": 0, "stop_cmd": 0}))


def test_list_commands_envelope_and_total(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    status, result = process_robot_library_commands(commands_path=str(commands))
    assert status == 200
    assert result["ok"] is True
    assert result["data"]["total"] == 2
    assert {c["id"] for c in result["data"]["items"]} == {"io0-off", "home"}


def test_list_commands_filter_by_component(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    _status, result = process_robot_library_commands(
        commands_path=str(commands), component_id="io_write"
    )
    assert [c["id"] for c in result["data"]["items"]] == ["io0-off"]


def test_list_commands_filter_by_q_matches_alias(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    _status, result = process_robot_library_commands(commands_path=str(commands), q="grip")
    assert [c["id"] for c in result["data"]["items"]] == ["io0-off"]


def test_list_commands_rejects_bad_risk_level(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    status, result = process_robot_library_commands(
        commands_path=str(commands), risk_level="extreme"
    )
    assert status == 400
    assert result["error"]["code"] == 400


def test_get_command_found_and_404(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    s_ok, r_ok = process_robot_library_command("home", commands_path=str(commands))
    assert s_ok == 200 and r_ok["data"]["id"] == "home"
    s_miss, r_miss = process_robot_library_command("nope", commands_path=str(commands))
    assert s_miss == 404 and r_miss["error"]["code"] == 404


def test_list_components_has_four() -> None:
    status, result = process_robot_library_components()
    assert status == 200
    assert {c["id"] for c in result["data"]["items"]} == {
        "system_action", "linear_move", "delay", "io_write"
    }


def test_get_component_includes_schema_and_404() -> None:
    s_ok, r_ok = process_robot_library_component("delay")
    assert s_ok == 200
    assert any(p["name"] == "delay_sec" for p in r_ok["data"]["parameters"])
    s_miss, r_miss = process_robot_library_component("nope")
    assert s_miss == 404 and r_miss["error"]["code"] == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_robot_library_routes.py -v`
Expected: FAIL with `ImportError: cannot import name 'process_robot_library_commands'`

- [ ] **Step 3: Write minimal implementation**

In `nanobot/api/robot_routes.py`, add the library imports alongside the existing `robot_ai.execution` import (after line 30):

```python
from robot_ai.library.catalog import ComponentCatalog
from robot_ai.library.models import CommandStatus, RiskLevel
from robot_ai.library.registry import CommandRegistry
```

Add the constants + validator set near `DEFAULT_FLOW_REGISTRY_PATH` (after line 46):

```python
DEFAULT_COMMANDS_PATH = "~/.nanobot/robot_ai/commands.json"

_VALID_RISK_LEVELS = frozenset(r.value for r in RiskLevel)
_VALID_COMMAND_STATUSES = frozenset(s.value for s in CommandStatus)
```

Add the four `process_*` functions immediately after `process_robot_status` (after line 383):

```python
def _resolve_commands_path(path: str | None) -> str:
    import os

    return os.path.expanduser(path or DEFAULT_COMMANDS_PATH)


def process_robot_library_commands(
    *,
    commands_path: str | None = None,
    component_id: str | None = None,
    risk_level: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/commands`` (read-only list)."""
    if risk_level is not None and risk_level not in _VALID_RISK_LEVELS:
        return 400, {"error": {"message": f"Invalid risk_level: {risk_level!r}",
                               "type": "invalid_request_error", "code": 400}}
    if status is not None and status not in _VALID_COMMAND_STATUSES:
        return 400, {"error": {"message": f"Invalid status: {status!r}",
                               "type": "invalid_request_error", "code": 400}}
    registry = CommandRegistry(_resolve_commands_path(commands_path))
    items = registry.list(component_id=component_id, risk_level=risk_level, status=status, q=q)
    return 200, {"ok": True, "data": {"items": [c.to_dict() for c in items], "total": len(items)}}


def process_robot_library_command(
    command_id: str,
    *,
    commands_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/commands/{id}`` (current record only)."""
    registry = CommandRegistry(_resolve_commands_path(commands_path))
    cmd = registry.get(command_id)
    if cmd is None:
        return 404, {"error": {"message": f"Command '{command_id}' not found.",
                               "type": "invalid_request_error", "code": 404}}
    return 200, {"ok": True, "data": cmd.to_dict()}


def process_robot_library_components() -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/components`` (read-only list)."""
    catalog = ComponentCatalog()
    items = catalog.list_all()
    return 200, {"ok": True, "data": {"items": [c.to_dict() for c in items], "total": len(items)}}


def process_robot_library_component(component_id: str) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/components/{id}`` (schema included)."""
    catalog = ComponentCatalog()
    comp = catalog.get(component_id)
    if comp is None:
        return 404, {"error": {"message": f"Component '{component_id}' not found.",
                               "type": "invalid_request_error", "code": 404}}
    return 200, {"ok": True, "data": comp.to_dict()}
```

Add the four `handle_*` functions immediately after `handle_robot_system_action` (after line 654):

```python
async def handle_robot_library_commands(request: web.Request) -> web.Response:
    """GET /api/robot/library/commands — read-only command list."""
    if request.query.get("version") is not None:
        return _error_json(400, "unsupported parameter: version")
    status, result = process_robot_library_commands(
        commands_path=request.app.get("robot_commands_path"),
        component_id=request.query.get("component_id") or None,
        risk_level=request.query.get("risk_level") or None,
        status=request.query.get("status") or None,
        q=request.query.get("q") or None,
    )
    return web.json_response(result, status=status)


async def handle_robot_library_command(request: web.Request) -> web.Response:
    """GET /api/robot/library/commands/{command_id} — single command."""
    if request.query.get("version") is not None:
        return _error_json(400, "unsupported parameter: version")
    command_id = request.match_info["command_id"]
    status, result = process_robot_library_command(
        command_id, commands_path=request.app.get("robot_commands_path")
    )
    return web.json_response(result, status=status)


async def handle_robot_library_components(request: web.Request) -> web.Response:
    """GET /api/robot/library/components — read-only component list."""
    status, result = process_robot_library_components()
    return web.json_response(result, status=status)


async def handle_robot_library_component(request: web.Request) -> web.Response:
    """GET /api/robot/library/components/{component_id} — component schema."""
    status, result = process_robot_library_component(request.match_info["component_id"])
    return web.json_response(result, status=status)
```

Register the routes inside `register_robot_routes` (after the `system-action` line, before the function ends):

```python
    app.router.add_get("/api/robot/library/commands", handle_robot_library_commands)
    app.router.add_get("/api/robot/library/commands/{command_id}", handle_robot_library_command)
    app.router.add_get("/api/robot/library/components", handle_robot_library_components)
    app.router.add_get("/api/robot/library/components/{component_id}", handle_robot_library_component)
```

Extend `__all__` (add these names to the existing tuple):

```python
    "handle_robot_library_commands",
    "handle_robot_library_command",
    "handle_robot_library_components",
    "handle_robot_library_component",
    "process_robot_library_commands",
    "process_robot_library_command",
    "process_robot_library_components",
    "process_robot_library_component",
    "DEFAULT_COMMANDS_PATH",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_robot_library_routes.py -v`
Expected: 7 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_robot_library_routes.py tests/robot_ai/test_robot_routes.py -q`
Expected: all pass (new + existing robot routes still green). No git commit.

---

## Task 8: Mount library routes in the gateway dispatcher (`ws_http.py`)

**Files:**
- Modify: `nanobot/webui/ws_http.py` (add `_dispatch_robot_library_routes` + call it in `_dispatch_robot_routes`)
- Test: `tests/robot_ai/test_ws_http_library_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/robot_ai/test_ws_http_library_routes.py
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nanobot.webui.ws_http import GatewayHTTPHandler
from robot_ai.library.models import Command
from robot_ai.library.registry import CommandRegistry


def _fake_handler(token_ok: bool, commands_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        check_api_token=lambda _req: token_ok,
        _robot_commands_path=commands_path,
    )


def _fake_request(path: str) -> SimpleNamespace:
    return SimpleNamespace(path=path, headers={})


def _seed(path: Path) -> None:
    CommandRegistry(path).add(
        Command(id="io0-off", name="IO0关闭", component_id="io_write", aliases=["grip"])
    )


def test_library_list_requires_token(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=False, commands_path=str(commands))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands"), "/api/robot/library/commands"
    )
    assert resp is not None
    assert resp.status_code == 401


def test_library_list_returns_200_with_token(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=True, commands_path=str(commands))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands"), "/api/robot/library/commands"
    )
    assert resp.status_code == 200


def test_library_command_detail_404(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=True, commands_path=str(commands))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands/nope"),
        "/api/robot/library/commands/nope",
    )
    assert resp.status_code == 404


def test_library_version_param_rejected(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=True, commands_path=str(commands))
    # got is path-only (as _parse_request_path yields); the query lives in request.path.
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands?version=1"),
        "/api/robot/library/commands",
    )
    assert resp.status_code == 400


def test_library_components_list(tmp_path: Path) -> None:
    fake = _fake_handler(token_ok=True, commands_path=str(tmp_path / "commands.json"))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/components"),
        "/api/robot/library/components",
    )
    assert resp.status_code == 200


def test_non_library_path_returns_none(tmp_path: Path) -> None:
    fake = _fake_handler(token_ok=True, commands_path=str(tmp_path / "commands.json"))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/status"), "/api/robot/status"
    )
    assert resp is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_ws_http_library_routes.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_dispatch_robot_library_routes'`

- [ ] **Step 3: Write minimal implementation**

In `nanobot/webui/ws_http.py`, add a new method to `GatewayHTTPHandler` immediately before `_dispatch_robot_routes` (before line 386):

```python
    def _dispatch_robot_library_routes(self, request: WsRequest, got: str) -> Response | None:
        """Dispatch the read-only ``/api/robot/library/*`` endpoints.

        Token-gated GET (no body), mounted through the robot dispatcher so the
        library inherits the same ``check_api_token`` gate as the other robot
        routes. Detail paths use regex (the rest of the robot dispatcher is
        exact-match only). ``?version=`` is explicitly unsupported in A1.
        """
        command_detail = re.match(r"^/api/robot/library/commands/([^/]+)$", got)
        component_detail = re.match(r"^/api/robot/library/components/([^/]+)$", got)
        is_command_list = got == "/api/robot/library/commands"
        is_component_list = got == "/api/robot/library/components"
        if not (command_detail or component_detail or is_command_list or is_component_list):
            return None

        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")

        query = _parse_query(request.path)
        if _query_first(query, "version") is not None:
            return _http_error(400, "unsupported parameter: version")

        from nanobot.api.robot_routes import (
            DEFAULT_COMMANDS_PATH,
            process_robot_library_command,
            process_robot_library_commands,
            process_robot_library_component,
            process_robot_library_components,
        )

        commands_path = getattr(self, "_robot_commands_path", None) or DEFAULT_COMMANDS_PATH

        if is_command_list:
            status, result = process_robot_library_commands(
                commands_path=commands_path,
                component_id=_query_first(query, "component_id") or None,
                risk_level=_query_first(query, "risk_level") or None,
                status=_query_first(query, "status") or None,
                q=_query_first(query, "q") or None,
            )
        elif command_detail is not None:
            status, result = process_robot_library_command(
                unquote(command_detail.group(1)), commands_path=commands_path
            )
        elif is_component_list:
            status, result = process_robot_library_components()
        else:  # component_detail
            status, result = process_robot_library_component(unquote(component_detail.group(1)))
        return _http_json_response(result, status=status)
```

Then wire it in as the **first** action inside `_dispatch_robot_routes` — add these two lines immediately after the method's docstring (right before the existing `if got not in (...)` check, around line 395):

```python
        lib_response = self._dispatch_robot_library_routes(request, got)
        if lib_response is not None:
            return lib_response
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_ws_http_library_routes.py -v`
Expected: 6 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/test_ws_http_library_routes.py -q`
Expected: `6 passed`. No git commit.

---

## Task 9: Final verification (full suite + ruff + real migration smoke)

**Files:** none (verification only)

- [ ] **Step 1: Run the full robot_ai + robot_routes test suite**

Run: `cd nanobot-main-1 && python -m pytest tests/robot_ai/ -q`
Expected: all pass (new library tests + existing flow/registry/routes tests still green — FlowRegistry untouched).

- [ ] **Step 2: Run ruff on all touched code**

Run: `cd nanobot-main-1 && ruff check nanobot/ robot_ai/ tools/ tests/`
Expected: clean (no errors). Rules E/F/I/N/W, E501 ignored.

- [ ] **Step 3: Smoke-run the real migration CLI against a throwaway output dir**

Run: `cd nanobot-main-1 && ROBOT_LIBRARY_OUT_DIR=./tmp_lib_smoke python tools/migrate_robot_commands.py`
Expected output (key lines):
```
Migrated 16 commands:
  + ...  (16 lines)
Skipped 5 records:
  - func=106  J1到10度  (v1 component set has no joint_move (Func106))
  - func=106  J2回正  (...)
  - func=107  X前进50  (...)
  - func=109  T0延时1秒  (...)
  - func=11   连续插补示例  (...)
Audit: written -> ./tmp_lib_smoke/audit.jsonl
```

- [ ] **Step 4: Re-run to confirm idempotency**

Run: `cd nanobot-main-1 && ROBOT_LIBRARY_OUT_DIR=./tmp_lib_smoke python tools/migrate_robot_commands.py`
Expected: `Migrated 0 commands` (all 16 already seeded → idempotent no-op) and `Skipped 5 records` (the 5 unmappable records are skipped on every run — they are never seeded, just reported) and `Audit: skipped (already present)` (deduped by `migration_id`). Confirm `audit.jsonl` still has exactly **one** line.

- [ ] **Step 5: Clean up the smoke dir**

Run: `cd nanobot-main-1 && rm -rf tmp_lib_smoke`
Expected: no output.

- [ ] **Step 6: Final checkpoint — no commit**

All tests pass, ruff clean, migration produces 16/5 + audit, idempotent. Do **not** `git add`/`commit` — the user commits unified later. Report completion.

---

## Self-Review

**1. Spec coverage:**
- §3 module layout → Tasks 1–6 create every listed file; Task 7–8 add the API + ws_http mount.
- §4 data models (Command/Component/ParameterField/AuditEntry + enums + normalize_id + risk mapping) → Task 2 (models) + Task 3 (catalog schema) + Task 5 (`_map_risk`).
- §4.3 `migration_id` audit field → Task 2 (AuditEntry) + Task 5 (migration writes it).
- §5 CommandRegistry atomic persist + global-namespace uniqueness + query → Task 4 (incl. `namespace()`, name/alias cross-conflict tests).
- §5 ComponentCatalog in-memory, no persistence → Task 3.
- §6 migration: 16 migrated / 5 skipped, deterministic id, alias dedup, report, audit summary, `migration_id` dedup, failure/backfill semantics → Task 5 (tests assert 16/5, idempotency, failure+backfill).
- §6 CLI `tools/migrate_robot_commands.py` → Task 6 (mirrors `migrate_robot_flows.py`).
- §7 four read-only endpoints, envelope, 404/400, no `?version=` → Task 7 (process layer) + Task 8 (ws_http dispatch incl. `?version=`→400 + token 401).
- §8 security: token gate via ws_http dispatcher → Task 8 (`check_api_token` before dispatch, tested 401).
- §9 tests (models / registry / catalog / migration / routes incl. failure semantics + namespace + version-unsupported) → Tasks 2,4,3,5,7,8.
- §10 acceptance (ruff, 16/5, idempotent + dedup, token-gated, namespace unique, no frontend touched, FlowRegistry untouched) → Task 9 + each task's verify.
- Hard constraint (no `App.tsx`/`RobotOperatorApp.tsx`/frontend, no FlowRegistry change) → File Structure "Do NOT touch" + Task 9 re-runs existing flow tests to prove FlowRegistry unaffected.

**2. Placeholder scan:** No TBD/TODO/“add error handling”/“similar to Task N”. Every code step shows full code; every test step shows runnable test code; every command shows expected output.

**3. Type/signature consistency:**
- `CommandRegistry(path)` ctor, `.add(cmd)->tuple[bool,str]`, `.get(id)->Command|None`, `.list(*, component_id, risk_level, status, q)->list[Command]`, `.namespace()->set[str]` — defined Task 4, used Task 5 (migration) and Task 7 (routes) with identical signatures.
- `ComponentCatalog()` ctor, `.list_all()`, `.get(id)`, `.func_to_id(func)` — defined Task 3, used Task 5 + Task 7 identically.
- `migrate_commands(src_path, commands_path, audit_path) -> MigrationResult` with attrs `migration_id/migrated/skipped/dropped_aliases/audit_written/audit_error` — defined Task 5, used Task 6 (CLI) and Task 5 tests identically.
- `process_robot_library_commands(*, commands_path, component_id, risk_level, status, q)` etc. — defined Task 7, called in Task 8 ws_http dispatch with matching kwargs (`commands_path=`, filters as `str|None`).
- `DEFAULT_COMMANDS_PATH` defined Task 7, imported in Task 8.
- `MigrationResult.migrated` is `list[tuple[str,str]]`; CLI unpacks `for cid, name in result.migrated` — consistent. `skipped` is `list[tuple[int,str,str]]`; CLI unpacks `for func, name, reason` — consistent.

No gaps found. Plan is complete.
