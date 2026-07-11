/**
 * Cross-panel robot operator display state.
 *
 * The dialogue panel dispatches ``command_submitted``; the chat-stream /
 * status-poll boundary dispatches ``tool_result_received`` /
 * ``status_poll_after_command``. The run panel reads the resulting
 * ``RobotDisplayState`` to render the current phase (safety-check → executing →
 * completed/blocked) without each panel keeping its own copy of the truth.
 */

export type RobotRunPhase =
  | "idle"
  | "safetyChecking"
  | "executing"
  | "completed"
  | "failed"
  | "blocked";

export interface RobotRunState {
  phase: RobotRunPhase;
  /** Backend ``state`` string from the most recent tool result, if any. */
  state: string | null;
  message: string;
  updatedAt: number | null;
}

export interface RobotDisplayState {
  lastCommand: string | null;
  run: RobotRunState;
  /** Most recent operator commands, newest first (capped at 5). */
  recent: Array<{ command: string; at: number }>;
}

export type RobotDisplayAction =
  | { type: "command_submitted"; command: string; at?: number }
  | { type: "auto_execution_started"; message?: string; at?: number }
  | {
      type: "tool_result_received";
      ok: boolean;
      state?: string;
      message?: string;
      at?: number;
    }
  | { type: "status_poll_after_command"; message?: string; at?: number }
  | { type: "clear_run"; at?: number };

export const initialRobotDisplayState: RobotDisplayState = {
  lastCommand: null,
  run: {
    phase: "idle",
    state: null,
    message: "系统待机, 等待指令",
    updatedAt: null,
  },
  recent: [],
};

const RECENT_CAP = 5;

export function robotDisplayReducer(
  state: RobotDisplayState,
  action: RobotDisplayAction,
): RobotDisplayState {
  const at = action.at ?? Date.now();

  switch (action.type) {
    case "command_submitted": {
      return {
        ...state,
        lastCommand: action.command,
        run: {
          phase: "safetyChecking",
          state: null,
          message: "正在进行安全检查",
          updatedAt: at,
        },
        recent: [{ command: action.command, at }, ...state.recent].slice(0, RECENT_CAP),
      };
    }
    case "auto_execution_started": {
      return {
        ...state,
        run: {
          phase: "executing",
          state: null,
          message: action.message ?? "安全检查通过, 正在执行",
          updatedAt: at,
        },
      };
    }
    case "tool_result_received": {
      return {
        ...state,
        run: {
          phase: action.ok ? "completed" : "blocked",
          state: action.state ?? null,
          message: action.message ?? (action.ok ? "执行完成" : "执行被阻断"),
          updatedAt: at,
        },
      };
    }
    case "status_poll_after_command": {
      return {
        ...state,
        run: {
          phase: "executing",
          state: state.run.state,
          message: action.message ?? "已发送指令, 正在根据状态轮询更新",
          updatedAt: at,
        },
      };
    }
    case "clear_run": {
      return initialRobotDisplayState;
    }
    default: {
      // Exhaustiveness guard — if a new action is added without a case, the
      // compiler errors here, and at runtime we fall back to a fresh state.
      return initialRobotDisplayState;
    }
  }
}

/**
 * Detect robot-shaped tool results and project them to display actions.
 * @deprecated M3 wires ``useRobotOperatorChat`` to extract ``robot_arm`` results
 * by exact ``toolEvent.name`` (not substring), which is precise. This helper is
 * retained only for reference; do not call it from new code.
 *
 * Returns ``null`` for non-robot results so the caller (the future chat-stream
 * bridge) can ignore everything else without touching the reducer. A result is
 * considered robot-shaped when it has a boolean ``ok``, a string ``state``,
 * and that state (or ``data.robot_state``) references the robot / zmotion
 * backend.
 */
export function robotToolResultToDisplayAction(value: unknown): RobotDisplayAction | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const result = value as Record<string, unknown>;
  if (typeof result.ok !== "boolean") return null;
  if (typeof result.state !== "string") return null;

  const stateLower = result.state.toLowerCase();
  const dataString = safeStringify(result.data);
  const hasRobotData =
    stateLower.includes("robot") ||
    stateLower.includes("zmotion") ||
    dataString.includes("robot_state");

  if (!hasRobotData) return null;

  return {
    type: "tool_result_received",
    ok: result.ok,
    state: result.state,
    message: typeof result.message === "string" ? result.message : undefined,
  };
}

function safeStringify(value: unknown): string {
  if (value == null) return "";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
