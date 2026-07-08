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
- Implemented the fourth real-controller slice: `robot_ai/zmotion_readonly_smoke.py` now provides a non-motion ZMotion read-only smoke verifier. It refuses to contact the controller unless `--read-only-diagnostics` is supplied, forces backend mode to `zmotion_readonly`, reads `get_state()` once, and reports structured JSON.
- Added `tools/verify_zmotion_readonly.py` plus package metadata for the `robot-zmotion-readonly-probe` console script.
- Added tests in `tests/robot_ai/test_zmotion_readonly_smoke.py`, covering:
  - refusal without explicit read-only diagnostics confirmation;
  - successful state read through an injected fake backend;
  - no calls to `move_axis`, `home`, or `stop`;
  - CLI/script presence and confirmation behavior.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_readonly_smoke.py tests\robot_ai\test_desktop_packaging_metadata.py -v`
  - Result: 6 passed.
  - `.venv-robot-desktop\Scripts\python.exe tools\verify_zmotion_readonly.py --json`
  - Result: expected non-zero safety refusal with state `readonly_diagnostics_confirmation_required`; no controller connection attempted.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 65 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\zmotion_readonly_smoke.py tools\verify_zmotion_readonly.py tests\robot_ai\test_zmotion_readonly_smoke.py tests\robot_ai\test_desktop_packaging_metadata.py`
  - Result: compile success.
- Next: document the real-controller environment variables and operator workflow, then wire desktop status display for read-only real-controller mode without enabling any `IEEE(32)` trigger writes.
- Implemented the fifth real-controller slice: `robot_ai/zmotion_readonly_smoke.py` now preflights required SDK configuration before creating a backend, returning `zmotion_readonly_configuration_missing` with explicit missing environment variable names and setup steps.
- Added `format_zmotion_readonly_setup_help()` so CLI and tests share the same operator-facing PowerShell workflow.
- Added `docs/zmotion_readonly_operator_workflow_2026-07-04.md`, documenting:
  - required `ROBOT_CONTROLLER_HOST`, `ROBOT_ZMOTION_WRAPPER_PATH`, and `ROBOT_ZMOTION_DLL_DIR`;
  - exact read-only diagnostic command;
  - expected JSON success/failure states;
  - current safety boundary: read-only SDK calls allowed, `IEEE(32)` and all Modbus/TABLE writes still disallowed.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_readonly_smoke.py -v`
  - Result: 7 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 68 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\zmotion_readonly_smoke.py tools\verify_zmotion_readonly.py tests\robot_ai\test_zmotion_readonly_smoke.py`
  - Result: compile success.
  - `.venv-robot-desktop\Scripts\python.exe tools\verify_zmotion_readonly.py --read-only-diagnostics --json`
  - Result: expected non-zero preflight result `zmotion_readonly_configuration_missing`; backend/controller connection was not attempted because SDK paths were not configured.
- Next: wire the desktop status display for `zmotion_readonly` so operators can see real-controller read-only state and configuration errors in the GUI, still without enabling motion writes.
- Implemented the sixth real-controller slice: desktop status now exposes backend metadata for operators.
- Updated `robot_ai/bridge.py` so `RobotApi.health()` and `RobotApi.get_robot_state()` include a `backend` summary with:
  - normalized backend mode;
  - controller host;
  - `real_readonly`;
  - `control_enabled`;
  - `configuration_ready`;
  - missing ZMotion SDK config keys;
  - operator-facing safety/status message.
- Updated `robot_desktop.py` so the desktop page refreshes `health()` automatically on `pywebviewready`, and the status button now calls the same health refresh path.
- Added tests in `tests/robot_ai/test_desktop_bridge.py` and `tests/robot_ai/test_desktop_html.py` covering:
  - simulation backend metadata;
  - `zmotion_readonly` metadata with missing SDK paths;
  - GUI startup health refresh wiring.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_desktop_bridge.py tests\robot_ai\test_desktop_html.py -v`
  - Result: 13 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 70 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\bridge.py robot_desktop.py tests\robot_ai\test_desktop_bridge.py tests\robot_ai\test_desktop_html.py`
  - Result: compile success.
- Next: add a desktop/runtime diagnostic path for `zmotion_readonly` that surfaces SDK configuration errors and disconnected-controller alarms in a compact operator status card, while still keeping real motion commands disabled.
- Implemented the seventh real-controller/desktop slice: `robot_desktop.py` now renders a compact operator status card above the raw JSON output.
- The status card shows:
  - backend mode;
  - control state (`enabled` or `read-only`);
  - configuration state (`ready` or missing SDK/env keys);
  - real-device connection/mode state;
  - backend safety/status message.
- Updated `refreshStatus()` so the first `health()` result updates the status card and still writes the full structured JSON into the diagnostic output area.
- Added tests in `tests/robot_ai/test_desktop_html.py` covering:
  - status card DOM IDs;
  - `renderOperatorStatus(result)` extraction of backend and robot state;
  - `refreshStatus()` invoking status-card rendering.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_desktop_html.py -v`
  - Result: 5 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 72 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_desktop.py tests\robot_ai\test_desktop_html.py`
  - Result: compile success.
- Next: refine real-controller diagnostics so SDK load failures, missing DLL paths, controller read failures, and alarm states are mapped to concise operator messages in the same desktop status path, still without enabling any real motion writes.
- Implemented the eighth real-controller/desktop diagnostic slice: `robot_ai/bridge.py` now maps read-only real-controller state into concise operator diagnostics for the desktop status card.
- Backend summaries now include:
  - `connected_real_device`;
  - `diagnostic_state`;
  - focused operator `message`.
- Added diagnostic mappings for:
  - `sdk_wrapper_missing`: ZMotion SDK wrapper path cannot be loaded;
  - `sdk_dll_dir_missing`: ZMotion DLL directory cannot be found;
  - `controller_read_failed`: SDK loads but controller status read fails;
  - `controller_alarm`: controller reports alarm bits/details;
  - `controller_disconnected`: read-only backend does not confirm a connected real device;
  - `readonly_connected`: read-only real-controller status is connected;
  - `configuration_missing`: SDK/env setup is incomplete;
  - `simulation`: simulator is active.
- Added tests in `tests/robot_ai/test_desktop_bridge.py` using fake read-only backend states to verify SDK wrapper failure, DLL directory failure, controller read failure, and controller alarm messages without loading a real DLL or contacting hardware.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_desktop_bridge.py -v`
  - Result: 13 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 75 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\bridge.py tests\robot_ai\test_desktop_bridge.py`
  - Result: compile success.
- Next: add a real-controller preflight endpoint/API method in the desktop bridge so the GUI can run the same explicit read-only diagnostics as `tools/verify_zmotion_readonly.py`, gated by a clear read-only confirmation flag and still with no motion writes.
- Implemented the ninth real-controller/desktop slice: the desktop bridge and GUI can now run the explicit ZMotion read-only diagnostic path.
- Updated `robot_ai/bridge.py` with `RobotApi.run_zmotion_readonly_diagnostics(confirmed_readonly_diagnostics=False)`.
  - It delegates to the same `run_zmotion_readonly_smoke()` path used by `tools/verify_zmotion_readonly.py`.
  - It passes the current `RobotBackendConfig`.
  - It enriches the returned data with the same backend summary used by the desktop status card.
  - It keeps the confirmation gate intact; without confirmation the result remains `readonly_diagnostics_confirmation_required`.
- Updated `robot_desktop.py` with a `只读诊断` button.
  - The button calls `window.confirm()` before invoking the bridge API.
  - The confirmation text states that the action only reads controller status and does not write `IEEE(32)`.
  - Results update both the operator status card and the raw JSON output area.
- Added tests in `tests/robot_ai/test_desktop_bridge.py` and `tests/robot_ai/test_desktop_html.py` covering:
  - unconfirmed diagnostic calls returning the original safety refusal;
  - confirmed calls delegating to an injected runner and adding backend summary for the status card;
  - GUI wiring for the confirmation dialog and bridge API call.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_desktop_bridge.py tests\robot_ai\test_desktop_html.py -v`
  - Result: 21 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 78 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\bridge.py robot_desktop.py tests\robot_ai\test_desktop_bridge.py tests\robot_ai\test_desktop_html.py`
  - Result: compile success.
- Next: once real SDK paths and controller network are available, run the GUI read-only diagnostic against the actual controller and record the observed status/alarms; after that, design the separate pending-confirm motion-write path, still disabled by default.
- Implemented the tenth real-controller slice: a dry-run ZMotion motion write planner now exists without enabling real writes.
- Added `robot_ai/backends/zmotion_write_plan.py` with:
  - legacy command parameter start `IEEE(0)`;
  - trigger register `IEEE(32)`;
  - echo/checkback start `IEEE(280)`;
  - accept/result register `IEEE(312)`;
  - `ZMotionWritePlanner.plan_move_axis()` for auditable dry-run plans;
  - blockers for missing command code, missing operator confirmation, disabled real writes, disconnected real device, non-idle controller, controller alarms, and unknown axes.
- Added `docs/zmotion_motion_write_dry_run_plan_2026-07-04.md`, documenting that:
  - this is not an executable writer;
  - no SDK write calls are made;
  - no `IEEE(32)` trigger is executed;
  - old command codes and parameter order still need confirmation before any real write path is implemented.
- Added tests in `tests/robot_ai/test_zmotion_write_plan.py` covering:
  - default blocking behavior;
  - legacy register envelope data;
  - safety blockers for alarm/disconnected controller state.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_write_plan.py -v`
  - Result: 3 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 81 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\zmotion_write_plan.py tests\robot_ai\test_zmotion_write_plan.py`
  - Result: compile success.
- Next: confirm the legacy real-motion command codes and parameter order from old code/vendor docs, then add an SDK write-client interface that is still disabled behind the same pending-confirm gate.
- Implemented the eleventh real-controller slice: `ZMotionSdkClient` now has guarded SDK write wrappers, still disconnected from all app motion paths.
- Added `ModbusWriteRequest` in `robot_ai/backends/zmotion_sdk.py`.
- Added guarded methods:
  - `write_modbus_float()`;
  - `write_modbus_long()`.
- Both write methods require:
  - `allow_real_motion_writes=True`;
  - `confirmed_real_motion=True`;
  - an active SDK connection.
- By default, they raise `ZMotionSdkError` before calling the vendor SDK, so existing application paths remain read-only.
- Added tests in `tests/robot_ai/test_zmotion_sdk_write_guard.py` with a fake SDK device, covering:
  - default write calls are blocked and do not call `ZAux_Modbus_Set4x_*`;
  - `allow_real_motion_writes=True` without operator confirmation is still blocked;
  - only the explicitly unlocked test path calls fake `ZAux_Modbus_Set4x_Float` and `ZAux_Modbus_Set4x_Long`.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_sdk_write_guard.py -v`
  - Result: 3 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 84 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\zmotion_sdk.py tests\robot_ai\test_zmotion_sdk_write_guard.py`
  - Result: compile success.
- Next: confirm legacy command codes/parameter order and then add an executor that can consume `ZMotionMotionWritePlan` and call the guarded SDK write wrappers only when all plan blockers are clear and all confirmation gates are explicitly set.
- Implemented the twelfth real-controller slice: a guarded write-plan executor now exists, but remains isolated from the application and real hardware entry points.
- Added `robot_ai/backends/zmotion_write_executor.py` with `ZMotionWriteExecutor`.
- The executor:
  - rejects plans that are not executable or still contain blockers;
  - remains disabled unless `allow_real_motion_writes=True` is supplied again at execution time;
  - requires a second runtime `confirmed_real_motion=True` gate;
  - submits parameter writes in plan order;
  - submits the `IEEE(32)` trigger only after all parameter writes succeed;
  - stops immediately and does not submit the trigger if any parameter write fails;
  - returns structured `ToolResult` data for blocked, disabled, confirmation-required, submitted, and failed states.
- The executor is not imported by `RobotApi`, `ZMotionReadOnlyBackend`, `RobotToolFacade`, the nanobot tool adapter, or the desktop GUI.
- Added `tests/robot_ai/test_zmotion_write_executor.py` with a fake write client covering:
  - blocked plans produce zero writes;
  - the executor is disabled by default;
  - runtime operator confirmation is mandatory;
  - parameter VRs `0`, `1`, and `2` are written before trigger VR `32`;
  - a parameter failure prevents the trigger write.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_write_executor.py -v`
  - Result: 5 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 89 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\zmotion_write_executor.py tests\robot_ai\test_zmotion_write_executor.py`
  - Result: compile success.
- Next: add a separate post-write verifier for the legacy echo range beginning at `IEEE(280)` and accept/result register `IEEE(312)`, using fake reads first. Keep the executor disconnected from all application motion paths until legacy command codes, parameter order, controller idle semantics, and actual hardware behavior have been confirmed.
- Performed a direct real-hardware read-only test against controller `10.168.3.21`.
- The legacy 64-bit ZMotion SDK loaded successfully, `ZAux_OpenEth` succeeded, and three consecutive real-controller samples were stable.
- Observed real state:
  - mode `idle`;
  - no reported alarms;
  - pose `[900, 0, 1000, 0, 0, 0]`;
  - `LONG(34)=268435584`;
  - `LONG(36)=0`;
  - `LONG(38)=0`;
  - `IEEE(56)=270`;
  - `IEEE(312)=0`;
  - `IEEE(324)=108`.
- Confirmed the real echo range beginning at `IEEE(280)` is readable and stable.
- Found a critical incompatibility before motion:
  - the current dry-run planner uses parameter VRs `0`, `1`, and `2`;
  - the legacy real protocol uses float VRs `0`, `2`, `4`, and so on;
  - legacy `Func108` requires a complete absolute Cartesian pose payload, not the current axis-index/delta draft.
- Read the controller safety block at `IEEE(1700...)`; radius and Z limits are all zero, so effective controller-side workspace boundaries are not configured.
- No motion write or `IEEE(32)` trigger was issued.
- Added `docs/zmotion_real_hardware_test_2026-07-04.md` with the real values, protocol findings, and motion-test blockers.
- Next: replace the incorrect draft payload with the confirmed legacy `Func108` even-address absolute-pose protocol, add echo and immediate pre-trigger state verification, then require explicit on-site clearance/emergency-stop confirmation and a specified low-speed target before the first physical motion.
- Implemented the thirteenth real-controller slice: the provisional planner was replaced by the confirmed restricted controller protocol.
- The supported function set is now deliberately limited to:
  - `Func104`: emergency stop, emergency-stop release, pause, resume, stop current command, and cancel release;
  - `Func108`: Cartesian linear interpolation only;
  - `Func110`: delay;
  - `Func120`: allowed-channel IO control.
- All other functions are unsupported by the new planner.
- `robot_ai/backends/zmotion_write_plan.py` now:
  - writes IEEE float parameters at even VR addresses;
  - builds complete Func108 absolute-pose payloads at `IEEE(0), IEEE(2), ..., IEEE(30)`;
  - converts an axis-relative request into a complete absolute target pose;
  - fixes Func108 `move_type` to `0` for linear interpolation;
  - builds exact Func104, Func110, and Func120 payloads;
  - records expected echoes at source VR plus `280`;
  - blocks invalid targets, percentages, delays, IO channels, unsupported system actions, unsafe motion state, and missing execution gates.
- Func104 safety controls do not use the motion idle/alarm blocker, so emergency stop, pause, and stop-current remain available when the controller is moving or reporting an alarm.
- `robot_ai/backends/zmotion_write_executor.py` now:
  - submits all parameter writes before any verification read;
  - verifies every expected command echo;
  - reads `IEEE(312)`, `LONG(34)`, `LONG(36)`, and `LONG(38)` immediately before the trigger;
  - blocks the trigger on echo mismatch, read failure, alarm, emergency stop, pause, non-ready status, nonzero system state, or nonzero accept/result state for Func108/110/120;
  - writes `IEEE(32)` only after all checks pass;
  - polls command acceptance and the function-specific `LONG(34)` state after the trigger;
  - validates Func104 emergency-stop/pause/cancel state bits;
  - waits for Func108/110/120 completion or returns a structured timeout/error;
  - reads `IEEE(1612...)` after Func108 completion and verifies the final pose.
- Added `robot_ai/backends/zmotion_sequence.py`.
  - It implements the requested continuous behavior as ordered Func108 segments.
  - Every segment uses the same single-command executor.
  - It stops on the first failed segment.
  - Func11, Func112, TABLE writes, and controller path buffering are not used.
- Added the approved design and implementation plan:
  - `docs/superpowers/specs/2026-07-04-zmotion-supported-functions-design.md`;
  - `docs/superpowers/plans/2026-07-04-zmotion-supported-functions.md`.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_write_plan.py tests\robot_ai\test_zmotion_write_executor.py tests\robot_ai\test_zmotion_sequence.py -v`
  - Result: 27 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 108 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\backends\zmotion_write_plan.py robot_ai\backends\zmotion_write_executor.py robot_ai\backends\zmotion_sequence.py tests\robot_ai\test_zmotion_write_plan.py tests\robot_ai\test_zmotion_write_executor.py tests\robot_ai\test_zmotion_sequence.py`
  - Result: compile success.
- The write executor and sequence runner remain disconnected from `RobotApi`, the desktop GUI, and the nanobot tool adapter. No real controller write or physical motion occurred during this slice.
- Next: expose a separate operator-only real-hardware test command for the restricted function set. It must require on-site clearance, reachable emergency stop, explicit action/target, low speed, configured software workspace limits, and a final confirmation immediately before execution.
- Implemented the fourteenth real-controller slice: an isolated, dry-run-by-default operator CLI now exists.
- Added `robot_ai/zmotion_operator_control.py` with:
  - `ZMotionOperatorRequest`;
  - explicit real-execution confirmation gates;
  - software Cartesian workspace limits;
  - first-test maximum delta of `5`;
  - first-test speed/acceleration/deceleration maximum of `5%`;
  - one-connection SDK lifecycle;
  - read-only state collection before planning;
  - Func104/108/110/120 plan selection;
  - dry-run plan output without constructing the executor;
  - real execution delegation to the guarded executor only after every confirmation passes.
- Real execution requires all of:
  - `--execute-real`;
  - `--confirm-work-area-clear`;
  - `--confirm-estop-ready`;
  - `--confirmation-code EXECUTE_ZMOTION_REAL`.
- Added `tools/verify_zmotion_control.py` with subcommands:
  - `system`;
  - `move-axis`;
  - `delay`;
  - `io`.
- Func108 CLI calls require explicit R and Z software limits on every invocation. There are no default workspace limits.
- The CLI remains disconnected from `RobotApi`, the desktop GUI, and the nanobot agent tool.
- Added design and implementation documents:
  - `docs/superpowers/specs/2026-07-04-zmotion-operator-cli-design.md`;
  - `docs/superpowers/plans/2026-07-04-zmotion-operator-cli.md`.
- Verified:
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai\test_zmotion_operator_control.py tests\robot_ai\test_zmotion_operator_cli.py -v`
  - Result: 21 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m pytest tests\robot_ai -v`
  - Result: 129 passed.
  - `.venv-robot-desktop\Scripts\python.exe -m py_compile robot_ai\zmotion_operator_control.py tools\verify_zmotion_control.py tests\robot_ai\test_zmotion_operator_control.py tests\robot_ai\test_zmotion_operator_cli.py`
  - Result: compile success.
- Ran the new CLI in its default dry-run mode against the real controller:
  - real state remained `idle`;
  - real pose was `[900, 0, 1000, 0, 0, 0]`;
  - requested dry-run was axis `z`, delta `-1`, speed/acceleration/deceleration `5%`;
  - supplied workspace was radius `800..1000`, Z `900..1100`;
  - generated target was `[900, 0, 999, 0, 0, 0]`;
  - the plan contained the expected even-address Func108 payload and execution blockers;
  - no parameter write and no `IEEE(32)` trigger occurred.
- Next: before the first physical Func108 motion, require the operator to confirm the same workspace and target while physically present at the robot with the emergency stop reachable. Then run the CLI with all four execution confirmations and capture before/after state, echo, completion, and pose evidence.
