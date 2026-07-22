import { useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

import { libraryExecution, runLibraryCommand, runLibraryFlow, type LibraryCommand, type LibraryExecution, type LibraryFlow } from "@/lib/robot-library-api";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryList } from "@/robot/library/LibraryList";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { EngineerWorkbench } from "@/robot/workbench/EngineerWorkbench";
import { ExecutionTimeline } from "@/robot/workbench/ExecutionTimeline";

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
  const { t } = useTranslation();
  const [tab, setTab] = useState<LibraryTab>("commands");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<string | null>(null);
  const [execution, setExecution] = useState<LibraryExecution | null>(null);
  const lib = useRobotLibrary(token, tab);
  const isCommand = tab === "commands";
  const run = async (id: string) => {
    setRunning(true);
    setRunResult(null);
    setExecution(null);
    try {
      const result = await (isCommand ? runLibraryCommand(token, userToken, id) : runLibraryFlow(token, userToken, id));
      const executionId = result.data.execution_id;
      const poll = async () => {
        const current = (await libraryExecution(token, userToken, executionId)).data;
        setExecution(current);
        if (current.state === "queued" || current.state === "running") {
          window.setTimeout(() => void poll(), 350);
          return;
        }
        setRunning(false);
        setRunResult(current.state === "completed" ? t("library.runComplete") : (current.message || t("library.runFailed")));
      };
      await poll();
    } catch (error) {
      setRunResult(error instanceof Error ? error.message : String(error));
      setRunning(false);
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
              <><CommandDetail command={lib.detail as LibraryCommand} onRun={run} running={running} />{execution ? <ExecutionTimeline execution={execution} /> : null}{runResult ? <p role="status" className="p-4">{runResult}</p> : null}</>
            ) : null}
            {lib.detail && !isCommand ? (
              <><FlowDetail flow={lib.detail as LibraryFlow} onRun={run} running={running} />{execution ? <ExecutionTimeline execution={execution} /> : null}{runResult ? <p role="status" className="p-4">{runResult}</p> : null}</>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
