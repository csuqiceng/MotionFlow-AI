# Robot Auto-Execution Mode Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist `auto_after_safety_check` through all typed configuration saves and load it from the active nanobot configuration path.

**Architecture:** `ToolsConfig` owns validation and serialization of the execution policy. The lightweight runtime reader continues to fail closed, but resolves the same active config path as the rest of nanobot and accepts both serialized camelCase and legacy snake_case keys.

**Tech Stack:** Python 3.11, Pydantic v2, pytest

---

### Task 1: Typed configuration persistence

**Files:**
- Modify: `nanobot-main-1/nanobot/config/schema.py`
- Create: `nanobot-main-1/tests/robot_ai/test_execution_mode_config.py`

- [ ] **Step 1: Write the failing configuration round-trip test**

```python
def test_execution_mode_survives_typed_config_round_trip(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"tools":{"execution_mode":"auto_after_safety_check"}}', encoding="utf-8")
    config = load_config(path)
    save_config(config, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert config.tools.execution_mode == "auto_after_safety_check"
    assert saved["tools"]["executionMode"] == "auto_after_safety_check"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest -q tests/robot_ai/test_execution_mode_config.py::test_execution_mode_survives_typed_config_round_trip`

Expected: FAIL because `ToolsConfig` has no `execution_mode` attribute and drops the input key.

- [ ] **Step 3: Add the typed field with compatibility aliases**

```python
execution_mode: Literal["dry_run_only", "auto_after_safety_check", "manual_confirm"] = Field(
    default="dry_run_only",
    validation_alias=AliasChoices("executionMode", "execution_mode"),
)
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pytest -q tests/robot_ai/test_execution_mode_config.py::test_execution_mode_survives_typed_config_round_trip`

Expected: `1 passed`.

### Task 2: Active-path runtime loading

**Files:**
- Modify: `nanobot-main-1/robot_ai/execution/mode.py`
- Modify: `nanobot-main-1/tests/robot_ai/test_execution_mode_config.py`

- [ ] **Step 1: Write failing reader tests**

```python
def test_mode_reader_uses_active_config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"tools":{"executionMode":"auto_after_safety_check"}}', encoding="utf-8")
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: path)
    assert mode._load_execution_mode() == "auto_after_safety_check"

@pytest.mark.parametrize("payload", [{}, {"tools": {}}, {"tools": {"executionMode": "invalid"}}])
def test_mode_reader_fails_closed(tmp_path, monkeypatch, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: path)
    assert mode._load_execution_mode() == "dry_run_only"
```

- [ ] **Step 2: Run the reader tests and verify RED**

Run: `pytest -q tests/robot_ai/test_execution_mode_config.py -k mode_reader`

Expected: active-path/camelCase test fails because the reader uses the home path and snake_case only.

- [ ] **Step 3: Implement minimal active-path compatible reader**

```python
from nanobot.config.loader import get_config_path

def _load_execution_mode() -> str:
    config_path = get_config_path()
    if not config_path.exists():
        return "dry_run_only"
    try:
        tools = json.loads(config_path.read_text(encoding="utf-8")).get("tools", {})
        selected = tools.get("executionMode", tools.get("execution_mode", "dry_run_only"))
        mode = str(selected)
        return mode if mode in VALID_MODES else "dry_run_only"
    except Exception:
        return "dry_run_only"
```

- [ ] **Step 4: Run the complete regression file and verify GREEN**

Run: `pytest -q tests/robot_ai/test_execution_mode_config.py`

Expected: all tests pass.

### Task 3: Activate and verify the runtime policy

**Files:**
- Modify runtime data: `%USERPROFILE%/.nanobot/config.json`

- [ ] **Step 1: Run focused regression suites**

Run: `pytest -q tests/robot_ai/test_execution_mode_config.py tests/robot_ai/test_nanobot_robot_tool_adapter.py tests/robot_ai/test_robot_flow_tool.py tests/robot_ai/test_robot_routes.py`

Expected: all selected tests pass.

- [ ] **Step 2: Update active config through the typed loader**

```python
config = load_config()
config.tools.execution_mode = "auto_after_safety_check"
save_config_atomic(config)
```

- [ ] **Step 3: Verify persistence with a fresh load**

Run a new Python process that loads the active config and prints `config.tools.execution_mode` and the serialized JSON value.

Expected: both values are `auto_after_safety_check`.

- [ ] **Step 4: Restart the running gateway**

Use the project's existing gateway launch/stop mechanism so import-time `EXECUTION_MODE` and `AUTO_EXECUTE` are refreshed. Do not issue any robot command.

- [ ] **Step 5: Verify status without motion**

Authenticate locally and call `GET /api/robot/status`.

Expected: `connected_real_device` remains true and `execution_mode` is `auto_after_safety_check`.

- [ ] **Step 6: Review the final diff**

Run: `git diff -- nanobot-main-1/nanobot/config/schema.py nanobot-main-1/robot_ai/execution/mode.py nanobot-main-1/tests/robot_ai/test_execution_mode_config.py`

Expected: only the typed field, compatible reader, and regression tests are present.
