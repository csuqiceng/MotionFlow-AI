import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, SkipForward, XCircle, Clock } from "lucide-react";
import type { LibraryExecution, LibraryExecutionStep } from "@/lib/robot-library-api";
import { cn } from "@/lib/utils";

const STEP_LABELS: Record<LibraryExecutionStep["state"], string> = {
  queued: "等待",
  running: "执行中",
  succeeded: "完成",
  failed: "失败",
  skipped: "已跳过",
};

const STATE_LABELS: Record<LibraryExecution["state"], string> = {
  queued: "排队中",
  running: "执行中",
  paused: "已暂停",
  stopping: "停止中",
  completed: "已完成",
  failed: "执行失败",
  stopped: "已停止",
  reset: "已重置",
};

function stateTone(state: LibraryExecution["state"]): "ok" | "danger" | "warn" | "info" | "idle" {
  if (state === "completed") return "ok";
  if (state === "failed" || state === "stopped") return "danger";
  if (state === "paused" || state === "stopping") return "warn";
  if (state === "running" || state === "queued") return "info";
  return "idle";
}

function StepIcon({ state }: { state: LibraryExecutionStep["state"] }) {
  if (state === "running") return <Loader2 className="h-4 w-4 animate-spin text-[hsl(var(--info))]" />;
  if (state === "succeeded") return <CheckCircle2 className="h-4 w-4 text-[hsl(var(--success))]" />;
  if (state === "failed") return <XCircle className="h-4 w-4 text-[hsl(var(--danger))]" />;
  if (state === "skipped") return <SkipForward className="h-4 w-4 text-muted-foreground" />;
  return <Clock className="h-4 w-4 text-muted-foreground/60" />;
}

function stepTone(state: LibraryExecutionStep["state"]): string {
  if (state === "running") return "border-[hsl(var(--info)/0.4)] bg-[hsl(var(--info-subtle))] shadow-soft";
  if (state === "succeeded") return "border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success-subtle))]";
  if (state === "failed") return "border-[hsl(var(--danger)/0.3)] bg-[hsl(var(--danger-subtle))]";
  return "border-border/50 bg-background/40 opacity-70";
}

export interface ExecutionTimelineDialogProps {
  execution: LibraryExecution | null;
  onClose?: () => void;
  /** 单步前进回调（仅在单步模式下可用） */
  onStep?: () => void;
  /** 停止后续单步回调；不替代控制器的停止当前动作 */
  onStop?: () => void;
  /** 是否处于单步模式 */
  stepping?: boolean;
}

/**
 * 执行时间线弹框 — 点击执行时弹出，带缩放动画。
 * 显示总体进度、每个步骤的状态图标和消息。
 * 单步模式下额外显示"单步前进"和"停止"按钮。
 */
export function ExecutionTimelineDialog({ execution, onClose, onStep, onStop, stepping = false }: ExecutionTimelineDialogProps) {
  const [open, setOpen] = useState(false);

  // 当有 execution 时打开弹框
  useEffect(() => {
    if (execution) {
      setOpen(true);
    }
  }, [execution?.execution_id]);

  if (!execution) return null;

  const tone = stateTone(execution.state);
  const isRunning = execution.state === "running" || execution.state === "queued";
  const isPaused = execution.state === "paused";
  const completedSteps = execution.steps.filter((s) => s.state === "succeeded" || s.state === "failed" || s.state === "skipped").length;
  const totalSteps = execution.steps.length;
  const progressPct = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;
  // 单步模式下：暂停或运行中都允许前进/停止后续步骤。
  const canStep = stepping && (isPaused || isRunning) && Boolean(onStep);
  const canStopStepping = stepping && Boolean(onStop);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="执行时间线"
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center p-4 transition-all duration-300",
        open ? "opacity-100" : "opacity-0 pointer-events-none",
      )}
    >
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={() => { if (!isRunning && !stepping) { setOpen(false); onClose?.(); } }}
      />

      {/* 弹框主体 */}
      <div
        className={cn(
          "relative w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-lg transition-all duration-300",
          open ? "scale-100 translate-y-0" : "scale-95 translate-y-4",
        )}
      >
        {/* 头部 */}
        <div className="mb-4 flex items-center gap-3">
          <div className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
            tone === "ok" && "bg-[hsl(var(--success-subtle))]",
            tone === "danger" && "bg-[hsl(var(--danger-subtle))]",
            tone === "warn" && "bg-[hsl(var(--warning-subtle))]",
            tone === "info" && "bg-[hsl(var(--info-subtle))]",
            tone === "idle" && "bg-muted",
          )}>
            {isRunning ? (
              <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--info))]" />
            ) : tone === "ok" ? (
              <CheckCircle2 className="h-5 w-5 text-[hsl(var(--success))]" />
            ) : tone === "danger" ? (
              <XCircle className="h-5 w-5 text-[hsl(var(--danger))]" />
            ) : (
              <Clock className="h-5 w-5 text-muted-foreground" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-foreground">执行时间线</h3>
            <p className="text-xs text-muted-foreground">
              {execution.kind === "flow" ? "流程执行" : execution.kind === "command" ? "命令执行" : "执行任务"}
            </p>
          </div>
          <span className={cn(
            "status-pill shrink-0",
            tone === "ok" && "status-pill--ok",
            tone === "danger" && "status-pill--danger",
            tone === "warn" && "status-pill--warn",
            tone === "info" && "status-pill--info",
            tone === "idle" && "status-pill--idle",
          )}>
            {STATE_LABELS[execution.state]}
          </span>
        </div>

        {/* 进度条 */}
        {totalSteps > 0 ? (
          <div className="mb-4">
            <div className="mb-1.5 flex items-center justify-between text-xs text-muted-foreground">
              <span>进度</span>
              <span className="data-mono">{completedSteps} / {totalSteps}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500 ease-out",
                  tone === "danger" ? "bg-[hsl(var(--danger))]" : tone === "ok" ? "bg-[hsl(var(--success))]" : "bg-[hsl(var(--accent-primary))]",
                )}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        ) : null}

        {/* 步骤列表 */}
        <ol className="flex flex-col gap-2 max-h-[40vh] overflow-y-auto">
          {execution.steps.map((step) => (
            <li
              key={step.step_index}
              className={cn(
                "flex items-start gap-3 rounded-lg border p-3 transition-all duration-300",
                stepTone(step.state),
              )}
            >
              <StepIcon state={step.state} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground">
                    步骤 {step.step_index}
                  </span>
                  <span className={cn(
                    "text-xs",
                    step.state === "running" && "text-[hsl(var(--info))]",
                    step.state === "succeeded" && "text-[hsl(var(--success))]",
                    step.state === "failed" && "text-[hsl(var(--danger))]",
                    step.state === "skipped" && "text-muted-foreground",
                    step.state === "queued" && "text-muted-foreground/70",
                  )}>
                    {STEP_LABELS[step.state]}
                  </span>
                </div>
                {step.result && !step.result.ok ? (
                  <p className="mt-1 text-xs text-[hsl(var(--danger))] leading-5">
                    {String(step.result.message ?? "执行失败")}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>

        {/* 底部消息 */}
        {execution.message ? (
          <p
            role="alert"
            className={cn(
              "mt-3 rounded-lg p-2.5 text-xs leading-5",
              tone === "danger" ? "bg-[hsl(var(--danger-subtle))] text-[hsl(var(--danger))]" : "bg-muted text-muted-foreground",
            )}
          >
            {execution.message}
          </p>
        ) : null}

        {/* 单步模式控制按钮 */}
        {canStep || canStopStepping ? (
          <div className="mt-4 flex gap-2">
            {canStep ? (
              <button
                type="button"
                onClick={() => onStep?.()}
                className="btn-primary h-9 flex-1 text-sm"
              >
                单步前进
              </button>
            ) : null}
            {canStopStepping ? (
              <button
                type="button"
                onClick={() => onStop?.()}
                className="btn-danger h-9 flex-1 text-sm"
              >
                停止后续步骤
              </button>
            ) : null}
          </div>
        ) : null}
        {canStopStepping ? (
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            当前下位机动作不会由此按钮中断；需要立即停止请使用右侧“停止当前”或急停。
          </p>
        ) : null}

        {/* 关闭按钮（仅在非运行/单步状态显示） */}
        {!isRunning && !stepping ? (
          <button
            type="button"
            onClick={() => { setOpen(false); onClose?.(); }}
            className="btn-secondary mt-4 h-9 w-full text-sm"
          >
            关闭
          </button>
        ) : null}
      </div>
    </div>
  );
}
