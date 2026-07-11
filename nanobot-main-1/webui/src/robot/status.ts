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
 * Project the raw ``/api/robot/status`` payload into a UI-friendly snapshot.
 *
 * Honest-null policy: anything the backend did not send becomes ``null`` /
 * ``"unknown"`` so the UI can render "-" rather than guess. We never fabricate
 * safety (estop/pause) state — those values come straight from ``alarms`` /
 * ``mode`` or stay ``"unknown"``.
 */
export function normalizeRobotStatusResult(result: RobotStatusResult): RobotDisplaySnapshot {
  const data = asRecord(result.data);
  const state = asRecord(data.robot_state);
  const axesSource = state.axes_mm ?? state.pose;
  const axes = asRecord(axesSource);
  const alarms = asStringList(state.alarms);
  const connected = Boolean(state.connected_real_device ?? state.connected);
  const mode =
    typeof state.mode === "string" && state.mode.length > 0 ? state.mode : "unknown";

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
      estop: alarms.some(
        (item) =>
          item.toLowerCase().includes("estop") ||
          item.toLowerCase().includes("急停") ||
          item.toLowerCase().includes("e-stop"),
      )
        ? "active"
        : "unknown",
      pause: mode === "paused" ? "paused" : "unknown",
      alarm: alarms.length > 0 ? "active" : "none",
      cancelLatch: Boolean(state.cancel_latch),
    },
    pose,
    joints: [null, null, null, null, null, null],
    motion: {
      speedPct: asNumberOrNull(state.speed_pct),
      progressPct: asNumberOrNull(state.progress_pct),
    },
    task: {
      current: typeof state.current_task === "string" ? state.current_task : null,
      mode,
      executionMode: normalizeExecutionMode(data.execution_mode),
    },
    raw: result,
  };
}

/** Render a pose axis value as a UI string. ``null`` → ``"-"``. */
export function formatPoseValue(value: number | null): string {
  if (value == null) return "-";
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}
