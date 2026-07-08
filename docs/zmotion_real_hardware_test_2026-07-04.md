# ZMotion Real Hardware Test Record

Date: 2026-07-04

Controller: `10.168.3.21`

## Scope

The Nanobot Robot AI source connected directly to the real ZMotion controller
through the legacy 64-bit `zauxdllPython.py` and `zauxdll.dll`.

This test used SDK connect and read calls only. It did not call either SDK write
method and did not write the `IEEE(32)` trigger.

## Connection Result

- SDK wrapper found: yes
- SDK DLL found: yes
- `ZAux_OpenEth`: success
- Three consecutive controller samples: success
- Controller mode: idle
- Real device connected: yes
- Alarm list: empty

## Stable Real Values

All three samples returned the same values:

- `LONG(34)`: `268435584`
- `LONG(36)`: `0`
- `LONG(38)`: `0`
- `IEEE(56)`: `270`
- `IEEE(312)`: `0`
- `IEEE(324)`: `108`
- actual pose `IEEE(1612...)`: `[900, 0, 1000, 0, 0, 0]`
- command pose `IEEE(1512...)`: `[900, 0, 1000, 0, 0, 0]`

The command echo range was also stable:

```text
280=108, 282=900, 284=0, 286=1000,
288=0, 290=0, 292=0,
294=50, 296=50, 298=50,
300=0, 302=0, 304=0, 306=0, 308=0, 310=0
```

## Motion-Test Blockers Found

1. The current Nanobot dry-run planner uses parameter VRs `0`, `1`, and `2`.
   The real legacy protocol uses float parameter VRs `0`, `2`, `4`, and so on
   through `30`.
2. The current `move_axis` draft treats the command as an axis index plus a
   delta. The legacy Cartesian protocol uses `Func108` with a complete absolute
   pose, followed by speed, acceleration, deceleration, fuzzy flags, stop, and
   move type fields.
3. Real controller safety limits at `IEEE(1700...)` reported:
   - radius minimum/maximum: `0 / 0`
   - Z minimum/maximum: `0 / 0`
   - speed/acceleration/deceleration maximum: `80 / 80 / 80`
4. Because the controller has no effective radius or Z workspace limits, a
   motion command currently lacks a controller-side workspace boundary.
5. Legacy logs contain an earlier motion attempt that ended with an alarm and
   communication abnormal state. This reinforces the need to correct and
   verify the protocol before a new motion trigger.

## Decision

Real communication and readback are proven. Real motion was not triggered
because the current write plan does not match the confirmed protocol and the
controller workspace limits are not configured.

Before physical motion:

1. Replace the draft `move_axis` payload with a confirmed `Func108` absolute
   pose payload using even-numbered VR addresses.
2. Verify every parameter against `IEEE(280...)` before writing `IEEE(32)`.
3. Re-read `LONG(34)`, `LONG(36)`, `LONG(38)`, and `IEEE(312)` immediately
   before the trigger.
4. Require an operator to confirm that the work area is clear and the physical
   emergency stop is reachable.
5. Use a separately specified low-speed, small-distance test target.

## Follow-Up Implementation

The first three software prerequisites above are now implemented in the isolated
planner/executor path:

- Func108 uses a complete absolute pose at even VR addresses;
- expected command echoes are checked before the trigger;
- immediate accept/status/system/alarm reads are checked before the trigger.
- command acceptance and function-specific completion are polled after the
  trigger;
- Func104 action state bits are verified;
- Func108 final pose is read and compared with the target;
- sequential Func108 execution cannot advance until the preceding segment
  completes successfully.

The path is still not connected to the application or a real-hardware command
entry point. Physical motion remains pending configured software workspace
limits, operator-site confirmation, and an explicit low-speed target.

## Operator CLI Dry Run

The isolated operator CLI was subsequently run against the real controller in
default dry-run mode:

```text
command: move-axis
axis: z
delta: -1
speed/acceleration/deceleration: 5/5/5 percent
software radius: 800..1000
software Z: 900..1100
```

Observed state:

- controller mode: idle;
- alarms: none;
- current pose: `[900, 0, 1000, 0, 0, 0]`;
- planned target: `[900, 0, 999, 0, 0, 0]`.

The generated plan used Func108 and VR addresses `0, 2, ..., 30`. It remained
blocked by `operator_confirmation_missing` and `real_motion_writes_disabled`.
No SDK write method was called and `IEEE(32)` was not triggered.
