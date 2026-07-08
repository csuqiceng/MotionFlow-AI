# ZMotion Supported Functions Design

Date: 2026-07-04

## Goal

Replace the provisional ZMotion planner with the confirmed legacy register
protocol while deliberately limiting the controller surface.

The supported command set is:

- `Func104`: emergency stop, emergency-stop release, pause, resume, stop current
  command, and cancel release
- `Func108`: Cartesian linear interpolation
- `Func110`: delay
- `Func120`: digital input/output control

All other controller functions are unsupported for now.

## Safety Boundary

Implementation and automated tests use fake SDK clients only. Merely creating a
plan never writes to the controller.

Real execution remains disabled by default and requires:

- an executable plan with no blockers;
- the runtime real-write enable flag;
- explicit operator confirmation;
- a connected controller;
- successful command echo verification before the trigger;
- successful immediate status verification before the trigger.

Func108, Func110, and Func120 additionally require an idle, alarm-free
controller. Func104 emergency stop, pause, and stop-current controls must remain
available while the controller is moving or reporting an alarm. Release/resume
controls use action-specific state checks instead of the motion idle gate.

The current controller reports zero radius and Z workspace limits. Physical
motion must remain blocked until an operator confirms the cleared work area,
reachable emergency stop, and an explicit low-speed target.

## Common Protocol

All command parameters are IEEE float values at even-numbered VR addresses.

- parameter source range: `IEEE(0)`, `IEEE(2)`, ..., `IEEE(30)`
- trigger: `IEEE(32)=1`
- parameter echo range: source VR plus `280`
- accept/result: `IEEE(312)`
- status: `LONG(34)`
- system state: `LONG(36)`
- alarm detail: `LONG(38)`
- current function: `IEEE(324)`

The executor writes parameters first. It then verifies every expected echo,
rechecks status, and only then writes the trigger. Any failed write, echo
mismatch, unsafe status, or read error prevents the trigger.

## Func104 System Control

Register layout:

| VR | Meaning |
|---:|---|
| 0 | function number `104` |
| 2 | emergency-stop control |
| 4 | pause control |
| 6 | cancel/current-command control |
| 8 | reset control, always `0` in this supported surface |

Supported actions:

| Action | VR 2 | VR 4 | VR 6 |
|---|---:|---:|---:|
| emergency stop | 1 | 0 | 0 |
| release emergency stop | 2 | 0 | 0 |
| pause | 0 | 1 | 0 |
| resume | 0 | 2 | 0 |
| stop current command | 0 | 0 | 1 |
| release cancel | 0 | 0 | 2 |

Only one control field may be nonzero in a plan.

## Func108 Linear Interpolation

Register layout:

| VR | Meaning |
|---:|---|
| 0 | function number `108` |
| 2..12 | absolute `x, y, z, rx, ry, rz` target pose |
| 14 | speed percentage |
| 16 | acceleration percentage |
| 18 | deceleration percentage |
| 20 | stop field, normally `0` |
| 22..28 | position/speed/acceleration/deceleration flags |
| 30 | move type, fixed to `0` for linear interpolation |

The public axis-relative operation reads the current complete pose, applies one
delta, and produces a complete absolute Func108 target. It does not send an axis
index/delta payload.

Targets and motion percentages must be finite numbers. Speed, acceleration, and
deceleration must be positive and within the configured software limits.

## Sequential Func108 Path

Continuous interpolation means an ordered sequence of Func108 linear segments.
It does not use Func11, Func112, TABLE writes, or controller path buffering.

For each path point:

1. Build a complete absolute Func108 plan.
2. Verify safety and command echo.
3. Trigger the segment.
4. Wait for acceptance and completion.
5. Re-read pose/status.
6. Continue only when the segment completed without alarm or cancellation.

The sequence stops on the first failure. Short pauses between path points are
accepted by design.

## Func110 Delay

Register layout:

| VR | Meaning |
|---:|---|
| 0 | function number `110` |
| 6 | delay in seconds |

Delay must be finite and greater than zero.

## Func120 IO

Register layout:

| VR | Meaning |
|---:|---|
| 0 | function number `120` |
| 2 | IO number |
| 4 | action, `1` for on and `0` for off |

The IO number must be a configured allowed channel. Arbitrary channels are
blocked.

## Components

`zmotion_write_plan.py` owns command schemas, validation, blockers, parameter
writes, expected echoes, and trigger metadata.

`zmotion_write_executor.py` owns runtime gates, ordered parameter submission,
echo verification, immediate pre-trigger state verification, trigger submission,
and structured failure results.

A sequence runner owns ordered Func108 path execution and stop-on-first-failure
behavior. It does not bypass the single-command executor.

No planner or executor is exposed through the desktop bridge or nanobot tool
adapter in this slice.

## Error States

Structured failures distinguish:

- unsupported function or action;
- invalid parameter;
- blocked controller state;
- execution disabled;
- operator confirmation missing;
- parameter write failure;
- echo mismatch or read failure;
- unsafe pre-trigger state;
- trigger failure;
- acceptance timeout;
- command error/alarm;
- path segment failure.

All failures include the action and relevant VR/status data without silently
continuing.

## Tests

Automated tests cover:

- exact even-address payloads and echoes for Func104/108/110/120;
- unsupported functions/actions;
- relative-axis conversion to a complete absolute Func108 pose;
- fixed Func108 linear `move_type=0`;
- trigger suppression on write, echo, or status failure;
- trigger ordering after echo and state checks;
- sequential Func108 ordering;
- sequence stop on first failed segment;
- no imports from the application, desktop bridge, or nanobot tool path.

Full `tests/robot_ai` regression and Python compile checks are required.
