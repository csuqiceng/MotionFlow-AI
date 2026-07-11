import { LogOut, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { RobotExecutionModeView } from "@/robot/hooks/useRobotExecutionMode";
import type { RobotDisplaySnapshot } from "@/robot/types";
import { cn } from "@/lib/utils";

type StatusTone = "ok" | "danger" | "info";

/**
 * Dense top status bar: title, connection pill, alarm pill, execution-mode pill,
 * plus restart/logout icon buttons. Reads the normalized snapshot + execution
 * mode view produced by ``useRobotExecutionMode``.
 */
export function RobotTopStatusBar({
  snapshot,
  executionMode,
  onLogout,
  onNativeEngineRestart,
}: {
  snapshot: RobotDisplaySnapshot | null;
  executionMode: RobotExecutionModeView;
  onLogout: () => void;
  onNativeEngineRestart: () => Promise<string>;
}) {
  const connected = snapshot?.connection.connected ?? false;
  const alarm = snapshot?.safety.alarm ?? "unknown";
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border/70 bg-background px-4">
      <div className="flex min-w-0 items-center gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold">机械手智能控制</h1>
          <p className="text-xs text-muted-foreground">Robot Control / Operator Console</p>
        </div>
        <StatusPill
          label={connected ? "控制器已连接" : "控制器离线"}
          tone={connected ? "ok" : "danger"}
        />
        <StatusPill
          label={alarm === "active" ? "报警" : "无报警"}
          tone={alarm === "active" ? "danger" : "ok"}
        />
        <StatusPill label={executionMode.label} tone="info" />
      </div>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="重启运行时"
          onClick={() => {
            void onNativeEngineRestart();
          }}
        >
          <RotateCcw className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="退出登录"
          onClick={onLogout}
        >
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}

function StatusPill({ label, tone }: { label: string; tone: StatusTone }) {
  return (
    <span
      className={cn(
        "rounded border px-2 py-0.5 text-xs font-medium",
        tone === "ok" &&
          "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        tone === "danger" &&
          "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
        tone === "info" &&
          "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300",
      )}
    >
      {label}
    </span>
  );
}
