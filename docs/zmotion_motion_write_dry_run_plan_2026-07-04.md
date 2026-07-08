# ZMotion Motion Write Dry-Run Plan

> Date: 2026-07-04
> Scope: prepare an auditable write envelope for future real motion control. This is not an executable controller writer.

## Current Status

`robot_ai.backends.zmotion_write_plan` can build a dry-run plan for future ZMotion motion writes. The plan is deliberately blocked by default and is not connected to the real backend.

No SDK write calls are made. No `ZAux_Modbus_Set4x_Float`, `ZAux_Modbus_Set4x_Long`, TABLE write, or `IEEE(32)` trigger is executed.

## Legacy Register Envelope

The old project analysis identified this command envelope:

- command parameters: `IEEE(0)` through `IEEE(30)`
- motion trigger: `IEEE(32)=1`
- command echo/checkback: starts at `IEEE(280)`
- command accept/result: `IEEE(312)`

The dry-run planner represents that envelope as data:

- `parameter_writes`
- `trigger_write`
- `echo_start_vr`
- `accept_vr`
- `blockers`
- `executable`

## Safety Gates

A plan is blocked unless all of these are true:

- the concrete legacy motion `command_code` has been provided;
- the operator has confirmed real motion;
- the build/runtime explicitly allows real motion writes;
- the real device is connected;
- the controller mode is `idle`;
- there are no controller alarms.

The normal application path still has real writes disabled. The planner is only groundwork for review, testing, and later implementation.

## Next Evidence Needed

Before any real motion write can be enabled, the old command codes and parameter order must be confirmed against the legacy code or vendor documentation. Then a separate implementation must add:

- pending-confirm UI/bridge gate;
- safety policy validation before building writes;
- SDK write client methods;
- echo and accept verification;
- timeout/error handling;
- a physical emergency-stop operating procedure.
