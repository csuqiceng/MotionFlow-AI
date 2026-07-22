import { LogOut, RotateCcw } from "lucide-react";

import type { RobotExecutionModeView } from "@/robot/hooks/useRobotExecutionMode";
import type { RobotDisplaySnapshot } from "@/robot/types";
import { cn } from "@/lib/utils";

type StatusTone = "ok" | "danger" | "info" | "warn" | "idle";

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
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-sidebar px-5 gap-4">
      <div className="flex min-w-0 items-center gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold leading-tight">机械手智能控制</h1>
          <p className="text-xs text-muted-foreground leading-tight truncate">Operator Console</p>
        </div>
        <div className="hidden md:flex items-center gap-2 shrink-0">
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
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button
          type="button"
          title="重启"
          aria-label="重启运行时"
          className="ghost-icon"
          onClick={() => {
            void onNativeEngineRestart();
          }}
        >
          <RotateCcw className="h-4 w-4" />
        </button>
        <button
          type="button"
          title="退出登录"
          aria-label="退出登录"
          className="ghost-icon ghost-icon--danger"
          onClick={onLogout}
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}

function StatusPill({ label, tone }: { label: string; tone: StatusTone }) {
  return (
    <span
      className={cn(
        "status-pill",
        tone === "ok" && "status-pill--ok",
        tone === "danger" && "status-pill--danger",
        tone === "info" && "status-pill--info",
        tone === "warn" && "status-pill--warn",
        tone === "idle" && "status-pill--idle",
      )}
    >
      {label}
    </span>
  );
}
