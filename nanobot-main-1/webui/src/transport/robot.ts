import type { RobotStatusResult } from "./contracts/robot";

import { fetchWithTimeout } from "./http";

const ROBOT_TIMEOUT_MS = 30_000;

export type { RobotStatusResult };

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
  gatewayToken: string,
  userToken: string = "",
  options: { method?: "GET" | "POST"; body?: unknown } = {},
  timeoutMs: number = ROBOT_TIMEOUT_MS,
): Promise<T> {
  const body = options.body === undefined ? undefined : JSON.stringify(options.body);
  const headers: Record<string, string> = { Authorization: `Bearer ${gatewayToken}` };
  if (userToken) headers["X-Robot-User-Token"] = userToken;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetchWithTimeout(
    url,
    {
      method: options.method ?? "GET",
      headers,
      body,
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

/**
 * Read-only robot status snapshot (polled by RobotControlPanel).
 *
 * Unlike the pending-plan / confirm / execute endpoints, this one carries no
 * request body — the gateway dispatcher routes it as a plain GET. The response
 * is ``{ok: true, data: {robot_state: {...}}}`` (or a ``mode="disconnected"``
 * snapshot on error).
 */
export async function robotStatus(token: string): Promise<RobotStatusResult> {
  return robotRequest<RobotStatusResult>("/api/robot/status", token);
}

/** Phase 1: dry-run a motion command, store the pending plan server-side. */
export async function robotPendingPlan(
  token: string,
  sessionKey: string,
  command: string,
  parameters: Record<string, unknown>,
  userToken: string = "",
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/plans", token, userToken, {
    method: "POST",
    body: { session_id: sessionKey, command, parameters },
  });
}

/** Phase 2: confirm a pending plan after the operator safety checks. */
export async function robotConfirm(
  token: string,
  sessionKey: string,
  planId: string,
  confirmWorkAreaClear: boolean,
  confirmEstopReady: boolean,
  userToken: string = "",
): Promise<RobotResult> {
  return robotRequest<RobotResult>(`/api/robot/plans/${encodeURIComponent(planId)}/confirm`, token, userToken, {
    method: "POST",
    body: {
      session_id: sessionKey,
      confirm_work_area_clear: confirmWorkAreaClear,
      confirm_estop_ready: confirmEstopReady,
    },
  });
}

/** Phase 3: execute a confirmed plan with the issued confirm_code. */
export async function robotExecute(
  token: string,
  sessionKey: string,
  planId: string,
  confirmCode: string,
  userToken: string = "",
): Promise<RobotResult> {
  return robotRequest<RobotResult>(`/api/robot/plans/${encodeURIComponent(planId)}/execute`, token, userToken, {
    method: "POST",
    body: { session_id: sessionKey, confirm_code: confirmCode },
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
  userToken: string = "",
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/flow-pending-plan", token, userToken, {
    method: "POST",
    body: {
      session_id: sessionKey,
      flow_name: flowName,
    },
  });
}

export async function robotFlowConfirm(
  token: string,
  sessionKey: string,
  planId: string,
  confirmWorkAreaClear: boolean,
  confirmEstopReady: boolean,
  userToken: string = "",
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/flow-confirm", token, userToken, {
    method: "POST",
    body: {
      session_id: sessionKey,
      plan_id: planId,
      confirm_work_area_clear: confirmWorkAreaClear,
      confirm_estop_ready: confirmEstopReady,
    },
  });
}

export async function robotFlowExecute(
  token: string,
  sessionKey: string,
  planId: string,
  confirmCode: string,
  userToken: string = "",
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/flow-execute", token, userToken, {
    method: "POST",
    body: {
      session_id: sessionKey,
      plan_id: planId,
      confirm_code: confirmCode,
    },
  });
}

/**
 * Emergency stop deliberately bypasses the normal plan/confirm/permit path.
 * The server owns a dedicated one-use authority and the minimum controller
 * write sequence, so the UI must never model it as a generic system action.
 */
export async function robotEmergencyStop(
  token: string,
  userToken: string = "",
): Promise<RobotResult> {
  return robotRequest<RobotResult>("/api/robot/emergency-stop", token, userToken, {
    method: "POST",
  });
}

/**
 * Operator system action other than emergency stop. These actions retain the
 * ordinary plan → confirmation → one-shot execution-permit safety chain.
 */
export async function robotSystemAction(
  token: string,
  sessionKey: string,
  action: string,
  userToken: string = "",
): Promise<RobotResult> {
  const planned = await robotPendingPlan(token, sessionKey, "system", { action }, userToken) as RobotResult & {
    plan_id?: string;
  };
  if (!planned.plan_id) {
    throw new Error(planned.message || `系统动作 ${action} 未能生成安全计划。`);
  }
  const confirmed = await robotConfirm(token, sessionKey, planned.plan_id, true, true, userToken) as RobotResult & {
    confirm_code?: string;
  };
  if (!confirmed.confirm_code) {
    throw new Error(confirmed.message || `系统动作 ${action} 未能获得确认码。`);
  }
  return robotExecute(token, sessionKey, planned.plan_id, confirmed.confirm_code, userToken);
}
