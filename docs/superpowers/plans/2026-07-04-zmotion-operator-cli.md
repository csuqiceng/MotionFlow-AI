# ZMotion Operator CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dry-run-by-default operator CLI for the restricted Func104/108/110/120 real-controller path with explicit workspace and execution confirmations.

**Architecture:** A new `zmotion_operator_control.py` service owns configuration checks, SDK lifecycle, read-only state collection, software workspace validation, planner selection, dry-run results, and optional executor invocation. A thin tool script delegates argument parsing and output to that service. Existing GUI and agent paths remain untouched.

**Tech Stack:** Python 3.11, argparse, dataclasses, injected protocols/factories, pytest, existing ZMotion planner/executor/SDK.

---

### Task 1: Operator Control Service

**Files:**
- Create: `nanobot-main-1/robot_ai/zmotion_operator_control.py`
- Create: `nanobot-main-1/tests/robot_ai/test_zmotion_operator_control.py`

- [ ] **Step 1: Write failing service tests**

Define fake connected clients, executor factories, and requests. Require:

```python
request = ZMotionOperatorRequest(
    command="move_axis",
    parameters={
        "axis": "z",
        "delta": -1.0,
        "speed_pct": 5.0,
        "acceleration_pct": 5.0,
        "deceleration_pct": 5.0,
        "r_min": 800.0,
        "r_max": 1000.0,
        "z_min": 900.0,
        "z_max": 1100.0,
    },
)
result = run_zmotion_operator_command(request=request, config=config, client_factory=fake_factory)
assert result["state"] == "zmotion_operator_dry_run"
assert fake_client.float_writes == []
```

Also test missing config, all real-execution confirmations, out-of-workspace
targets, invalid limits, delta over 5, percentages over 5, disallowed IO, client
disconnect on success/failure, and executor invocation for supported commands.

- [ ] **Step 2: Run tests and verify missing module failure**

Run:

```powershell
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_operator_control.py -v
```

Expected: `ModuleNotFoundError` for `robot_ai.zmotion_operator_control`.

- [ ] **Step 3: Implement request, limits, and runner**

Create:

```python
REAL_EXECUTION_CONFIRMATION_CODE = "EXECUTE_ZMOTION_REAL"

@dataclass(frozen=True)
class ZMotionOperatorRequest:
    command: str
    parameters: dict[str, Any]
    execute_real: bool = False
    confirm_work_area_clear: bool = False
    confirm_estop_ready: bool = False
    confirmation_code: str = ""

@dataclass(frozen=True)
class CartesianWorkspaceLimits:
    r_min: float
    r_max: float
    z_min: float
    z_max: float
```

Implement `run_zmotion_operator_command()` with injected `client_factory` and
`executor_factory`. Validate configuration before creating the client. Connect
once, read state through `ZMotionReadOnlyBackend`, build one restricted plan,
and disconnect in `finally`.

For motion, validate limits, target radius/Z, absolute delta at most 5, and
speed/acceleration/deceleration in `(0, 5]`. Dry-run returns the plan and never
constructs the executor. Real mode requires all confirmations and passes both
runtime gates as true to planner and executor.

- [ ] **Step 4: Run service tests**

Run the command from Step 2.

Expected: all operator-control tests pass.

### Task 2: CLI And Tool Entry Point

**Files:**
- Modify: `nanobot-main-1/robot_ai/zmotion_operator_control.py`
- Create: `nanobot-main-1/tools/verify_zmotion_control.py`
- Create: `nanobot-main-1/tests/robot_ai/test_zmotion_operator_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Require `main(argv, runner=...)` to parse:

```text
system --action emergency_stop
move-axis --axis z --delta -1 --speed-pct 5 --acceleration-pct 5
          --deceleration-pct 5 --r-min 800 --r-max 1000 --z-min 900 --z-max 1100
delay --seconds 0.25
io --io-number 3 --state on --allowed-io 2,3,4
```

Test shared SDK options, execution confirmation options, JSON output, process
status, and the existence of `tools/verify_zmotion_control.py`.

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```powershell
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_operator_cli.py -v
```

Expected: import or attribute failures because CLI parsing is not implemented.

- [ ] **Step 3: Implement argparse and tool wrapper**

Add `main(argv=None, runner=run_zmotion_operator_command)` and subparsers for
`system`, `move-axis`, `delay`, and `io`. Convert `--allowed-io` into a list of
integers. Build `RobotBackendConfig` from environment plus CLI overrides.

The tool wrapper adds the repository root to `sys.path`, imports `main`, and
exits with its status.

- [ ] **Step 4: Run CLI tests**

Run the command from Step 2.

Expected: all CLI tests pass.

### Task 3: Regression And Documentation

**Files:**
- Modify: `docs/nanobot_robot_ai_implementation_plan_2026-07-03.md`
- Modify: `docs/zmotion_real_hardware_test_2026-07-04.md`

- [ ] **Step 1: Verify application isolation**

Run:

```powershell
rg -n "zmotion_operator_control|verify_zmotion_control|ZMotionOperatorRequest" robot_ai\bridge.py robot_desktop.py nanobot\agent\tools\robot_arm.py
```

Expected: no matches.

- [ ] **Step 2: Run focused, full, and compile verification**

Run:

```powershell
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_operator_control.py tests\robot_ai\test_zmotion_operator_cli.py -v
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v
.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\zmotion_operator_control.py tools\verify_zmotion_control.py tests\robot_ai\test_zmotion_operator_control.py tests\robot_ai\test_zmotion_operator_cli.py
```

Expected: all commands exit zero.

- [ ] **Step 3: Update implementation records**

Document the CLI commands, confirmation gates, software workspace checks, test
totals, and the fact that implementation verification used fake clients only.

## Worktree Note

The shared worktree is dirty and on `main`. Do not commit, reset, checkout, or
reorder existing changes unless explicitly requested.
