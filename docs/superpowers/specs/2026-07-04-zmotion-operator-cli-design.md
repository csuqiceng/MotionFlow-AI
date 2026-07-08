# ZMotion Operator CLI Design

Date: 2026-07-04

## Goal

Provide a separate command-line entry point for controlled real-hardware testing
of the restricted ZMotion command set without exposing writes through the
desktop GUI, RobotApi, or nanobot agent.

## Supported Commands

The CLI supports only:

- Func104 system controls:
  - emergency stop;
  - emergency-stop release;
  - pause;
  - resume;
  - stop current command;
  - cancel release.
- Func108 single-axis relative linear motion.
- Func110 delay.
- Func120 allowed-channel IO on/off.

No other controller function is accepted.

## Modes

The default mode is dry-run.

Dry-run mode:

- loads SDK configuration;
- connects to the real controller for read-only state collection;
- builds and prints the command plan;
- performs no parameter writes;
- never writes `IEEE(32)`.

Real execution additionally requires every one of:

- `--execute-real`;
- `--confirm-work-area-clear`;
- `--confirm-estop-ready`;
- `--confirmation-code EXECUTE_ZMOTION_REAL`.

Missing or incorrect confirmation returns a structured refusal before any write.

## CLI Shape

Executable:

```powershell
.venv-robot-desktop\Scripts\python.exe tools\verify_zmotion_control.py <command> [options] --json
```

Shared SDK options:

- `--host`;
- `--wrapper-path`;
- `--dll-dir`;
- environment fallbacks matching the read-only verifier.

Subcommands:

```text
system --action <emergency_stop|release_emergency_stop|pause|resume|stop_current|release_cancel>
move-axis --axis <x|y|z|rx|ry|rz> --delta <number>
          --speed-pct <number> --acceleration-pct <number> --deceleration-pct <number>
          --r-min <number> --r-max <number> --z-min <number> --z-max <number>
delay --seconds <number>
io --io-number <integer> --state <on|off> --allowed-io <comma-separated integers>
```

## Func108 First-Test Limits

The operator must provide software workspace limits on every motion invocation.
There are no fallback limits because the real controller currently reports zero
radius and Z bounds.

Validation:

- `r_min >= 0`;
- `r_max > r_min`;
- `z_max > z_min`;
- target radius `sqrt(x*x + y*y)` is within `[r_min, r_max]`;
- target Z is within `[z_min, z_max]`;
- current and target poses contain six finite values;
- `abs(delta) <= 5`;
- speed, acceleration, and deceleration are each in `(0, 5]`;
- controller is connected, idle, ready, and alarm-free.

The motion plan is a complete absolute Func108 pose with `move_type=0`.

## Runtime Flow

1. Parse arguments without contacting hardware.
2. Validate SDK configuration and confirmation syntax.
3. Create one `ZMotionSdkClient`.
4. Connect once.
5. Read current controller state.
6. Build the restricted command plan.
7. For Func108, apply software workspace validation to the target.
8. In dry-run mode, return the plan and disconnect.
9. In real mode, pass the plan to `ZMotionWriteExecutor`.
10. Wait for echo verification, trigger, acceptance, completion, and final pose
    verification.
11. Disconnect in a `finally` block.

Any failure returns a structured `ToolResult` dictionary.

## Component Boundaries

`robot_ai/zmotion_operator_control.py` owns:

- operator confirmation gates;
- software workspace limits;
- current-state collection;
- plan selection;
- SDK client lifecycle;
- dry-run versus execution behavior.

`tools/verify_zmotion_control.py` owns only argument parsing, JSON/text output,
and process exit status.

Existing planner, executor, SDK client, and read-only backend remain focused and
are reused without GUI or agent integration.

## Error States

The CLI distinguishes:

- configuration missing;
- execution confirmation missing;
- connection/state read failure;
- invalid workspace limits;
- target outside workspace;
- first-test delta or percentage exceeded;
- unsupported action/function;
- disallowed IO channel;
- blocked plan;
- executor echo/status/completion/pose failures.

All pre-execution failures happen before the first SDK write.

## Testing

Automated tests use injected fake SDK clients and cover:

- default dry-run performs reads but no writes;
- every confirmation gate is required for real execution;
- valid Func104/108/110/120 plans reach the injected executor;
- missing SDK configuration fails before client creation;
- invalid workspace limits and out-of-bounds targets fail before writes;
- delta and motion percentages above first-test limits fail;
- disallowed IO channels fail;
- disconnect runs after success and failure;
- CLI argument wiring and tool script existence.

No automated test connects to the real controller.
