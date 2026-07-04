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
- TTS now has a lightweight nanobot subsystem skeleton: provider registry, config resolution, and adapter interface. Real provider HTTP adapters are still pending.
- WebUI currently depends on WebSocket transport in `webui/src/lib/nanobot-client.ts`.
- `robot_ai/`, `nanobot/agent/tools/robot_arm.py`, and `robot_desktop.py` now exist in the current source tree as the first simulated desktop loop.

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

## Progress Log

### 2026-07-03

- Implemented Task 1: `robot_ai` simulation core with `ToolResult`, `RobotState`, `SafetyPolicy`, and `SimulationRobotBackend`.
- Implemented Task 2: `RobotToolFacade` plus module-level robot tool functions.
- Implemented Task 3 code: nanobot `robot_arm` adapter under `nanobot/agent/tools/robot_arm.py`.
- Verified:
  - `python -m pytest tests/robot_ai/test_simulation_backend.py tests/robot_ai/test_robot_tools.py tests/robot_ai/test_nanobot_robot_tool_adapter.py -v`
  - Result: 10 passed, 5 skipped. Skips are adapter tests gated on missing local nanobot dependencies (`loguru`, `pydantic`).
  - `python -m py_compile robot_ai\models.py robot_ai\safety\policy.py robot_ai\backends\simulation_backend.py robot_ai\tools\robot_tools.py nanobot\agent\tools\robot_arm.py`
  - Result: compile success.
- Implemented Task 4: `RobotApi` bridge and a minimal `robot_desktop.py` pywebview entry.
- Verified:
  - `python -m pytest tests/robot_ai/test_simulation_backend.py tests/robot_ai/test_robot_tools.py tests/robot_ai/test_nanobot_robot_tool_adapter.py tests/robot_ai/test_desktop_bridge.py -v`
  - Result: 15 passed, 5 skipped. Skips are still adapter tests gated on missing local nanobot dependencies (`loguru`, `pydantic`).
  - `python -m py_compile robot_ai\models.py robot_ai\safety\policy.py robot_ai\backends\simulation_backend.py robot_ai\tools\robot_tools.py robot_ai\bridge.py nanobot\agent\tools\robot_arm.py robot_desktop.py`
  - Result: compile success.
- Implemented Task 5 first slice: TTS provider registry/config skeleton with `edge_tts`, `azure_speech`, and `xfyun`; added stable `synthesize_text()` adapter entry point and provider placeholders.
- Implemented Task 5 second slice: desktop bridge voice API with `get_voice_state()` and `synthesize_speech(text)` returning frontend-ready base64 audio payloads through the shared TTS service.
- Implemented Task 5 third slice: minimal `robot_desktop.py` HTML now includes voice status and speech playback controls wired to the pywebview API.
- Implemented Task 5 fourth slice: config schema and WebUI settings wiring for TTS provider selection (`Config.tts`, `update_tts_settings()`, `/api/settings/tts/update`, and settings payload `tts` section).
- Implemented Task 5 fifth slice: optional Edge TTS adapter using `edge_tts` when installed, plus lazy `nanobot.providers` package exports so TTS adapters do not require LLM provider dependencies at import time.
- Implemented Task 5 sixth slice: package metadata now declares desktop/voice runtime extras (`desktop`, `voice`, and `robot-desktop`) for `pywebview` and optional `edge-tts`.
- Implemented Task 5 seventh slice: runtime dependency diagnostics for the desktop entrypoint, including structured missing-module status and an install command for `.[robot-desktop]`.
- Implemented Task 5 eighth slice: repeatable desktop runtime smoke verifier (`robot_ai.runtime_smoke` and `tools/verify_robot_desktop_runtime.py`) that checks dependencies, bridge health, simulated motion, and voice settings without launching a GUI window.
- Implemented Task 5 ninth slice: controlled runtime environment `.venv-robot-desktop` with `.[dev,robot-desktop]` installed for full local verification.
- Implemented Task 5 tenth slice: actual pywebview desktop-window probe (`tools/probe_robot_desktop_window.py`) with auto-close after `pywebviewready`, avoiding premature WebView2 teardown.
- Implemented Task 5 eleventh slice: packaging metadata now includes `robot_ai`, `robot_desktop.py`, desktop probe tools, and console scripts `robot-desktop` and `robot-desktop-probe`.
- Verified:
  - `python -m pytest tests/robot_ai/test_tts_config.py -v`
  - Result: 7 passed.
  - `python -m pytest tests/robot_ai/test_desktop_bridge.py -v`
  - Result: 9 passed.
  - `python -m pytest tests/robot_ai/test_desktop_html.py tests/robot_ai/test_desktop_bridge.py tests/robot_ai/test_tts_config.py -v`
  - Result: 17 passed.
  - `python -m pytest tests/robot_ai/test_tts_settings_wiring.py -v`
  - Result: 3 passed.
  - `python -m pytest tests/robot_ai/test_runtime_packaging.py -v`
  - Result: 7 passed.
  - `python -m pytest tests/robot_ai/test_runtime_smoke.py -v`
  - Result: 3 passed.
  - `python -m pytest tests/robot_ai -v`
  - Result: 41 passed, 5 skipped. Skips are still adapter tests gated on missing local nanobot dependencies (`loguru`, `pydantic`).
  - `python tools\verify_robot_desktop_runtime.py --json`
  - Result: expected non-zero dependency report in the current environment: missing required `pydantic`, `loguru`, `webview`; missing optional `edge_tts`; install hint `python -m pip install -e ".[robot-desktop]"`.
  - `.venv-robot-desktop\Scripts\python.exe tools\verify_robot_desktop_runtime.py --json`
  - Result: runtime smoke passed with dependencies ready, bridge healthy, simulated `x` motion to `5.0`, and TTS settings resolved.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 46 passed. The previous 5 skipped nanobot adapter tests now pass with `pydantic` and `loguru` installed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\webui\test_settings_api.py -v`
  - Result: 53 passed, including real TTS settings payload/update coverage.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai tests\webui\test_settings_api.py -v`
  - Result: 99 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_desktop_window_probe.py -v`
  - Result: 5 passed.
  - `.venv-robot-desktop\Scripts\python.exe tools\probe_robot_desktop_window.py --auto-close --auto-close-delay 2 --json`
  - Result: desktop pywebview window probe passed cleanly after waiting for `pywebviewready`.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai tests\webui\test_settings_api.py -v`
  - Result: 107 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_desktop_packaging_metadata.py tests\robot_ai\test_runtime_smoke.py -v`
  - Result: 6 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m robot_ai.runtime_smoke --json`
  - Result: runtime smoke passed through the console-script target function.
  - `python -m py_compile robot_ai\runtime_smoke.py tools\verify_robot_desktop_runtime.py robot_ai\runtime.py robot_desktop.py`
  - Result: compile success.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\runtime_smoke.py tools\verify_robot_desktop_runtime.py robot_ai\runtime.py robot_desktop.py robot_ai\bridge.py nanobot\webui\settings_api.py nanobot\webui\settings_routes.py nanobot\config\schema.py nanobot\audio\tts.py nanobot\audio\tts_registry.py nanobot\providers\tts.py tests\webui\test_settings_api.py`
  - Result: compile success.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_desktop.py tools\probe_robot_desktop_window.py robot_ai\runtime_smoke.py tools\verify_robot_desktop_runtime.py robot_ai\runtime.py robot_ai\bridge.py nanobot\webui\settings_api.py tests\robot_ai\test_desktop_window_probe.py`
  - Result: compile success.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\runtime_smoke.py robot_desktop.py tools\probe_robot_desktop_window.py tools\verify_robot_desktop_runtime.py tests\robot_ai\test_desktop_packaging_metadata.py tests\robot_ai\test_runtime_smoke.py`
  - Result: compile success.
  - `.venv-robot-desktop\Scripts\python.exe -m hatchling build -t wheel`
  - Result: not run to completion because `hatchling` is not installed in the controlled venv; refreshing the editable install to generate new console script `.exe` files was blocked by the current approval/usage limit.
- Next: once installation approval is available again, refresh `.venv-robot-desktop` editable install and verify generated `robot-desktop` / `robot-desktop-probe` scripts, then decide whether to connect the full WebUI transport.

### 2026-07-04

- Analyzed the legacy real-controller path and identified the safe first real-device slice: read-only ZMotion status access through the same backend boundary as the simulator.
- Implemented the first real-controller slice: `robot_ai/backends/zmotion_backend.py` now provides `ZMotionReadOnlyBackend`, lazy client connection, pose/status/alarm reads, ZMotion status-bit mode mapping, and explicit rejection for motion/control writes while real writes remain disabled.
- Added tests in `tests/robot_ai/test_zmotion_readonly_backend.py` with a fake ZMotion client, covering:
  - reading real-device pose/status without any write call;
  - mapping controller alarm bits and alarm detail codes;
  - rejecting `move_axis`, `home`, and `stop` with `real_control_disabled`.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_readonly_backend.py -v`
  - Result: 3 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 57 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\zmotion_backend.py tests\robot_ai\test_zmotion_readonly_backend.py`
  - Result: compile success.
- Next: add a configurable ZMotion client factory and a desktop/tool status path for read-only real-controller mode, still without enabling `IEEE(32)` trigger writes or real motion commands.
- Implemented the second real-controller slice: `robot_ai/backends/factory.py` now provides `RobotBackendConfig`, `create_robot_backend()`, environment-based backend mode defaults, and injectable ZMotion client factories.
- Connected the desktop bridge to backend creation: `RobotApi` now accepts a `backend_factory` and defaults through `create_robot_backend()`, so the same `get_robot_state()` API can expose simulated state or read-only real-controller state.
- Extended `tests/robot_ai/test_zmotion_readonly_backend.py` to cover:
  - creating `zmotion_readonly` through the backend factory;
  - returning read-only real-controller state through `RobotApi.get_robot_state()`.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_readonly_backend.py -v`
  - Result: 5 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 59 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\factory.py robot_ai\backends\zmotion_backend.py robot_ai\bridge.py tests\robot_ai\test_zmotion_readonly_backend.py`
  - Result: compile success.
- Next: implement a real ZMotion SDK client loader behind the factory, using an explicit SDK root/DLL path and keeping connection/status reads separate from all motion writes.
- Implemented the third real-controller slice: `robot_ai/backends/zmotion_sdk.py` now provides `ZMotionSdkClient`, `ZMotionSdkConfig`, SDK wrapper loading with a temporary DLL directory/PATH scope, `ZAux_OpenEth`/`ZAux_Close`, and read-only `ZAux_Modbus_Get4x_Float` / `ZAux_Modbus_Get4x_Long` wrappers.
- Extended `RobotBackendConfig` with explicit SDK path fields:
  - `ROBOT_ZMOTION_WRAPPER_PATH`
  - `ROBOT_ZMOTION_DLL_DIR`
- Updated `create_robot_backend()` so `zmotion_readonly` can now create a real SDK-backed read-only client when those paths are configured; injected test factories still work for deterministic tests.
- Extended `tests/robot_ai/test_zmotion_readonly_backend.py` to cover:
  - `ZMotionSdkClient` connection/read/disconnect calls against a fake vendor module;
  - factory creation of an SDK-backed read-only backend when wrapper/DLL paths are provided.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_readonly_backend.py -v`
  - Result: 7 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 61 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\zmotion_sdk.py robot_ai\backends\factory.py robot_ai\backends\zmotion_backend.py tests\robot_ai\test_zmotion_readonly_backend.py`
  - Result: compile success.
- Next: add a non-motion real-controller smoke verifier that loads the configured SDK paths, connects, reads pose/status once, prints JSON, and refuses to run unless explicitly invoked for read-only diagnostics.
