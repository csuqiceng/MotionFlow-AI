import { useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

import { libraryExecution, libraryExecutionControl, runLibraryCommand, runLibraryFlow, type LibraryCommand, type LibraryExecution, type LibraryFlow } from "@/lib/robot-library-api";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryList } from "@/robot/library/LibraryList";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { EngineerWorkbench } from "@/robot/workbench/EngineerWorkbench";
import { ExecutionTimelineDialog } from "@/robot/workbench/ExecutionTimeline";

export function CommandLibraryPage({
  token,
  role = "operator",
  userToken = "",
}: {
  token: string;
  role?: "operator" | "engineer";
  userToken?: string;
}) {
  if (role === "engineer") {
    return <EngineerWorkbench role={role} gatewayToken={token} userToken={userToken} />;
  }
  return <OperatorCommandLibraryPage token={token} userToken={userToken} />;
}

function OperatorCommandLibraryPage({
  token,
  userToken,
}: {
  token: string;
  userToken: string;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<LibraryTab>("commands");
  const [running, setRunning] = useState(false);
  const [stepping, setStepping] = useState(false);
  const [execution, setExecution] = useState<LibraryExecution | null>(null);
  const lib = useRobotLibrary(token, tab);
  const isCommand = tab === "commands";

  const pollExecution = async (
    executionId: string,
    isActive: (state: LibraryExecution["state"]) => boolean,
    onDone: (state: LibraryExecution) => void,
  ) => {
    const poll = async () => {
      const current = (await libraryExecution(token, userToken, executionId)).data;
      setExecution(current);
      if (isActive(current.state)) {
        window.setTimeout(() => void poll(), 350);
        return;
      }
      onDone(current);
    };
    await poll();
  };

  const run = async (id: string) => {
    setRunning(true);
    setExecution(null);
    try {
      const result = await (isCommand ? runLibraryCommand(token, userToken, id) : runLibraryFlow(token, userToken, id));
      const executionId = result.data.execution_id;
      await pollExecution(
        executionId,
        (s) => s === "queued" || s === "running",
        () => {
          setRunning(false);
        },
      );
    } catch (error) {
      console.error("Library run failed:", error instanceof Error ? error.message : String(error));
      setRunning(false);
    }
  };

  // 单步执行：启动流程后立即暂停，用户可在弹框中点击"单步前进"逐个推进。
  const stepFlow = async (name: string) => {
    setStepping(true);
    setExecution(null);
    try {
      const result = await runLibraryFlow(token, userToken, name);
      const executionId = result.data.execution_id;
      // 立即暂停以进入单步模式
      try {
        await libraryExecutionControl(token, userToken, executionId, "pause");
      } catch {
        // 忽略暂停失败（可能流程已快速结束或暂不支持暂停）
      }
      // 单步模式下，paused/queued/running 都继续轮询（用户可能在点击单步前进）
      await pollExecution(
        executionId,
        (s) => s === "queued" || s === "running" || s === "paused" || s === "stopping",
        () => {
          setStepping(false);
        },
      );
    } catch (error) {
      console.error("Library step failed:", error instanceof Error ? error.message : String(error));
      setStepping(false);
    }
  };

  // 单步前进：在已暂停的执行中推进一个步骤
  const advanceStep = async () => {
    if (!execution) return;
    try {
      await libraryExecutionControl(token, userToken, execution.execution_id, "step");
    } catch (error) {
      console.error("Library advance step failed:", error instanceof Error ? error.message : String(error));
    }
  };

  // 停止单步执行
  const stopStepping = async () => {
    if (!execution) return;
    try {
      await libraryExecutionControl(token, userToken, execution.execution_id, "stop");
    } catch (error) {
      console.error("Library stop stepping failed:", error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div data-testid="command-library-page" className="flex h-full w-full overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col">
        <div role="tablist" className="segmented grid-cols-2 mx-auto mt-4 w-fit">
          <button
            type="button"
            role="tab"
            aria-selected={isCommand}
            onClick={() => setTab("commands")}
            className={cn(
              "segmented__item",
              isCommand && "segmented__item--active",
            )}
          >
            {t("library.tabs.commands", { defaultValue: "Commands" })}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={!isCommand}
            onClick={() => setTab("flows")}
            className={cn(
              "segmented__item",
              !isCommand && "segmented__item--active",
            )}
          >
            {t("library.tabs.flows", { defaultValue: "Flows" })}
          </button>
        </div>
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <LibraryList
            tab={tab}
            items={lib.items}
            loading={lib.loading}
            error={lib.error}
            filters={lib.filters}
            onFiltersChange={lib.setFilters}
            selectedId={lib.selectedId}
            onSelect={lib.select}
          />
          <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
            {lib.detailError ? (
              <p className="p-4 text-sm text-destructive">{lib.detailError}</p>
            ) : null}
            {lib.detailLoading ? (
              <p className="p-4 text-sm text-muted-foreground">…</p>
            ) : null}
            {!lib.detail && !lib.detailLoading && !lib.detailError ? (
              <p className="p-4 text-sm text-muted-foreground">
                {t("library.detail.selectPrompt", {
                  defaultValue: "Select an item to view details.",
                })}
              </p>
            ) : null}
            {lib.detail && isCommand ? (
              <CommandDetail command={lib.detail as LibraryCommand} onRun={run} running={running} />
            ) : null}
            {lib.detail && !isCommand ? (
              <FlowDetail
                flow={lib.detail as LibraryFlow}
                onRun={run}
                onStep={stepFlow}
                running={running}
                stepping={stepping}
              />
            ) : null}
          </div>
        </div>
      </div>
      <ExecutionTimelineDialog
        execution={execution}
        onClose={() => setExecution(null)}
        onStep={stepping ? advanceStep : undefined}
        onStop={stepping ? stopStepping : undefined}
        stepping={stepping}
      />
    </div>
  );
}
