# nanobot Robot AI Implementation Plan

> Date: 2026-07-03
> Source root: `C:\Users\KY\Desktop\yjcao\nanobot_robot_ai\nanobot-main-1`
> Legacy reference only: `C:\Users\KY\Desktop\yjcao\ai_pipeline_prototype-trae-solo-agent-cINULN (1)\ai_pipeline_prototype-trae-solo-agent-cINULN\重构版本`

## Goal

Build a zero-port Windows desktop robot-arm AI on top of nanobot. The first working loop is text input plus simulated robot actions; cloud LLM/STT/TTS, full WebUI bridge, and real controller access are later phases.

## Current Verified State

- `nanobot-main-1` contains nanobot source code, but it is not a git repository.
- `nanobot.nanobot.Nanobot` is the in-process SDK entry point and can run through `AgentLoop.process_direct()` without gateway.
- Built-in tools are auto-discovered from `nanobot/agent/tools` by `pkgutil`.
- STT exists in `nanobot/audio/transcription.py`, `nanobot/audio/transcription_registry.py`, and `nanobot/providers/transcription.py`.
- TTS is not present as a nanobot subsystem.
- WebUI currently depends on WebSocket transport in `webui/src/lib/nanobot-client.ts`.
- `robot_ai/`, `nanobot/agent/tools/robot_arm.py`, and `robot_desktop.py` do not exist in the current source tree.

## Architecture

```text
pywebview desktop shell
  -> local HTML or built WebUI
  -> Python bridge
  -> nanobot SDK
  -> robot tool adapter
  -> robot_ai core
       -> SimulationRobotBackend
       -> SafetyPolicy
       -> ToolResult
```

The robot domain logic lives outside nanobot internals first, under `robot_ai/`, so it can be tested without LLM or gateway. A later adapter registers robot actions as nanobot tools.

## Implementation Tasks

### Task 1: Simulation Core

Files:
- Create `nanobot-main-1/robot_ai/__init__.py`
- Create `nanobot-main-1/robot_ai/models.py`
- Create `nanobot-main-1/robot_ai/safety/__init__.py`
- Create `nanobot-main-1/robot_ai/safety/policy.py`
- Create `nanobot-main-1/robot_ai/backends/__init__.py`
- Create `nanobot-main-1/robot_ai/backends/simulation_backend.py`
- Create `nanobot-main-1/tests/robot_ai/test_simulation_backend.py`

Behaviors:
- Initial state is idle, six axes are zero, no alarms, no real device connected.
- `get_state()` returns a serializable state object.
- `move_axis(axis, delta)` updates one axis when within limits.
- Out-of-range movement returns rejection and does not mutate state.
- `home()` returns all axes to zero.
- `stop()` changes mode to stopped without pretending a hardware emergency stop happened.

Verification:

```powershell
python -m pytest tests/robot_ai/test_simulation_backend.py -v
```

### Task 2: Robot Tool Facade

Files:
- Create `nanobot-main-1/robot_ai/tools/__init__.py`
- Create `nanobot-main-1/robot_ai/tools/robot_tools.py`
- Create `nanobot-main-1/tests/robot_ai/test_robot_tools.py`

Behaviors:
- Expose `robot_get_status`, `robot_move_axis`, `robot_home`, `robot_stop`, and `robot_explain_limits`.
- Every function returns `ToolResult` with `ok/state/message/data/errors`.
- Tool layer is the only layer allowed to say whether simulated execution succeeded or was refused.

Verification:

```powershell
python -m pytest tests/robot_ai/test_robot_tools.py -v
```

### Task 3: Nanobot Tool Adapter

Files:
- Create `nanobot-main-1/nanobot/agent/tools/robot_arm.py`
- Create `nanobot-main-1/tests/robot_ai/test_nanobot_robot_tool_adapter.py`

Behaviors:
- Register one nanobot tool named `robot_arm`.
- Accept an `action` field and route to the robot tool facade.
- Mark motion actions as exclusive.
- Keep safety refusal as structured tool output.

Verification:

```powershell
python -m pytest tests/robot_ai/test_nanobot_robot_tool_adapter.py -v
```

### Task 4: Minimal Desktop Bridge

Files:
- Create `nanobot-main-1/robot_ai/bridge.py`
- Create `nanobot-main-1/robot_desktop.py`
- Create `nanobot-main-1/tests/robot_ai/test_desktop_bridge.py`

Behaviors:
- Provide `health()`, `send_message(text)`, `get_robot_state()`, `move_axis(axis, delta)`, `home()`, and `stop()`.
- Robot buttons work without network or LLM.
- Chat uses nanobot SDK when config/provider are available; otherwise returns a clear configuration/network error.
- No gateway port is started.

Verification:

```powershell
python -m pytest tests/robot_ai/test_desktop_bridge.py -v
```

### Task 5: Voice and WebUI Bridge

Files:
- Add TTS subsystem only after text and desktop bridge are stable.
- Add a pywebview transport adapter for the WebUI only after the minimal bridge is verified.

Behaviors:
- Reuse existing STT where possible.
- Add TTS provider abstraction separately from STT.
- Keep microphone/VAD and WebUI transport changes isolated.

Verification:

```powershell
python -m pytest tests/robot_ai -v
```

## Safety Rules

- Real Modbus, serial, ZMotion, or write-controller logic is not implemented until protocol documentation is provided.
- All production-motion commands must pass through `SafetyPolicy`.
- Over-limit commands must be rejected before backend state changes.
- High-risk real actions later need a pending-confirm gate and physical emergency stop outside software.

## This Turn Scope

Implement Task 1 with TDD, then report:
- What was implemented.
- What was verified.
- What the next task is.
