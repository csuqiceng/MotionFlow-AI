import type { RobotDisplaySnapshot, RobotExecutionMode, RobotStatusResult } from "./types";
import { isRobotExecutionMode } from "./types";

/** Canonical pose axis order, also consumed by the left status panel. */
export const ROBOT_POSE_AXES = ["x", "y", "z", "rx", "ry", "rz"] as const;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asNumberOrNull(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim().length > 0) {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  }
  return null;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === "string" ? item : ""))
      .filter((item) => item.length > 0);
  }
  if (typeof value === "string" && value.length > 0) return [value];
  return [];
}

function normalizeExecutionMode(value: unknown): RobotExecutionMode {
  return isRobotExecutionMode(value) ? value : "unknown";
}

/**
 * Project a raw ``robot_state`` dict into a UI-friendly snapshot.
 *
 * Honest-null policy: anything the backend did not send becomes ``null`` /
 * ``"unknown"`` so the UI can render "-" rather than guess. Safety (estop/
 * pause) is inferred from ``alarms`` / ``mode`` — which the backend derives
 * from the ESTOP/PAUSED status bits — so when connected and the active signal
 * is absent, the state is reliably ``"ok"`` (not ``"unknown"``). ``"unknown"``
 * is reserved for disconnected status or genuinely ambiguous cases (e.g.
 * pause hidden behind an alarm).
 *
 * This is the SINGLE normalization path for robot state — shared by the operator
 * console (via :func:`normalizeRobotStatusResult`) and the legacy
 * ``RobotControlPanel`` (via its ``extractRobotState``), so the two cannot drift.
 */
export function normalizeRobotState(
  state: unknown,
  executionMode?: unknown,
  raw?: unknown,
): RobotDisplaySnapshot {
  const rs = asRecord(state);
  const axes = asRecord(rs.axes_mm ?? rs.pose);
  const alarms = asStringList(rs.alarms);
  const connected = Boolean(rs.connected_real_device ?? rs.connected);
  const mode =
    typeof rs.mode === "string" && rs.mode.length > 0 ? rs.mode : "unknown";

  const pose = {
    x: asNumberOrNull(axes.x),
    y: asNumberOrNull(axes.y),
    z: asNumberOrNull(axes.z),
    rx: asNumberOrNull(axes.rx),
    ry: asNumberOrNull(axes.ry),
    rz: asNumberOrNull(axes.rz),
  };

  return {
    connection: {
      connected,
      label: connected ? "已连接" : "离线",
    },
    safety: {
      // Connected + no emergency_stop alarm ⟺ ESTOP bit clear ⟺ not e-stopped
      // (the backend derives ``alarms`` from the ESTOP status bit). Only stay
      // "unknown" when the status wasn't read (disconnected).
      estop: !connected
        ? "unknown"
        : alarms.some((item) => {
            const lower = item.toLowerCase();
            // "emergency" catches the backend's "emergency_stop" alarm (which
            // does NOT contain the substring "estop" — it's "_stop").
            return (
              lower.includes("emergency") ||
              lower.includes("estop") ||
              lower.includes("急停") ||
              lower.includes("e-stop")
            );
          })
          ? "active"
          : "ok",
      // PAUSED bit is clear for idle/moving/stopped/initializing ⟺ not paused.
      // "alarm" hides the PAUSED bit (ALARM takes precedence in
      // _mode_from_status), so pause is genuinely ambiguous there — "unknown".
      pause: !connected
        ? "unknown"
        : mode === "paused"
          ? "paused"
          : mode === "idle" ||
              mode === "moving" ||
              mode === "stopped" ||
              mode === "initializing"
            ? "ok"
            : "unknown",
      alarm: alarms.length > 0 ? "active" : "none",
      cancelLatch: Boolean(rs.cancel_latch),
    },
    pose,
    alarms,
    joints: [null, null, null, null, null, null],
    motion: {
      speedPct: asNumberOrNull(rs.speed_pct),
      progressPct: asNumberOrNull(rs.progress_pct),
    },
    task: {
      current: typeof rs.current_task === "string" ? rs.current_task : null,
      mode,
      executionMode: normalizeExecutionMode(executionMode),
    },
    raw: raw ?? state,
  };
}

/**
 * Project the raw ``/api/robot/status`` payload into a UI-friendly snapshot.
 * Thin wrapper over :func:`normalizeRobotState` that pulls ``robot_state`` and
 * ``execution_mode`` out of the status envelope.
 */
export function normalizeRobotStatusResult(result: RobotStatusResult): RobotDisplaySnapshot {
  const data = asRecord(result.data);
  return normalizeRobotState(data.robot_state, data.execution_mode, result);
}

/** Render a pose axis value as a UI string. ``null`` → ``"-"``. */
export function formatPoseValue(value: number | null): string {
  if (value == null) return "-";
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}
