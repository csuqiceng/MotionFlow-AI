# Robot Auto-Execution Mode Persistence Design

## Goal

Keep the robot execution policy at `auto_after_safety_check` across WebUI and CLI configuration saves. A command that passes the existing L1 safety gate executes on the connected real controller without a separate human-confirmation step.

## Scope

- Add the execution mode to the typed `ToolsConfig` schema.
- Accept both `executionMode` and `execution_mode` when loading existing configuration.
- Persist the canonical camelCase key used by the rest of the configuration serializer.
- Resolve the execution-mode file through nanobot's active configuration path rather than hard-coding `~/.nanobot/config.json`.
- Keep `dry_run_only` as the fail-safe fallback for missing, invalid, or unreadable configuration.
- Set the active configuration to `auto_after_safety_check` and restart the gateway so import-time mode constants refresh.

## Runtime Behavior

The LLM robot tool builds a request with real execution enabled only when the resolved mode is `auto_after_safety_check`. The existing workspace-bound, alarm, emergency-stop, limit, and controller checks remain mandatory. A failed check rejects the request; a passed check writes directly to the controller without manual confirmation.

`manual_confirm` and `dry_run_only` remain supported modes. This change does not send a movement command during deployment or verification.

## Tests and Verification

Regression tests will first demonstrate that an execution-mode setting is lost by the current typed configuration round trip and that the mode reader misses the active config path/camelCase key. The implementation will then make those tests pass.

Verification will cover:

- schema load/save round trip;
- snake_case backward compatibility;
- active config path resolution;
- invalid/missing values falling back to `dry_run_only`;
- focused robot execution-mode tests;
- runtime `/api/robot/status` reporting `auto_after_safety_check` after restart, without issuing motion.
