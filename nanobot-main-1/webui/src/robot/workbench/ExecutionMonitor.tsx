import type { LibraryExecution, LibraryExecutionAction } from "@/lib/robot-library-api";
import { Button } from "@/components/ui/button";
import { ExecutionTimelineDialog } from "./ExecutionTimeline";

const controlLabels: Record<LibraryExecutionAction, string> = {
  pause: "暂停",
  resume: "继续",
  step: "单步",
  stop: "停止",
  reset: "重置",
};

export function ExecutionMonitor({
  execution,
  onControl,
  controlling = false,
}: {
  execution: LibraryExecution;
  onControl: (action: LibraryExecutionAction) => void;
  controlling?: boolean;
}) {
  return (
    <section aria-label="执行监控" className="border-t">
      <div className="flex flex-wrap items-center gap-2 p-4">
        <h3 className="mr-auto font-semibold">执行监控</h3>
        {(execution.allowed_actions ?? []).map((action) => (
          <Button
            key={action}
            type="button"
            variant={action === "stop" ? "destructive" : "outline"}
            disabled={controlling}
            onClick={() => onControl(action)}
          >
            {controlLabels[action]}
          </Button>
        ))}
      </div>
      <ExecutionTimelineDialog execution={execution} />
    </section>
  );
}
