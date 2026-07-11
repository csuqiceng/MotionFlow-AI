import { AlertTriangle, Loader2, Octagon, Pause, Play, RotateCcw, Square, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { robotSystemAction } from "@/lib/robot-api";
import { useRobotStatus } from "@/robot/hooks/useRobotStatus";
import { formatPoseValue, ROBOT_POSE_AXES } from "@/robot/status";

type QuickAction = {
  action: string;
  label: string;
  Icon: typeof Octagon;
  destructive: boolean;
};

const QUICK_ACTIONS: readonly QuickAction[] = [
  { action: "emergency_stop", label: "急停", Icon: Octagon, destructive: true },
  { action: "pause", label: "暂停", Icon: Pause, destructive: false },
  { action: "resume", label: "继续", Icon: Play, destructive: false },
  { action: "release_emergency_stop", label: "解除急停", Icon: RotateCcw, destructive: false },
  { action: "release_cancel", label: "解除取消", Icon: XCircle, destructive: false },
  { action: "stop_current", label: "停止当前", Icon: Square, destructive: false },
  { action: "alarm_reset", label: "报警复位", Icon: AlertTriangle, destructive: false },
];

const TOAST_DURATION_MS = 3000;

/**
 * Right-side robot panel: live safety status + real-time pose + operator quick
 * buttons (急停/暂停/继续/解除急停/解除取消/停止当前/报警复位). Buttons fire
 * immediately on click (safety buttons must be instant); the result is shown
 * as a transient toast in the top-right corner that auto-dismisses.
 */
export function RobotSidePanel({ token }: { token: string }) {
  const { snapshot } = useRobotStatus(token);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const toastTimer = useRef<number | null>(null);

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
    try {
      const result = await robotSystemAction(token, action);
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

  return (
    <aside className="flex min-h-0 w-72 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border/70 bg-muted/20 p-4">
      <h2 className="text-sm font-semibold">机械手状态</h2>

      <section className="rounded-md border border-border/70 bg-background p-3">
        <p className="text-xs text-muted-foreground">连接</p>
        <p className="mt-1 text-sm font-medium">{snapshot?.connection.label ?? "连接中..."}</p>
      </section>

      <section className="rounded-md border border-border/70 bg-background p-3">
        <p className="text-xs text-muted-foreground">安全状态</p>
        <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
          <div><dt className="text-muted-foreground">急停</dt><dd className="font-medium">{snapshot?.safety.estop ?? "unknown"}</dd></div>
          <div><dt className="text-muted-foreground">暂停</dt><dd className="font-medium">{snapshot?.safety.pause ?? "unknown"}</dd></div>
          <div><dt className="text-muted-foreground">报警</dt><dd className="font-medium">{snapshot?.safety.alarm ?? "unknown"}</dd></div>
          <div><dt className="text-muted-foreground">取消锁存</dt><dd className="font-medium">{snapshot?.safety.cancelLatch ? "active" : "ok"}</dd></div>
        </dl>
      </section>

      <section className="rounded-md border border-border/70 bg-background p-3">
        <p className="text-xs text-muted-foreground">实时位置</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-xs">
          {ROBOT_POSE_AXES.map((axis) => (
            <div key={axis} className="flex justify-between">
              <dt className="uppercase text-muted-foreground">{axis}</dt>
              <dd>{formatPoseValue(snapshot?.pose[axis] ?? null)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">快捷操作</p>
        {QUICK_ACTIONS.map(({ action, label, Icon, destructive }) => (
          <Button
            key={action}
            variant={destructive ? "destructive" : "outline"}
            size="sm"
            disabled={busy !== null}
            onClick={() => runAction(action, label)}
            className="justify-start gap-2"
          >
            {busy === action ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
            {label}
          </Button>
        ))}
      </section>

      {toast ? (
        <div
          role="status"
          className={cn(
            "fixed right-4 top-4 z-50 max-w-sm rounded-md border px-4 py-2 text-sm font-medium shadow-lg",
            toast.ok
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "border-destructive/40 bg-destructive/10 text-destructive",
          )}
        >
          {toast.ok ? "✓ " : "✗ "}
          {toast.msg}
        </div>
      ) : null}
    </aside>
  );
}
