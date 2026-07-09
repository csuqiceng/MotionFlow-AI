import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  robotConfirm,
  robotExecute,
  robotFlowConfirm,
  robotFlowExecute,
  robotFlowPendingPlan,
  robotPendingPlan,
  robotStatus,
  type RobotResult,
} from "@/lib/robot-api";

type Mode = "motion" | "flow";

interface PoseInputs {
  x: string;
  y: string;
  z: string;
  rx: string;
  ry: string;
  rz: string;
  speedPct: string;
}

interface LogEntry {
  step: "dry-run" | "confirm" | "execute";
  at: string;
  result: RobotResult | { error: string };
}

/** Normalized robot_state snapshot for the status display. */
interface RobotStateSnapshot {
  mode: string;
  pose: { x: number; y: number; z: number; rx: number; ry: number; rz: number };
  alarms: string[];
  connected: boolean;
  cancelLatch: boolean;
}

const DEFAULT_POSE: PoseInputs = {
  x: "900",
  y: "0",
  z: "1000",
  rx: "0",
  ry: "0",
  rz: "0",
  speedPct: "50",
};

const STATUS_AXES: Array<keyof RobotStateSnapshot["pose"]> = ["x", "y", "z", "rx", "ry", "rz"];

function nowStamp(): string {
  try {
    return new Date().toLocaleTimeString();
  } catch {
    return new Date().toISOString();
  }
}

function num(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((v) => (typeof v === "string" ? v : JSON.stringify(v))).filter((s) => s.length > 0);
  }
  if (typeof value === "string" && value.length > 0) return [value];
  return [];
}

/**
 * Extract a normalized :RobotStateSnapshot from a robot API result.
 *
 * The robot endpoints do NOT wrap their payloads in the ``RobotResult``
 * envelope uniformly — different endpoints place ``robot_state`` in different
 * spots:
 *
 *  - Motion pending-plan: top-level ``plan.data.robot_state`` (``plan`` is the
 *    dry-run ToolResult).
 *  - Motion execute: top-level ``data.robot_state`` (the execute result IS a
 *    ToolResult).
 *  - Flow pending-plan: top-level ``dry_run_result.data.results[].result.data
 *    .robot_state`` (last step).
 *  - Flow execute: top-level ``data.results[].result.data.robot_state`` (last
 *    step).
 *
 * ``extractRobotState`` walks all of these locations and returns the first
 * match. ``result`` is treated as an opaque object (typed as ``RobotResult``
 * only because that is the declared return type of the API functions).
 */
function extractRobotState(result: RobotResult | null | undefined): RobotStateSnapshot | null {
  if (!result) return null;
  const root = result as unknown as Record<string, unknown>;

  // 1. data.robot_state (motion execute; some flow shapes).
  const rs = findRobotState(root);
  if (rs) return normalizeRobotState(rs);

  return null;
}

function findRobotState(obj: Record<string, unknown>): Record<string, unknown> | null {
  if (!obj || typeof obj !== "object") return null;

  // Direct: obj.robot_state
  if (obj.robot_state && typeof obj.robot_state === "object") {
    return obj.robot_state as Record<string, unknown>;
  }
  // obj.data.robot_state (ToolResult envelope — motion execute, flow execute)
  const data = obj.data;
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    if (d.robot_state && typeof d.robot_state === "object") {
      return d.robot_state as Record<string, unknown>;
    }
    // Flow: data.results[].result.data.robot_state — last step.
    if (Array.isArray(d.results) && d.results.length > 0) {
      const last = d.results[d.results.length - 1] as Record<string, unknown>;
      const stepRs = findRobotState(last);
      if (stepRs) return stepRs;
    }
  }
  // Motion pending-plan: obj.plan.data.robot_state
  const plan = obj.plan;
  if (plan && typeof plan === "object") {
    const planRs = findRobotState(plan as Record<string, unknown>);
    if (planRs) return planRs;
  }
  // Flow pending-plan: obj.dry_run_result (a ToolResult) -> data.results[]...
  const dry = obj.dry_run_result;
  if (dry && typeof dry === "object") {
    const dryRs = findRobotState(dry as Record<string, unknown>);
    if (dryRs) return dryRs;
  }
  return null;
}

function normalizeRobotState(rs: Record<string, unknown>): RobotStateSnapshot {
  const axes = (rs.axes_mm ?? rs.pose ?? {}) as Record<string, unknown>;
  return {
    mode: typeof rs.mode === "string" ? rs.mode : String(rs.mode ?? "unknown"),
    pose: {
      x: asNumber(axes.x),
      y: asNumber(axes.y),
      z: asNumber(axes.z),
      rx: asNumber(axes.rx),
      ry: asNumber(axes.ry),
      rz: asNumber(axes.rz),
    },
    alarms: asStringList(rs.alarms),
    connected: Boolean(rs.connected_real_device ?? rs.connected),
    cancelLatch: Boolean(rs.cancel_latch),
  };
}

/**
 * WebUI Robot Control Panel — dry-run -> confirm -> execute flow.
 *
 * Two modes share the same confirm chain:
 *  - Motion: pose inputs (x/y/z/rx/ry/rz + speed_pct) -> /api/robot/pending-plan.
 *  - Flow:   a named flow (e.g. "test_z_back")      -> /api/robot/flow-pending-plan.
 *
 * Switching mode clears planId/confirmCode so the operator must re-dry-run.
 * A status display at the top shows the robot_state from the most recent
 * dry-run / execute result.
 */
export function RobotControlPanel({
  token,
  sessionKey,
}: {
  token: string;
  sessionKey: string;
}) {
  const [mode, setMode] = useState<Mode>("motion");
  const [pose, setPose] = useState<PoseInputs>(DEFAULT_POSE);
  const [flowName, setFlowName] = useState<string>("test_z_back");
  const [planId, setPlanId] = useState<string | null>(null);
  const [paramHash, setParamHash] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [flowDryRunText, setFlowDryRunText] = useState<string | null>(null);
  const [flowResultsText, setFlowResultsText] = useState<string | null>(null);
  const [robotState, setRobotState] = useState<RobotStateSnapshot | null>(null);
  const [confirmCode, setConfirmCode] = useState<string | null>(null);
  const [workAreaClear, setWorkAreaClear] = useState(false);
  const [estopReady, setEstopReady] = useState(false);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [busy, setBusy] = useState<null | "dry-run" | "confirm" | "execute">(null);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState<"connecting" | "connected" | "error">("connecting");
  const latestToken = useRef(token);
  latestToken.current = token;

  const canConfirm = !!planId && workAreaClear && estopReady && busy !== "dry-run";
  const canExecute = !!confirmCode && busy !== "confirm";

  // Poll /api/robot/status every 3s while the panel is mounted. The cleanup
  // function clears the timer so polling stops when the panel unmounts (i.e.
  // when the floating-button modal closes).
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const result = await robotStatus(latestToken.current);
        if (cancelled) return;
        const snap = extractRobotState(result);
        if (snap) {
          setRobotState(snap);
          setPolling("connected");
        } else {
          setPolling("error");
        }
      } catch {
        if (!cancelled) setPolling("error");
      } finally {
        if (!cancelled) {
          timer = setTimeout(tick, 3000);
        }
      }
    };

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const appendLog = useCallback((entry: LogEntry) => {
    setLog((current) => [...current, entry]);
  }, []);

  const resetPlanState = useCallback(() => {
    setPlanId(null);
    setParamHash(null);
    setExpiresAt(null);
    setFlowDryRunText(null);
    setFlowResultsText(null);
    setConfirmCode(null);
  }, []);

  const updatePoseField = (field: keyof PoseInputs, value: string) => {
    setPose((current) => ({ ...current, [field]: value }));
    resetPlanState();
  };

  const onModeChange = (next: Mode) => {
    if (next === mode) return;
    setMode(next);
    setError(null);
    // Switching mode invalidates the pending plan/confirm flow.
    resetPlanState();
  };

  const onDryRun = useCallback(async () => {
    setBusy("dry-run");
    setError(null);
    try {
      if (mode === "motion") {
        const parameters = {
          target_pose: {
            x: num(pose.x, 0),
            y: num(pose.y, 0),
            z: num(pose.z, 0),
            rx: num(pose.rx, 0),
            ry: num(pose.ry, 0),
            rz: num(pose.rz, 0),
          },
          speed_pct: num(pose.speedPct, 50),
          acceleration_pct: 50,
          deceleration_pct: 50,
          // Must match robot_ai/safety/config.py DEFAULT_WORKSPACE_* (single source of truth).
          r_min: 200,
          r_max: 1800,
          z_min: 0,
          z_max: 2500,
        };
        const result = await robotPendingPlan(
          token,
          sessionKey,
          "linear_move",
          parameters,
        );
        // pending-plan returns ``{plan_id, plan, param_hash, expires_at}`` at
        // the TOP LEVEL (not wrapped in ``data``). ``RobotResult`` is a lie
        // here — check both shapes defensively.
        const nextPlanId = readStringField(result, "plan_id");
        setPlanId(nextPlanId);
        setParamHash(readStringField(result, "param_hash"));
        setExpiresAt(readStringOrNumberField(result, "expires_at"));
        setRobotState(extractRobotState(result));
        setConfirmCode(null);
        appendLog({ step: "dry-run", at: nowStamp(), result });
        if (!nextPlanId) {
          setError("Dry-run returned no plan_id — cannot proceed to confirm.");
        }
      } else {
        const name = flowName.trim();
        if (!name) {
          setError("Flow name is required.");
          return;
        }
        const result = await robotFlowPendingPlan(token, sessionKey, name);
        // flow-pending-plan returns ``{plan_id, flow_name, dry_run_result,
        // param_hash, expires_at}`` at the TOP LEVEL (not wrapped in ``data``).
        const nextPlanId = readStringField(result, "plan_id");
        setPlanId(nextPlanId);
        setParamHash(readStringField(result, "param_hash"));
        setExpiresAt(readStringOrNumberField(result, "expires_at"));
        const dryRun = readField(result, "dry_run_result");
        setFlowDryRunText(
          dryRun !== undefined && dryRun !== null
            ? safeJson(dryRun)
            : safeJson(result),
        );
        setRobotState(extractRobotState(result));
        setConfirmCode(null);
        appendLog({ step: "dry-run", at: nowStamp(), result });
        if (!nextPlanId) {
          setError("Flow dry-run returned no plan_id — cannot proceed to confirm.");
        }
      }
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      appendLog({ step: "dry-run", at: nowStamp(), result: { error: msg } });
    } finally {
      setBusy(null);
    }
  }, [appendLog, flowName, mode, pose, resetPlanState, sessionKey, token]);

  const onConfirm = useCallback(async () => {
    if (!planId) return;
    setBusy("confirm");
    setError(null);
    try {
      const result =
        mode === "motion"
          ? await robotConfirm(token, sessionKey, planId, workAreaClear, estopReady)
          : await robotFlowConfirm(token, sessionKey, planId, workAreaClear, estopReady);
      // The confirm endpoints return ``{confirm_code}`` at the TOP LEVEL (not
      // wrapped in ``data``). ``RobotResult`` is a lie here — the response is a
      // bare object — so check both shapes defensively.
      const code = readConfirmCode(result);
      setConfirmCode(code);
      appendLog({ step: "confirm", at: nowStamp(), result });
      if (!code) {
        setError("Confirm returned no confirm_code — cannot proceed to execute.");
      }
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      appendLog({ step: "confirm", at: nowStamp(), result: { error: msg } });
    } finally {
      setBusy(null);
    }
  }, [appendLog, estopReady, mode, planId, sessionKey, token, workAreaClear]);

  const onExecute = useCallback(async () => {
    if (!planId || !confirmCode) return;
    setBusy("execute");
    setError(null);
    try {
      const result =
        mode === "motion"
          ? await robotExecute(token, sessionKey, planId, confirmCode)
          : await robotFlowExecute(token, sessionKey, planId, confirmCode);
      setRobotState(extractRobotState(result));
      if (mode === "flow") {
        // Surface per-step poses from data.results[] (flow-execute returns a
        // proper ToolResult envelope, so results live under ``data``).
        const results = readField(result, "results");
        setFlowResultsText(formatFlowResults(results));
      }
      appendLog({ step: "execute", at: nowStamp(), result });
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      appendLog({ step: "execute", at: nowStamp(), result: { error: msg } });
    } finally {
      setBusy(null);
    }
  }, [appendLog, confirmCode, mode, planId, sessionKey, token]);

  const poseFields: Array<{ key: keyof PoseInputs; label: string }> = useMemo(
    () => [
      { key: "x", label: "x" },
      { key: "y", label: "y" },
      { key: "z", label: "z" },
      { key: "rx", label: "rx" },
      { key: "ry", label: "ry" },
      { key: "rz", label: "rz" },
      { key: "speedPct", label: "speed_pct" },
    ],
    [],
  );

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4 text-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold">Robot Control Panel</h2>
        <p className="text-xs text-muted-foreground">
          Dry-run {"->"} 确认 {"->"} 执行. session_key:{" "}
          <code className="font-mono">{sessionKey || "(none)"}</code>
        </p>
      </div>

      <StatusDisplay state={robotState} polling={polling} />

      <ModeToggle mode={mode} onChange={onModeChange} disabled={!!busy} />

      {mode === "motion" ? (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Motion target
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {poseFields.map(({ key, label }) => (
              <label key={key} className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Input
                  type="number"
                  value={pose[key]}
                  onChange={(e) => updatePoseField(key, e.target.value)}
                  disabled={!!busy}
                  className="h-9"
                />
              </label>
            ))}
          </div>
        </section>
      ) : (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Flow target
          </h3>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">flow_name</span>
            <Input
              type="text"
              value={flowName}
              onChange={(e) => {
                setFlowName(e.target.value);
                resetPlanState();
              }}
              disabled={!!busy}
              placeholder="e.g. test_z_back"
              className="h-9 font-mono"
            />
          </label>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" onClick={onDryRun} disabled={!!busy} className="gap-2">
            {busy === "dry-run" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Dry-run
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={onConfirm}
            disabled={!canConfirm}
            className="gap-2"
          >
            {busy === "confirm" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            确认
          </Button>
          <Button
            type="button"
            variant="default"
            onClick={onExecute}
            disabled={!canExecute}
            className="gap-2"
          >
            {busy === "execute" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            执行
          </Button>
        </div>

        <div className="flex flex-col gap-2 rounded-md border border-border/60 bg-muted/30 p-2 text-xs">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={workAreaClear}
              onChange={(e) => setWorkAreaClear(e.target.checked)}
              disabled={!!busy}
              className="h-4 w-4"
            />
            <span>Work area is clear (确认工作区无障碍)</span>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={estopReady}
              onChange={(e) => setEstopReady(e.target.checked)}
              disabled={!!busy}
              className="h-4 w-4"
            />
            <span>E-stop reachable (急停按钮就绪)</span>
          </label>
        </div>

        <p className="flex items-start gap-1 text-xs text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            Physical E-stop is the real abort. This panel only issues the planned
            motion; hitting E-stop on the hardware stops motion immediately.
          </span>
        </p>
      </section>

      <section className="flex flex-col gap-1 text-xs">
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <span>
            plan_id: <code className="font-mono">{planId ?? "—"}</code>
          </span>
          <span>
            param_hash: <code className="font-mono">{paramHash ?? "—"}</code>
          </span>
          <span>
            expires_at: <code className="font-mono">{expiresAt ?? "—"}</code>
          </span>
          <span>
            confirm_code: <code className="font-mono">{confirmCode ?? "—"}</code>
          </span>
        </div>
        {error ? <p className="text-destructive">{error}</p> : null}
      </section>

      {mode === "flow" && flowDryRunText ? (
        <section className="flex flex-col gap-1">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            flow dry_run_result
          </h3>
          <pre className="max-h-48 overflow-auto rounded-md border border-border/60 bg-muted/30 p-2 text-xs">
            {flowDryRunText}
          </pre>
        </section>
      ) : null}

      {mode === "flow" && flowResultsText ? (
        <section className="flex flex-col gap-1">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            flow step results (pose per step)
          </h3>
          <pre className="max-h-64 overflow-auto rounded-md border border-border/60 bg-muted/30 p-2 text-xs">
            {flowResultsText}
          </pre>
        </section>
      ) : null}

      <section className="flex min-h-0 flex-1 flex-col gap-1">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Log
        </h3>
        <pre
          className={cn(
            "min-h-[120px] flex-1 overflow-auto rounded-md border border-border/60 bg-muted/30 p-2 text-xs",
          )}
        >
          {log.length === 0
            ? "(no steps yet — click Dry-run to begin)"
            : log
                .map((entry) => {
                  const head = `[${entry.at}] ${entry.step}`;
                  if ("error" in entry.result) {
                    return `${head}\n  ERROR: ${entry.result.error}`;
                  }
                  const r = entry.result;
                  return [
                    head,
                    `  ok=${r.ok} state=${r.state} message=${r.message ?? ""}`,
                    `  data=${JSON.stringify(r.data ?? {})}`,
                  ].join("\n");
                })
                .join("\n\n")}
        </pre>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ModeToggle({
  mode,
  onChange,
  disabled,
}: {
  mode: Mode;
  onChange: (next: Mode) => void;
  disabled: boolean;
}) {
  const options: Array<{ value: Mode; label: string }> = [
    { value: "motion", label: "Motion" },
    { value: "flow", label: "Flow" },
  ];
  return (
    <div
      role="tablist"
      aria-label="Control mode"
      className="inline-flex w-fit rounded-md border border-border/60 bg-muted/30 p-0.5"
    >
      {options.map((opt) => {
        const active = opt.value === mode;
        return (
          <button
            key={opt.value}
            role="tab"
            type="button"
            aria-selected={active}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={cn(
              "rounded-sm px-3 py-1 text-xs font-medium transition-colors",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              disabled ? "opacity-50" : "",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function StatusDisplay({
  state,
  polling,
}: {
  state: RobotStateSnapshot | null;
  polling: "connecting" | "connected" | "error";
}) {
  const indicator =
    polling === "connected"
      ? "已连接"
      : polling === "error"
        ? "连接错误"
        : "连接中...";
  const indicatorClass =
    polling === "connected"
      ? "text-green-600"
      : polling === "error"
        ? "text-destructive"
        : "text-muted-foreground";
  if (!state) {
    return (
      <section className="flex flex-col gap-1 rounded-md border border-border/60 bg-muted/20 p-2 text-xs">
        <h3 className="flex items-center justify-between gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <span>Robot status</span>
          <span className={cn("normal-case", indicatorClass)}>{indicator}</span>
        </h3>
        <p className="text-muted-foreground">未查询</p>
      </section>
    );
  }
  const alarmText = state.alarms.length > 0 ? state.alarms.join(", ") : "none";
  return (
    <section className="flex flex-col gap-1 rounded-md border border-border/60 bg-muted/20 p-2 text-xs">
      <h3 className="flex items-center justify-between gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <span>Robot status</span>
        <span className={cn("normal-case", indicatorClass)}>{indicator}</span>
      </h3>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        <span>
          mode:{" "}
          <code className="font-mono">{state.mode}</code>
        </span>
        <span>
          connected:{" "}
          <code className="font-mono">{String(state.connected)}</code>
        </span>
        <span>
          cancel_latch:{" "}
          <code className="font-mono">{String(state.cancelLatch)}</code>
        </span>
        {STATUS_AXES.map((axis) => (
          <span key={axis}>
            {axis}: <code className="font-mono">{formatNum(state.pose[axis])}</code>
          </span>
        ))}
        <span className="col-span-2 sm:col-span-3">
          alarms: <code className="font-mono">{alarmText}</code>
        </span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/**
 * Read a string field from a robot API response, checking both the top level
 * and ``data.*`` (the endpoints inconsistently wrap payloads — some return
 * bare ``{plan_id, ...}``, others a ``RobotResult`` envelope).
 */
function readStringField(result: RobotResult, field: string): string | null {
  const value = readField(result, field);
  return typeof value === "string" ? value : null;
}

function readStringOrNumberField(result: RobotResult, field: string): string | null {
  const value = readField(result, field);
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}

function readField(result: RobotResult, field: string): unknown {
  const root = result as unknown as Record<string, unknown>;
  const top = root[field];
  if (top !== undefined) return top;
  const data = root.data;
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    if (d[field] !== undefined) return d[field];
  }
  return undefined;
}

function readConfirmCode(result: RobotResult): string | null {
  return readStringField(result, "confirm_code");
}

function formatNum(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(3);
}

function formatFlowResults(results: unknown): string {
  if (!Array.isArray(results) || results.length === 0) return "(no step results)";
  const lines: string[] = [];
  results.forEach((entry, i) => {
    const step = entry as Record<string, unknown>;
    const stepIndex = step.step_index ?? i + 1;
    const stepResult = step.result as Record<string, unknown> | undefined;
    const stepData = stepResult?.data as Record<string, unknown> | undefined;
    const rs = stepData?.robot_state as Record<string, unknown> | undefined;
    const actualPose = (stepData?.actual_pose ??
      (rs ? (rs.axes_mm ?? rs.pose) : undefined)) as
      | Record<string, unknown>
      | undefined;
    const ok = stepResult?.ok;
    const state = stepResult?.state;
    lines.push(
      `step ${stepIndex}: ok=${ok} state=${state ?? ""}${
        actualPose ? ` pose=${safeJson(actualPose)}` : ""
      }`,
    );
  });
  return lines.join("\n");
}
