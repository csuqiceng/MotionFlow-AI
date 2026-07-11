import type { RobotExecutionModeView } from "@/robot/hooks/useRobotExecutionMode";
import type { RobotDisplayState } from "@/robot/state/robotDisplayState";

/**
 * Right run panel.
 *
 * Auto mode: shows the current phase message plus an info card explaining that
 * the backend auto-executes after the safety check, and that the run state is
 * fed by either the chat tool-result projection or the status poll.
 *
 * Manual mode: shows an amber notice that M2 will wire up the plan/confirm/RC
 * execution chain.
 */
export function RobotRunPanel({
  displayState,
  executionMode,
}: {
  displayState: RobotDisplayState;
  executionMode: RobotExecutionModeView;
}) {
  return (
    <aside className="flex min-h-0 w-80 shrink-0 flex-col gap-3 overflow-y-auto bg-muted/10 p-4">
      <div>
        <h2 className="text-sm font-semibold">运行面板</h2>
        <p className="text-xs text-muted-foreground">当前模式: {executionMode.label}</p>
      </div>

      <section className="rounded-md border border-border/70 bg-background p-3">
        <p className="text-xs text-muted-foreground">当前状态</p>
        <p className="mt-1 text-sm font-medium">{displayState.run.message}</p>
        {displayState.run.state ? (
          <p className="mt-2 font-mono text-xs text-muted-foreground">
            {displayState.run.state}
          </p>
        ) : null}
      </section>

      {executionMode.requiresManualConfirm ? (
        <section className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          人工确认模式已启用。M2 会接入计划卡、确认卡和 RC 执行链路。
        </section>
      ) : null}

      {executionMode.autoExecutesAfterSafetyCheck ? (
        <section className="rounded-md border border-blue-500/30 bg-blue-500/10 p-3 text-sm">
          自动执行模式: 安全检查通过后, 后端工具会直接执行。右侧状态由对话工具结果或状态轮询写入共享运行状态。
        </section>
      ) : null}

      {executionMode.dryRunOnly ? (
        <section className="rounded-md border border-border/70 bg-muted/30 p-3 text-sm text-muted-foreground">
          只预演模式: 后端仅做计划与校验, 不会触发真实运动。
        </section>
      ) : null}
    </aside>
  );
}
