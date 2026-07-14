import { useState } from "react";
import { useTranslation } from "react-i18next";

import { runLibraryCommand, runLibraryFlow, type LibraryCommand, type LibraryFlow } from "@/lib/robot-library-api";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryList } from "@/robot/library/LibraryList";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { EngineerWorkbench } from "@/robot/workbench/EngineerWorkbench";

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
  const lib = useRobotLibrary(token, tab);
  const isCommand = tab === "commands";
  const run = async (id: string) => { setRunning(true); setRunResult(null); try { const result = isCommand ? await runLibraryCommand(token, userToken, id) : await runLibraryFlow(token, userToken, id); setRunResult(result.ok ? t("library.runComplete") : String(result.message ?? t("library.runFailed"))); } catch (error) { setRunResult(error instanceof Error ? error.message : String(error)); } finally { setRunning(false); } };

  return (
    <div data-testid="command-library-page" className="flex h-full w-full overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col">
        <div role="tablist" className="flex gap-1 border-b border-border/70 px-3 py-2">
          <button
            type="button"
            role="tab"
            aria-selected={isCommand}
            onClick={() => setTab("commands")}
            className="rounded px-3 py-1 text-sm font-medium hover:bg-accent/50"
          >
            {t("library.tabs.commands", { defaultValue: "Commands" })}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={!isCommand}
            onClick={() => setTab("flows")}
            className="rounded px-3 py-1 text-sm font-medium hover:bg-accent/50"
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
              <><CommandDetail command={lib.detail as LibraryCommand} onRun={run} running={running} />{runResult ? <p role="status" className="p-4">{runResult}</p> : null}</>
            ) : null}
            {lib.detail && !isCommand ? (
              <><FlowDetail flow={lib.detail as LibraryFlow} onRun={run} running={running} />{runResult ? <p role="status" className="p-4">{runResult}</p> : null}</>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
