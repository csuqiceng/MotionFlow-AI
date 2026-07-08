# ZMotion Read-Only Operator Workflow

> Date: 2026-07-04
> Scope: connect Nanobot Robot AI to the real lower controller for diagnostics only.

## What This Enables

This workflow verifies that the desktop project can load the legacy ZMotion SDK wrapper, open the controller at the configured host, and read robot pose/status once.

It does not enable real motion. The verifier does not call `move_axis`, `home`, `stop`, command parameter writes, or the `IEEE(32)` trigger.

## Required Inputs

- `ROBOT_CONTROLLER_HOST`: controller IP address. The legacy project default is `10.168.3.21`.
- `ROBOT_ZMOTION_WRAPPER_PATH`: full path to `zauxdllPython.py` from the legacy project or vendor SDK.
- `ROBOT_ZMOTION_DLL_DIR`: directory containing the matching `zauxdll.dll` and related SDK files.

## PowerShell Setup

Run these commands from `C:\Users\KY\Desktop\yjcao\nanobot_robot_ai\nanobot-main-1`:

```powershell
$env:ROBOT_AI_BACKEND="zmotion_readonly"
$env:ROBOT_CONTROLLER_HOST="10.168.3.21"
$env:ROBOT_ZMOTION_WRAPPER_PATH="C:\path\to\zauxdllPython.py"
$env:ROBOT_ZMOTION_DLL_DIR="C:\path\to\zauxdll\directory"
```

Then run the explicit read-only diagnostic:

```powershell
.venv-robot-desktop\Scripts\python.exe tools\verify_zmotion_readonly.py --read-only-diagnostics --json
```

The `--read-only-diagnostics` flag is required on purpose. Without it, the tool exits before trying to create a backend or contact the controller.

## Expected Result

When the SDK paths and controller are reachable, the JSON result should report:

- `ok: true`
- `state: zmotion_readonly_smoke_passed`
- `data.robot_state.connected_real_device: true`
- current axes under `data.robot_state.axes_mm`

If configuration is missing, the tool returns:

- `ok: false`
- `state: zmotion_readonly_configuration_missing`
- `data.missing` with the missing environment variable names.

If the SDK loads but the controller cannot be read, the tool returns a structured failure and includes the disconnected robot state or SDK error detail.

## Safety Boundary

Current real-controller support is status-only:

- allowed: `ZAux_OpenEth`, `ZAux_Close`, `ZAux_Modbus_Get4x_Float`, `ZAux_Modbus_Get4x_Long`
- not allowed yet: `ZAux_Modbus_Set4x_Float`, `ZAux_Modbus_Set4x_Long`, TABLE writes, `IEEE(32)` trigger writes, or any production motion command

Real motion should only be added after a separate pending-confirm gate, safety-policy integration, command echo/accept verification, and physical emergency-stop procedure are documented and tested.
