/**
 * Robot operator UI shared types.
 *
 * The execution-mode / safety / pose / motion shape here is the canonical
 * display contract between the status hook, the normalization helper, and the
 * operator layout panels. Anything not provided by the backend is left as
 * ``null`` / ``"unknown"`` so the UI can render an honest "-" instead of
 * fabricating safety state.
 */

export type RobotExecutionMode =
  | "dry_run_only"
  | "auto_after_safety_check"
  | "manual_confirm"
  | "unknown";

export type RobotSafetyValue = "ok" | "active" | "unknown";

export type RobotAlarmValue = "none" | "active" | "unknown";

export interface RobotPoseSnapshot {
  x: number | null;
  y: number | null;
  z: number | null;
  rx: number | null;
  ry: number | null;
  rz: number | null;
}

export interface RobotDisplaySnapshot {
  connection: {
    connected: boolean;
    label: string;
  };
  safety: {
    estop: RobotSafetyValue;
    pause: "ok" | "paused" | "unknown";
    alarm: RobotAlarmValue;
    cancelLatch: boolean;
  };
  pose: RobotPoseSnapshot;
  joints: Array<number | null>;
  motion: {
    speedPct: number | null;
    progressPct: number | null;
  };
  task: {
    current: string | null;
    mode: string;
    executionMode: RobotExecutionMode;
  };
  raw: unknown;
}

/**
 * Shape returned by ``/api/robot/status``. The gateway always returns a
 * ``RobotResult`` envelope (``ok``/``state``/``data``/``errors``); the other
 * endpoints re-use the same envelope but place plan/result fields under
 * ``data`` or at the top level. ``RobotStatusResult`` is the read-only status
 * subset and is the only contract ``normalizeRobotStatusResult`` depends on.
 */
export interface RobotStatusResult {
  ok: boolean;
  state?: string;
  message?: string;
  data?: Record<string, unknown>;
  errors?: unknown[];
}

/**
 * Narrows an unknown value to a known execution mode (excluding ``"unknown"``,
 * which is the fallback the normalizer assigns when the backend omits or sends
 * a value outside the known set).
 */
export function isRobotExecutionMode(
  value: unknown,
): value is Exclude<RobotExecutionMode, "unknown"> {
  return (
    value === "dry_run_only" ||
    value === "auto_after_safety_check" ||
    value === "manual_confirm"
  );
}
