import type { LibraryExecution } from "@/lib/robot-library-api";

const labels: Record<LibraryExecution["steps"][number]["state"], string> = {
  queued: "等待",
  running: "执行中",
  succeeded: "完成",
  failed: "失败",
  skipped: "已跳过",
};

export function ExecutionTimeline({ execution }: { execution: LibraryExecution }) {
  return <section aria-label="执行时间线" className="border-t p-4">
    <h3 className="font-semibold">执行时间线</h3>
    <p className="text-sm text-muted-foreground">状态：{execution.state}</p>
    <ol className="mt-2 space-y-2">
      {execution.steps.map((step) => <li key={step.step_index} className="rounded border p-2">
        步骤 {step.step_index}：{labels[step.state]}
        {step.result && !Boolean(step.result.ok) ? <p role="alert">{String(step.result.message ?? "执行失败")}</p> : null}
      </li>)}
    </ol>
    {execution.message ? <p role="alert">{execution.message}</p> : null}
  </section>;
}
