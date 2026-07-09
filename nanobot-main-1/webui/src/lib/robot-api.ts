import { fetchWithTimeout } from "./http";

const ROBOT_TIMEOUT_MS = 30_000;

/** Standard ToolResult shape returned by the robot endpoints. */
export interface RobotResult {
  ok: boolean;
  state: string;
  message: string;
  data: Record<string, unknown>;
  errors: unknown[];
}

async function robotRequest<T>(
  url: string,
  token: string,
  body: unknown,
  timeoutMs: number = ROBOT_TIMEOUT_MS,
): Promise<T> {
  // The gateway's websockets library only accepts GET (not POST), so the
  // payload is carried in a custom header — matching the codebase convention
  // (automations/MCP routes use the same pattern).
  const res = await fetchWithTimeout(
    url,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Nanobot-Robot-Body": JSON.stringify(body),
      },
      credentials: "same-origin",
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = typeof res.text === "function" ? (await res.text()).trim() : "";
    throw new Error(`Robot API ${url} failed: ${res.status} ${text}`);
  }
  const contentType = res.headers?.get?.("content-type") ?? "";
  if (contentType && !contentType.toLowerCase().includes("application/json")) {
    const text = typeof res.text === "function" ? await res.text() : "";
    throw new Error(
      `Robot API ${url} returned a non-JSON response: ${text.slice(0, 200)}`,
    );
  }
  return (await res.json()) as T;
}

/** Phase 1: dry-run a motion command, store the pending plan server-side. */
export async function robotPendingPlan(
  token: string,
  sessionKey: string,
  command: string,
  parameters: Record<string, unknown>,
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/pending-plan", token, {
    session_key: sessionKey,
    command,
    parameters,
  });
}

/** Phase 2: confirm a pending plan after the operator safety checks. */
export async function robotConfirm(
  token: string,
  sessionKey: string,
  planId: string,
  confirmWorkAreaClear: boolean,
  confirmEstopReady: boolean,
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/confirm", token, {
    session_key: sessionKey,
    plan_id: planId,
    confirm_work_area_clear: confirmWorkAreaClear,
    confirm_estop_ready: confirmEstopReady,
  });
}

/** Phase 3: execute a confirmed plan with the issued confirm_code. */
export async function robotExecute(
  token: string,
  sessionKey: string,
  planId: string,
  confirmCode: string,
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/execute", token, {
    session_key: sessionKey,
    plan_id: planId,
    confirm_code: confirmCode,
  });
}

/**
 * Flow mode — multi-step named-flow dry-run -> confirm -> execute.
 *
 * Mirrors the single-command ``robotPendingPlan`` / ``robotConfirm`` /
 * ``robotExecute`` functions but targets the ``/api/robot/flow-*`` endpoints.
 * The flow-pending-plan response carries ``plan_id`` + nested ``dry_run_result``
 * at the top level; the flow-confirm response carries ``confirm_code`` at the
 * top level; the flow-execute response returns the flow result with
 * ``data.results[]`` (one entry per step, each holding ``result.data.robot_state``).
 * The shared ``RobotResult`` shape covers all three (flow-specific fields live
 * under ``data``).
 */
export async function robotFlowPendingPlan(
  token: string,
  sessionKey: string,
  flowName: string,
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/flow-pending-plan", token, {
    session_key: sessionKey,
    flow_name: flowName,
  });
}

export async function robotFlowConfirm(
  token: string,
  sessionKey: string,
  planId: string,
  confirmWorkAreaClear: boolean,
  confirmEstopReady: boolean,
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/flow-confirm", token, {
    session_key: sessionKey,
    plan_id: planId,
    confirm_work_area_clear: confirmWorkAreaClear,
    confirm_estop_ready: confirmEstopReady,
  });
}

export async function robotFlowExecute(
  token: string,
  sessionKey: string,
  planId: string,
  confirmCode: string,
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/flow-execute", token, {
    session_key: sessionKey,
    plan_id: planId,
    confirm_code: confirmCode,
  });
}
