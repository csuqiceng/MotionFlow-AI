import { useCallback, useMemo, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  robotConfirm,
  robotExecute,
  robotPendingPlan,
  type RobotResult,
} from "@/lib/robot-api";

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

const DEFAULT_POSE: PoseInputs = {
  x: "900",
  y: "0",
  z: "1000",
  rx: "0",
  ry: "0",
  rz: "0",
  speedPct: "50",
};

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

function renderRobotState(data: Record<string, unknown>): string {
  const rs = data?.robot_state;
  if (rs && typeof rs === "object") {
    try {
      return JSON.stringify(rs, null, 2);
    } catch {
      return String(rs);
    }
  }
  if (rs !== undefined) return String(rs);
  return "(no robot_state in response)";
}

/**
 * WebUI Robot Control Panel — dry-run -> confirm -> execute flow.
 *
 * Self-contained: the parent mounts it inside a Sheet and supplies the
 * bootstrap token + a session key. The operator enters a target pose,
 * runs a dry-run, ticks the two safety checkboxes, confirms, then executes.
 */
export function RobotControlPanel({
  token,
  sessionKey,
}: {
  token: string;
  sessionKey: string;
}) {
  const [pose, setPose] = useState<PoseInputs>(DEFAULT_POSE);
  const [planId, setPlanId] = useState<string | null>(null);
  const [paramHash, setParamHash] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [robotStateText, setRobotStateText] = useState<string | null>(null);
  const [confirmCode, setConfirmCode] = useState<string | null>(null);
  const [workAreaClear, setWorkAreaClear] = useState(false);
  const [estopReady, setEstopReady] = useState(false);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [busy, setBusy] = useState<null | "dry-run" | "confirm" | "execute">(null);
  const [error, setError] = useState<string | null>(null);

  const canConfirm = !!planId && workAreaClear && estopReady && busy !== "dry-run";
  const canExecute = !!confirmCode && busy !== "confirm";

  const appendLog = useCallback((entry: LogEntry) => {
    setLog((current) => [...current, entry]);
  }, []);

  const updateField = (field: keyof PoseInputs, value: string) => {
    setPose((current) => ({ ...current, [field]: value }));
    // Any pose change invalidates the pending plan/confirm flow.
    setPlanId(null);
    setParamHash(null);
    setExpiresAt(null);
    setRobotStateText(null);
    setConfirmCode(null);
  };

  const onDryRun = useCallback(async () => {
    setBusy("dry-run");
    setError(null);
    try {
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
        r_min: 0,
        r_max: 1200,
        z_min: 0,
        z_max: 1200,
      };
      const result = await robotPendingPlan(
        token,
        sessionKey,
        "linear_move",
        parameters,
      );
      const data = result.data ?? {};
      const nextPlanId = typeof data.plan_id === "string" ? data.plan_id : null;
      setPlanId(nextPlanId);
      setParamHash(typeof data.param_hash === "string" ? data.param_hash : null);
      setExpiresAt(
        typeof data.expires_at === "string" || typeof data.expires_at === "number"
          ? String(data.expires_at)
          : null,
      );
      setRobotStateText(renderRobotState(data));
      setConfirmCode(null);
      appendLog({ step: "dry-run", at: nowStamp(), result });
      if (!nextPlanId) {
        setError("Dry-run returned no plan_id — cannot proceed to confirm.");
      }
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      appendLog({ step: "dry-run", at: nowStamp(), result: { error: msg } });
    } finally {
      setBusy(null);
    }
  }, [appendLog, pose, sessionKey, token]);

  const onConfirm = useCallback(async () => {
    if (!planId) return;
    setBusy("confirm");
    setError(null);
    try {
      const result = await robotConfirm(
        token,
        sessionKey,
        planId,
        workAreaClear,
        estopReady,
      );
      const data = result.data ?? {};
      const code = typeof data.confirm_code === "string" ? data.confirm_code : null;
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
  }, [appendLog, estopReady, planId, sessionKey, token, workAreaClear]);

  const onExecute = useCallback(async () => {
    if (!planId || !confirmCode) return;
    setBusy("execute");
    setError(null);
    try {
      const result = await robotExecute(token, sessionKey, planId, confirmCode);
      setRobotStateText(renderRobotState(result.data ?? {}));
      appendLog({ step: "execute", at: nowStamp(), result });
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      appendLog({ step: "execute", at: nowStamp(), result: { error: msg } });
    } finally {
      setBusy(null);
    }
  }, [appendLog, confirmCode, planId, sessionKey, token]);

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
          Dry-run {"->"} 确认 {"->"} 执行. session_key: <code className="font-mono">{sessionKey || "(none)"}</code>
        </p>
      </div>

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
                onChange={(e) => updateField(key, e.target.value)}
                disabled={!!busy}
                className="h-9"
              />
            </label>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            onClick={onDryRun}
            disabled={!!busy}
            className="gap-2"
          >
            {busy === "dry-run" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            Dry-run
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={onConfirm}
            disabled={!canConfirm}
            className="gap-2"
          >
            {busy === "confirm" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            确认
          </Button>
          <Button
            type="button"
            variant="default"
            onClick={onExecute}
            disabled={!canExecute}
            className="gap-2"
          >
            {busy === "execute" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
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
            Physical E-stop is the real abort. This panel only issues the
            planned motion; hitting E-stop on the hardware stops motion
            immediately.
          </span>
        </p>
      </section>

      <section className="flex flex-col gap-1 text-xs">
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <span>
            plan_id:{" "}
            <code className="font-mono">{planId ?? "—"}</code>
          </span>
          <span>
            param_hash:{" "}
            <code className="font-mono">{paramHash ?? "—"}</code>
          </span>
          <span>
            expires_at:{" "}
            <code className="font-mono">{expiresAt ?? "—"}</code>
          </span>
          <span>
            confirm_code:{" "}
            <code className="font-mono">{confirmCode ?? "—"}</code>
          </span>
        </div>
        {error ? (
          <p className="text-destructive">{error}</p>
        ) : null}
      </section>

      {robotStateText ? (
        <section className="flex flex-col gap-1">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            robot_state
          </h3>
          <pre className="max-h-48 overflow-auto rounded-md border border-border/60 bg-muted/30 p-2 text-xs">
            {robotStateText}
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
