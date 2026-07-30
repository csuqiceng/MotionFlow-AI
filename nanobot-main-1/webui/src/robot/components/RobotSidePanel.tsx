import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { robotEmergencyStop, robotSystemAction } from "@/lib/robot-api";
import { useRobotStatus } from "@/robot/hooks/useRobotStatus";
import { formatPoseValue, ROBOT_POSE_AXES } from "@/robot/status";

type QuickAction = {
  action: string;
  label: string;
};

const EMERGENCY_ACTION: QuickAction = {
  action: "emergency_stop",
  label: "急停",
};

const PRIMARY_CONTROL_ACTIONS: readonly QuickAction[] = [
  { action: "pause", label: "暂停" },
  { action: "resume", label: "继续" },
  { action: "alarm_reset", label: "报警复位" },
];

const SECONDARY_ACTIONS: readonly QuickAction[] = [
  { action: "release_emergency_stop", label: "解除急停" },
  { action: "release_cancel", label: "解除取消" },
  { action: "stop_current", label: "停止当前" },
];

const TOAST_DURATION_MS = 3000;

/**
 * Right-side robot panel: live safety status + real-time pose + joint angles +
 * operator quick buttons (急停/暂停/继续/解除急停/解除取消/停止当前/报警复位).
 * Every control action uses the same plan → operator confirmation → execute
 * safety chain as the full control panel; the result is shown as a transient
 * toast in the top-right corner that auto-dismisses.
 *
 * v3 styling: soft-cards with rounded-xl, status-dot--lg header, data-cell
 * tiles for pose/joints, sticky bottom e-stop + 3-col chip grid.
 */
export function RobotSidePanel({ token, userToken }: { token: string; userToken: string }) {
  const { snapshot } = useRobotStatus(token);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const toastTimer = useRef<number | null>(null);
  const safetySessionKey = useRef(`side-panel-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`);

  // Overall status tone for the header pulse dot:
  // 未连接 (idle) 优先 > danger (急停/报警) > warn (暂停/取消锁存) > ok (在线且安全)
  const overallTone: "danger" | "warn" | "idle" | "ok" =
    !snapshot?.connection.connected
      ? "idle"
      : snapshot?.safety.estop === "active" || snapshot?.safety.alarm === "active"
        ? "danger"
        : snapshot?.safety.pause === "paused" || snapshot?.safety.cancelLatch
          ? "warn"
          : "ok";
  const headerDotClass = {
    danger: "status-dot status-dot--danger status-dot--lg",
    warn: "status-dot status-dot--warn status-dot--lg",
    idle: "status-dot status-dot--idle status-dot--lg",
    ok: "status-dot status-dot--ok status-dot--lg",
  }[overallTone];
  const overallLabel = {
    danger: "系统报警",
    warn: "需注意",
    idle: "未连接",
    ok: "系统正常",
  }[overallTone];
  const overallPillClass = {
    danger: "status-pill status-pill--danger",
    warn: "status-pill status-pill--warn",
    idle: "status-pill",
    ok: "status-pill status-pill--ok",
  }[overallTone];
  const overallPillLabel = {
    danger: "报警",
    warn: "注意",
    idle: "离线",
    ok: "正常",
  }[overallTone];

  useEffect(
    () => () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(
      () => setToast(null),
      TOAST_DURATION_MS,
    );
  };

  const runAction = async (action: string, label: string) => {
    setBusy(action);
    showToast(`正在执行${label}…`, true);
    try {
      const result = action === EMERGENCY_ACTION.action
        ? await robotEmergencyStop(token, userToken)
        : await robotSystemAction(
          token,
          safetySessionKey.current,
          action,
          userToken,
        );
      showToast(
        result.ok ? `${label} 已执行` : `${label} 失败:${result.message}`,
        result.ok,
      );
    } catch (e) {
      showToast(`${label} 失败:${(e as Error).message}`, false);
    } finally {
      setBusy(null);
    }
  };

  const actionEnabled = (action: string): boolean => {
    if (action === EMERGENCY_ACTION.action) return busy === null;
    if (busy !== null || !snapshot?.connection.connected) return false;
    switch (action) {
      case "pause":
        return snapshot.safety.pause === "ok";
      case "resume":
        return snapshot.safety.pause === "paused";
      case "alarm_reset":
        return snapshot.safety.alarm === "active";
      case "release_emergency_stop":
        return snapshot.safety.estop === "active";
      case "release_cancel":
        return snapshot.safety.cancelLatch;
      case "stop_current":
        return snapshot.task.mode !== "idle" && snapshot.task.mode !== "unknown";
      default:
        return false;
    }
  };

  const joints = snapshot?.joints ?? [];
  const jointCount = Math.min(6, joints.length);

  return (
    <aside className={cn(
      "robot-side-panel hidden min-h-0 w-80 shrink-0 flex-col border-l border-border bg-background lg:flex",
    )}>
      {/* Status content scrolls independently when the desktop window is short. */}
      <div className="robot-status-stack min-h-0 shrink overflow-y-auto scrollbar-thin flex flex-col p-3 gap-3">

        {/* Safety status overview */}
        <section className="robot-panel-card soft-card rounded-lg p-3 animate-fade-in-up">
          <div className="robot-panel-card-header mb-2 flex items-center gap-2">
            <span className={cn("shrink-0", headerDotClass)} />
            <div className="min-w-0">
              <h3 className="text-sm font-medium leading-tight">{overallLabel}</h3>
              <p className="robot-panel-subtitle text-xs text-muted-foreground leading-tight">Safety Overview</p>
            </div>
            <span className={cn("ml-auto", overallPillClass)}>
              {overallPillLabel}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <SafetyChip
              label="急停"
              value={
                snapshot?.safety.estop === "active"
                  ? { tone: "danger", text: "已触发" }
                  : snapshot?.safety.estop === "ok"
                    ? { tone: "ok", text: "正常" }
                    : { tone: "idle", text: "离线" }
              }
            />
            <SafetyChip
              label="报警"
              value={
                snapshot?.safety.alarm === "active"
                  ? { tone: "danger", text: "报警中" }
                  : snapshot?.safety.alarm === "none"
                    ? { tone: "ok", text: "无" }
                    : { tone: "idle", text: "离线" }
              }
            />
            <SafetyChip
              label="暂停"
              value={
                snapshot?.safety.pause === "paused"
                  ? { tone: "warn", text: "已暂停" }
                  : snapshot?.safety.pause === "ok"
                    ? { tone: "ok", text: "正常" }
                    : { tone: "idle", text: "离线" }
              }
            />
            <SafetyChip
              label="取消锁存"
              value={
                snapshot?.safety.cancelLatch
                  ? { tone: "warn", text: "已锁存" }
                  : snapshot?.connection.connected
                    ? { tone: "ok", text: "正常" }
                    : { tone: "idle", text: "离线" }
              }
            />
          </div>
        </section>

        {/* End-effector pose — 2 cols x 3 rows */}
        <section className="robot-panel-card soft-card rounded-lg p-3 animate-fade-in-up">
          <div className="robot-panel-card-header mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium">末端位姿</h3>
            <span className="robot-panel-subtitle text-xs text-muted-foreground data-mono">End-effector Pose</span>
          </div>
          <div className="robot-pose-grid grid grid-cols-2 gap-2">
            {ROBOT_POSE_AXES.map((axis) => {
              const value = snapshot?.pose[axis] ?? null;
              const unit = axis === "x" || axis === "y" || axis === "z" ? "mm" : "deg";
              return (
                <div key={axis} className="data-cell">
                  <div className="flex items-baseline justify-between mb-0.5">
                    <span className="text-xs uppercase text-muted-foreground tracking-wider">{axis}</span>
                    <span className="text-[10px] text-muted-foreground">{unit}</span>
                  </div>
                  <p className="robot-pose-value data-mono text-base font-semibold text-foreground truncate">
                    {formatPoseValue(value)}
                  </p>
                </div>
              );
            })}
          </div>
        </section>

        {/* Joint angles — 3 cols x 2 rows */}
        {jointCount > 0 ? (
          <section className="robot-panel-card soft-card rounded-lg p-3 animate-fade-in-up">
            <div className="robot-panel-card-header mb-2 flex items-center justify-between">
              <h3 className="text-sm font-medium">关节角度</h3>
              <span className="robot-panel-subtitle text-xs text-muted-foreground data-mono">Joint Angles</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {Array.from({ length: jointCount }).map((_, idx) => {
                const value = joints[idx];
                return (
                  <div key={`J${idx + 1}`} className="data-cell text-center">
                    <p className="text-[10px] uppercase text-muted-foreground tracking-wider mb-0.5">J{idx + 1}</p>
                    <p className="data-mono text-sm font-semibold text-foreground truncate">
                      {value === null || value === undefined ? "—" : `${value.toFixed(1)}°`}
                    </p>
                  </div>
                );
              })}
            </div>
          </section>
        ) : null}

        {/* Motion telemetry — speed + progress */}
        <section className="robot-panel-card soft-card rounded-lg p-3 animate-fade-in-up">
          <div className="robot-panel-card-header mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium">运动参数</h3>
            <span className="robot-panel-subtitle text-xs text-muted-foreground data-mono">Motion</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">速度</span>
              <span className="data-mono font-semibold text-foreground">
                {snapshot?.motion.speedPct === null || snapshot?.motion.speedPct === undefined
                  ? "—"
                  : `${snapshot.motion.speedPct.toFixed(1)}%`}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">进度</span>
              <span className="data-mono font-semibold text-accent-primary">
                {snapshot?.motion.progressPct === null || snapshot?.motion.progressPct === undefined
                  ? "—"
                  : `${snapshot.motion.progressPct.toFixed(1)}%`}
              </span>
            </div>
          </div>
        </section>
      </div>

      {/* Safety actions occupy all remaining panel height below the status stack. */}
      <div className="robot-action-dock min-h-[240px] flex-1 border-t border-border bg-sidebar p-5 flex flex-col justify-center space-y-3">
        <button
          type="button"
          disabled={!actionEnabled(EMERGENCY_ACTION.action)}
          onClick={() => runAction(EMERGENCY_ACTION.action, EMERGENCY_ACTION.label)}
          className="robot-estop btn-estop h-14 w-full inline-flex items-center justify-center text-base tracking-wide disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy === EMERGENCY_ACTION.action ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
          {EMERGENCY_ACTION.label}
        </button>
        <div className="robot-action-grid grid grid-cols-3 gap-3">
          {PRIMARY_CONTROL_ACTIONS.map(({ action, label }) => (
            <button
              key={action}
              type="button"
              disabled={!actionEnabled(action)}
              onClick={() => runAction(action, label)}
              className="robot-action btn-secondary h-10 inline-flex items-center justify-center gap-1.5 text-xs disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {busy === action ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {label}
            </button>
          ))}
        </div>
        <div className="robot-action-grid grid grid-cols-3 gap-3">
          {SECONDARY_ACTIONS.map(({ action, label }) => (
            <button
              key={action}
              type="button"
              disabled={!actionEnabled(action)}
              onClick={() => runAction(action, label)}
              className="robot-action btn-secondary h-10 inline-flex items-center justify-center gap-1.5 text-xs disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {busy === action ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {label}
            </button>
          ))}
        </div>
      </div>

      {toast ? (
        <div
          role="status"
          className={cn(
            "status-pill fixed right-4 top-4 z-50 max-w-sm px-4 py-2 text-sm font-medium shadow-card backdrop-blur-md",
            toast.ok ? "status-pill--ok" : "status-pill--danger",
          )}
        >
          {toast.ok ? "✓ " : "✗ "}
          {toast.msg}
        </div>
      ) : null}
    </aside>
  );
}

/** A safety status row — label + value pill in a horizontal layout. */
function SafetyChip({
  label,
  value,
}: {
  label: string;
  value: { tone: "ok" | "danger" | "warn" | "idle"; text: string };
}) {
  const pillClass = {
    ok: "status-pill status-pill--ok",
    danger: "status-pill status-pill--danger",
    warn: "status-pill status-pill--warn",
    idle: "status-pill",
  }[value.tone];
  return (
    <div className="flex min-w-0 items-center justify-between gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={pillClass}>{value.text}</span>
    </div>
  );
}
