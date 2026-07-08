# ZMotion Supported Functions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the provisional ZMotion planner with the confirmed Func104/108/110/120 protocol and add guarded echo verification plus sequential Func108 path execution.

**Architecture:** `zmotion_write_plan.py` becomes the single source of truth for supported command payloads, even-numbered VR addresses, expected echoes, and plan blockers. `zmotion_write_executor.py` submits one plan through a read/write client, verifies echoes and controller state before triggering, and returns structured results. A focused sequence runner composes the single-command executor for ordered Func108 path points.

**Tech Stack:** Python 3.11, dataclasses, typing protocols, pytest, existing `ToolResult`, ZMotion SDK wrapper.

---

### Task 1: Replace The Provisional Planner

**Files:**
- Modify: `nanobot-main-1/robot_ai/backends/zmotion_write_plan.py`
- Modify: `nanobot-main-1/tests/robot_ai/test_zmotion_write_plan.py`

- [ ] **Step 1: Replace the old planner expectations with failing protocol tests**

Add tests that require:

```python
plan = planner.plan_move_axis(
    axis="z",
    delta=-1.0,
    robot_state=RobotState(
        mode="idle",
        axes_mm={"x": 900.0, "y": 0.0, "z": 1000.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
        connected_real_device=True,
    ),
    speed_pct=5.0,
    acceleration_pct=5.0,
    deceleration_pct=5.0,
    confirmed_real_motion=True,
    allow_real_motion_writes=True,
)
assert [item.vr for item in plan.parameter_writes] == list(range(0, 32, 2))
assert [item.value for item in plan.parameter_writes] == [
    108.0, 900.0, 0.0, 999.0, 0.0, 0.0, 0.0,
    5.0, 5.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
]
assert plan.expected_echoes[286] == 999.0
```

Also require exact Func104 actions, Func110 delay payload, Func120 IO payload, and structured rejection of unsupported actions.

- [ ] **Step 2: Run planner tests and verify the old implementation fails**

Run:

```powershell
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_write_plan.py -v
```

Expected: failures showing the old `0,1,2` payload and missing planner APIs.

- [ ] **Step 3: Implement the restricted command planner**

Define:

```python
ZMOTION_SUPPORTED_FUNCTIONS = frozenset({104, 108, 110, 120})
ZMOTION_PARAMETER_VRS = tuple(range(0, 32, 2))

@dataclass(frozen=True)
class ZMotionCommandPlan:
    action: str
    function_code: int
    executable: bool
    blockers: list[str]
    parameter_writes: list[ZMotionWriteDraft]
    expected_echoes: dict[int, float]
    trigger_write: ZMotionWriteDraft
    accept_vr: int
```

Implement:

```python
plan_move_axis(...)
plan_linear_move(...)
plan_system_control(action, ...)
plan_delay(seconds, ...)
plan_io(io_number, enabled, allowed_io_channels, ...)
```

`plan_move_axis` must copy the current six-axis pose, apply one delta, and
delegate to `plan_linear_move`. Func108 must always write all 16 even-addressed
fields with `move_type=0`. Func104 must support only:

```python
{
    "emergency_stop": (1, 0, 0),
    "release_emergency_stop": (2, 0, 0),
    "pause": (0, 1, 0),
    "resume": (0, 2, 0),
    "stop_current": (0, 0, 1),
    "release_cancel": (0, 0, 2),
}
```

Build echoes as `{280 + write.vr: write.value}`.

Func108, Func110, and Func120 plans require idle, alarm-free state. Func104
emergency stop, pause, stop current, and their release/resume controls do not use
the motion idle/alarm blockers; they still require a connected real device and
both explicit write gates.

- [ ] **Step 4: Run planner tests**

Run the command from Step 2.

Expected: all planner tests pass.

### Task 2: Add Echo And Pre-Trigger Verification

**Files:**
- Modify: `nanobot-main-1/robot_ai/backends/zmotion_write_executor.py`
- Modify: `nanobot-main-1/tests/robot_ai/test_zmotion_write_executor.py`

- [ ] **Step 1: Add failing executor tests**

Extend the fake client with:

```python
def read_modbus_float(self, request: ModbusReadRequest) -> list[float]: ...
def read_modbus_long(self, request: ModbusReadRequest) -> list[int]: ...
```

Add tests proving:

- all parameters are written before echo reads;
- an echo mismatch returns `real_motion_echo_mismatch` and never writes VR 32;
- `LONG(38) != 0` returns `real_motion_pretrigger_unsafe`;
- safe values `LONG(34)`, `LONG(36)`, `LONG(38)=0` allow VR 32 last;
- read exceptions return `real_motion_verification_failed` without a trigger.

- [ ] **Step 2: Run executor tests and verify failure**

Run:

```powershell
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_write_executor.py -v
```

Expected: failures because the current executor does not read echoes or status.

- [ ] **Step 3: Implement verification in the executor**

Expand the client protocol with read methods. After all parameter writes:

```python
for vr, expected in plan.expected_echoes.items():
    actual = client.read_modbus_float(ModbusReadRequest(start_vr=vr, count=1))[0]
    if abs(actual - expected) > echo_tolerance:
        return echo_mismatch_failure
```

Then read:

```python
status = client.read_modbus_long(ModbusReadRequest(start_vr=34, count=1))[0]
system_state = client.read_modbus_long(ModbusReadRequest(start_vr=36, count=1))[0]
alarm = client.read_modbus_long(ModbusReadRequest(start_vr=38, count=1))[0]
```

Reject alarms and unsafe plan/controller states before submitting the trigger.
Preserve the SDK write gates and write the trigger last.

- [ ] **Step 4: Run executor tests**

Run the command from Step 2.

Expected: all executor tests pass.

### Task 3: Add Sequential Func108 Paths

**Files:**
- Create: `nanobot-main-1/robot_ai/backends/zmotion_sequence.py`
- Create: `nanobot-main-1/tests/robot_ai/test_zmotion_sequence.py`

- [ ] **Step 1: Write failing sequence tests**

Define a fake single-command executor and require:

```python
result = runner.execute(plans, allow_real_motion_writes=True, confirmed_real_motion=True)
assert fake_executor.actions == ["linear_move", "linear_move", "linear_move"]
assert result["state"] == "real_motion_sequence_submitted"
```

Also test that the second segment failure prevents the third segment from
executing and returns `real_motion_sequence_failed` with `failed_segment=2`.

- [ ] **Step 2: Run sequence tests and verify missing module failure**

Run:

```powershell
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_sequence.py -v
```

Expected: `ModuleNotFoundError` for `zmotion_sequence`.

- [ ] **Step 3: Implement the sequence runner**

Create:

```python
class ZMotionSequenceRunner:
    def __init__(self, executor: ZMotionSinglePlanExecutor) -> None: ...

    def execute(
        self,
        plans: list[ZMotionCommandPlan],
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict: ...
```

Reject any plan whose function code is not 108. Execute in order using the same
runtime gates. Stop on the first non-OK result and return its segment number.

- [ ] **Step 4: Run sequence tests**

Run the command from Step 2.

Expected: all sequence tests pass.

### Task 4: Restrict Integration Surface And Regress

**Files:**
- Modify: `docs/nanobot_robot_ai_implementation_plan_2026-07-03.md`
- Verify only: `nanobot-main-1/robot_ai/bridge.py`
- Verify only: `nanobot-main-1/robot_ai/tools.py`
- Verify only: `nanobot-main-1/nanobot/agent/tools/robot_arm.py`

- [ ] **Step 1: Verify unsupported functions are absent from the new path**

Run:

```powershell
rg -n "Func(8|11|102|106|107|109|112)|function_code.?=.?\\b(8|11|102|106|107|109|112)\\b" robot_ai tests\robot_ai
```

Expected: no supported-planner references to excluded functions.

- [ ] **Step 2: Verify write components remain disconnected from application paths**

Run:

```powershell
rg -n "ZMotionWriteExecutor|ZMotionSequenceRunner|zmotion_write_executor|zmotion_sequence" robot_ai\bridge.py robot_ai\tools.py nanobot\agent\tools\robot_arm.py robot_desktop.py
```

Expected: no matches.

- [ ] **Step 3: Run focused and full verification**

Run:

```powershell
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_write_plan.py tests\robot_ai\test_zmotion_write_executor.py tests\robot_ai\test_zmotion_sequence.py -v
.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v
.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\zmotion_write_plan.py robot_ai\backends\zmotion_write_executor.py robot_ai\backends\zmotion_sequence.py tests\robot_ai\test_zmotion_write_plan.py tests\robot_ai\test_zmotion_write_executor.py tests\robot_ai\test_zmotion_sequence.py
```

Expected: all commands exit zero.

- [ ] **Step 4: Update implementation documentation**

Record the supported function set, exact real protocol, test totals, and that no
real write or physical motion was performed during implementation.

## Worktree Note

The shared worktree is already dirty and currently on `main`, with existing
staged and unstaged user changes. Do not commit, reset, checkout, or reorder
those changes unless the user explicitly requests it.
