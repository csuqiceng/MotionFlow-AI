import { Loader2 } from "lucide-react";

import type { RobotExecutionModeView } from "@/robot/hooks/useRobotExecutionMode";
import type { RobotDisplayState } from "@/robot/state/robotDisplayState";

/**
 * Right run panel. Shows the current phase (driven by the shared display
 * reducer, which ``useRobotOperatorChat`` advances from safetyChecking →
 * executing → completed/blocked) with a spinner while the LLM turn is in
 * flight, plus the execution-mode info card.
 */
export function RobotRunPanel({
  displayState,
  executionMode,
  isStreaming,
}: {
  displayState: RobotDisplayState;
  executionMode: RobotExecutionModeView;
  isStreaming: boolean;
}) {
  const phase = displayState.run.phase;
  const showSpinner =
    isStreaming || phase === "safetyChecking" || phase === "executing";

  return (
    <aside className="flex min-h-0 w-80 shrink-0 flex-col gap-3 overflow-y-auto bg-muted/10 p-4">
      <div>
        <h2 className="text-sm font-semibold">运行面板</h2>
        <p className="text-xs text-muted-foreground">当前模式: {executionMode.label}</p>
      </div>

      <section className="soft-card p-3">
        <p className="text-xs text-muted-foreground">当前状态</p>
        <p className="mt-1 flex items-center gap-2 text-sm font-medium">
          {showSpinner ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {displayState.run.message}
        </p>
        {displayState.run.state ? (
          <p className="mt-2 data-mono text-xs text-muted-foreground">
            {displayState.run.state}
          </p>
        ) : null}
      </section>

      {executionMode.requiresManualConfirm ? (
        <section className="soft-card border-warning/40 bg-warning/10 p-3 text-sm text-warning">
          人工确认模式已启用。M2 会接入计划卡、确认卡和 RC 执行链路。
        </section>
      ) : null}

      {executionMode.autoExecutesAfterSafetyCheck ? (
        <section className="soft-card border-info/30 bg-info/10 p-3 text-sm text-info">
          自动执行模式: 安全检查通过后, 后端工具会直接执行。右侧状态由对话工具结果或状态轮询写入共享运行状态。
        </section>
      ) : null}

      {executionMode.dryRunOnly ? (
        <section className="soft-card p-3 text-sm text-muted-foreground">
          只预演模式: 后端仅做计划与校验, 不会触发真实运动。
        </section>
      ) : null}
    </aside>
  );
}
