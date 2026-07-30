import { useState } from "react";
import { useTranslation } from "react-i18next";
import { libraryExecution, libraryExecutionControl, runLibraryCommand, runLibraryFlow, type LibraryCommand, type LibraryExecution, type LibraryFlow } from "@/lib/robot-library-api";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryWorkspaceSidebar } from "@/robot/library/LibraryWorkspaceSidebar";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { EngineerWorkbench } from "@/robot/workbench/EngineerWorkbench";
import { ExecutionTimelineDialog } from "@/robot/workbench/ExecutionTimeline";

export function CommandLibraryPage({
  token,
  role = "operator",
  userToken = "",
  onBackToChat,
}: {
  token: string;
  role?: "operator" | "engineer";
  userToken?: string;
  onBackToChat?: () => void;
}) {
  if (role === "engineer") {
    return (
      <EngineerWorkbench
        role={role}
        gatewayToken={token}
        userToken={userToken}
        onBackToChat={onBackToChat}
      />
    );
  }
  return <OperatorCommandLibraryPage token={token} userToken={userToken} onBackToChat={onBackToChat} />;
}

function OperatorCommandLibraryPage({
  token,
  userToken,
  onBackToChat,
}: {
  token: string;
  userToken: string;
  onBackToChat?: () => void;
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
    <div data-testid="command-library-page" className="flex h-full w-full flex-col overflow-hidden bg-[radial-gradient(circle_at_55%_0%,hsl(var(--muted))_0%,hsl(var(--background))_44%)] md:flex-row">
      <LibraryWorkspaceSidebar
        tab={tab}
        onTabChange={setTab}
        items={lib.items}
        loading={lib.loading}
        error={lib.error}
        filters={lib.filters}
        onFiltersChange={lib.setFilters}
        selectedId={lib.selectedId}
        onSelect={lib.select}
        onBackToChat={onBackToChat}
      />
      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div className="mx-auto w-full max-w-[920px] px-4 py-6 sm:px-8 sm:py-8 lg:py-12">
          <div className="mb-7">
            <p className="mb-2 text-[12px] text-muted-foreground">{t("sidebar.commandLibrary")}</p>
            <h1 className="text-[24px] font-normal leading-tight text-foreground sm:text-[28px]">
              {isCommand
                ? t("library.tabs.commands", { defaultValue: "Commands" })
                : t("library.tabs.flows", { defaultValue: "Flows" })}
            </h1>
            <p className="mt-2 text-[13px] leading-5 text-muted-foreground">
              {t("library.description", { defaultValue: "Manage reusable robot positions, commands, and flows." })}
            </p>
          </div>
          <section className="min-h-[22rem] overflow-hidden rounded-[24px] border border-border/50 bg-card/80 shadow-[0_22px_70px_rgba(15,23,42,0.06)] dark:border-white/10">
            {lib.detailError ? (
              <p className="p-4 text-sm text-destructive">{lib.detailError}</p>
            ) : null}
            {lib.detailLoading ? (
              <p className="p-4 text-sm text-muted-foreground">…</p>
            ) : null}
            {!lib.detail && !lib.detailLoading && !lib.detailError ? (
              <p className="flex min-h-[22rem] items-center justify-center p-8 text-center text-sm text-muted-foreground">
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
          </section>
        </div>
      </main>
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
