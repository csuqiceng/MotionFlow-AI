import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  engineerCreateCommand,
  engineerCreateFlow,
  engineerDeleteCommand,
  engineerDeleteFlow,
  engineerUpdateCommand,
  engineerUpdateFlow,
  type EngineerCommandDraft,
  type EngineerFlowDraft,
} from "@/lib/engineer-workbench-api";
import {
  libraryExecution,
  libraryExecutionControl,
  robotLibraryComponents,
  runLibraryCommand,
  runLibraryFlow,
  type LibraryCommand,
  type LibraryComponent,
  type LibraryExecution,
  type LibraryExecutionAction,
  type LibraryFlow,
} from "@/lib/robot-library-api";
import { Button } from "@/components/ui/button";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryWorkspaceSidebar } from "@/robot/library/LibraryWorkspaceSidebar";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { CommandDraftEditor } from "./CommandDraftEditor";
import { ExecutionMonitor } from "./ExecutionMonitor";
import { FlowDraftEditor } from "./FlowDraftEditor";

type Editor =
  | { kind: "command"; id?: string; value: EngineerCommandDraft }
  | { kind: "flow"; id?: string; value: EngineerFlowDraft }
  | null;

type DeleteTarget = {
  kind: "command" | "flow";
  id: string;
  name: string;
};

const commandValue = (item: LibraryCommand): EngineerCommandDraft => ({
  name: item.name,
  aliases: item.aliases,
  description: item.description,
  component_id: item.component_id,
  parameters: item.parameters,
});

const flowValue = (item: LibraryFlow): EngineerFlowDraft => ({
  name: item.name,
  description: item.description,
  step_delay_ms: item.step_delay_ms,
  rehearsal_spd: item.rehearsal_spd,
  steps: item.steps,
});

/**
 * Simple engineer-facing library maintenance surface.
 *
 * Saving a command or flow immediately updates the published operator library.
 * The version registry remains internal for auditability; it is deliberately not
 * surfaced as a user workflow.
 */
export function EngineerWorkbench({
  role,
  gatewayToken,
  userToken,
  onBackToChat,
}: {
  role: "operator" | "engineer";
  gatewayToken: string;
  userToken: string;
  onBackToChat?: () => void;
}) {
  if (role !== "engineer") return null;
  return <Workbench gatewayToken={gatewayToken} userToken={userToken} onBackToChat={onBackToChat} />;
}

function Workbench({
  gatewayToken,
  userToken,
  onBackToChat,
}: {
  gatewayToken: string;
  userToken: string;
  onBackToChat?: () => void;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<LibraryTab>("commands");
  const [editor, setEditor] = useState<Editor>(null);
  const [components, setComponents] = useState<LibraryComponent[]>([]);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [execution, setExecution] = useState<LibraryExecution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const detailPanelRef = useRef<HTMLDivElement>(null);
  const lib = useRobotLibrary(gatewayToken, tab, userToken);
  const commandLib = useRobotLibrary(gatewayToken, "commands", userToken);
  const isCommand = tab === "commands";
  const selected = lib.detail as LibraryCommand | LibraryFlow | null;

  useEffect(() => {
    let cancelled = false;
    void robotLibraryComponents(gatewayToken)
      .then((response) => {
        if (!cancelled) setComponents(response.data.items);
      })
      .catch(() => {
        if (!cancelled) setComponents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [gatewayToken]);

  useEffect(() => {
    if (lib.selectedId) detailPanelRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [lib.selectedId, tab]);

  const displayError = (cause: unknown) =>
    cause instanceof Error ? cause.message : String(cause);

  const beginNew = () => {
    setError(null);
    setEditor(isCommand
      ? { kind: "command", value: { name: "", aliases: [], description: "", component_id: "", parameters: {} } }
      : { kind: "flow", value: { name: "", steps: [], description: "", step_delay_ms: 0, rehearsal_spd: 100 } });
  };

  const beginEdit = () => {
    if (!selected) return;
    setError(null);
    setEditor(isCommand
      ? { kind: "command", id: (selected as LibraryCommand).id, value: commandValue(selected as LibraryCommand) }
      : { kind: "flow", id: (selected as LibraryFlow).flow_id, value: flowValue(selected as LibraryFlow) });
  };

  const saveCommand = async (value: EngineerCommandDraft) => {
    setSaving(true);
    setError(null);
    try {
      if (editor?.kind === "command" && editor.id) {
        await engineerUpdateCommand(gatewayToken, userToken, editor.id, value);
      } else {
        await engineerCreateCommand(gatewayToken, userToken, value);
      }
      setEditor(null);
      lib.refresh();
      commandLib.refresh();
    } catch (cause) {
      setError(displayError(cause));
    } finally {
      setSaving(false);
    }
  };

  const saveFlow = async (value: EngineerFlowDraft) => {
    setSaving(true);
    setError(null);
    try {
      if (editor?.kind === "flow" && editor.id) {
        await engineerUpdateFlow(gatewayToken, userToken, editor.id, value);
      } else {
        await engineerCreateFlow(gatewayToken, userToken, value);
      }
      setEditor(null);
      lib.refresh();
    } catch (cause) {
      setError(displayError(cause));
    } finally {
      setSaving(false);
    }
  };

  const requestRemoveSelected = () => {
    if (!selected) return;
    setDeleteError(null);
    setDeleteTarget(isCommand
      ? { kind: "command", id: (selected as LibraryCommand).id, name: selected.name }
      : { kind: "flow", id: (selected as LibraryFlow).flow_id, name: selected.name });
  };

  const confirmRemoveSelected = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setError(null);
    try {
      if (deleteTarget.kind === "command") {
        await engineerDeleteCommand(gatewayToken, userToken, deleteTarget.id);
        commandLib.refresh();
      } else {
        await engineerDeleteFlow(gatewayToken, userToken, deleteTarget.id);
      }
      setDeleteError(null);
      setDeleteTarget(null);
      setExecution(null);
      lib.select(null);
      lib.refresh();
    } catch (cause) {
      const message = displayError(cause);
      setError(message);
      setDeleteError(message);
    } finally {
      setDeleting(false);
    }
  };

  const runSelected = async (id: string) => {
    setRunning(true);
    setExecution(null);
    setError(null);
    try {
      const result = isCommand
        ? await runLibraryCommand(gatewayToken, userToken, id)
        : await runLibraryFlow(gatewayToken, userToken, id);
      const executionId = result.data.execution_id;
      const poll = async () => {
        const current = (await libraryExecution(gatewayToken, userToken, executionId)).data;
        setExecution(current);
        if (["queued", "running", "paused", "stopping"].includes(current.state)) {
          window.setTimeout(() => void poll(), 350);
        } else {
          setRunning(false);
        }
      };
      await poll();
    } catch (cause) {
      setError(displayError(cause));
      setRunning(false);
    }
  };

  const controlExecution = async (action: LibraryExecutionAction) => {
    if (!execution) return;
    setControlling(true);
    setError(null);
    try {
      const current = await libraryExecutionControl(
        gatewayToken,
        userToken,
        execution.execution_id,
        action,
      );
      setExecution(current.data);
    } catch (cause) {
      setError(displayError(cause));
    } finally {
      setControlling(false);
    }
  };

  return (
    <div data-testid="engineer-workbench" className="flex h-full w-full flex-col overflow-hidden bg-[radial-gradient(circle_at_55%_0%,hsl(var(--muted))_0%,hsl(var(--background))_44%)] md:flex-row">
      <LibraryWorkspaceSidebar
        tab={tab}
        onTabChange={(nextTab) => {
          setTab(nextTab);
          setEditor(null);
          setError(null);
        }}
        items={lib.items}
        loading={lib.loading}
        error={lib.error}
        filters={lib.filters}
        onFiltersChange={lib.setFilters}
        selectedId={lib.selectedId}
        onSelect={(id) => {
          setEditor(null);
          setError(null);
          lib.select(id);
        }}
        onBackToChat={onBackToChat}
        onCreate={beginNew}
      />
      <main ref={detailPanelRef} className="min-h-0 min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
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
            {error ? <p role="alert" className="p-4 text-sm text-destructive">{error}</p> : null}
            {editor?.kind === "command" ? (
              <CommandDraftEditor
                draft={editor.value}
                components={components}
                saving={saving}
                onSave={saveCommand}
              />
            ) : null}
            {editor?.kind === "flow" ? (
              <FlowDraftEditor
                draft={editor.value}
                commands={commandLib.items as LibraryCommand[]}
                saving={saving}
                onSave={saveFlow}
              />
            ) : null}
            {!editor && selected ? (
              <>
                <div className="flex gap-2 border-b p-3">
                  <Button variant="outline" onClick={beginEdit}>编辑</Button>
                  <Button variant="destructive" onClick={requestRemoveSelected}>删除</Button>
                </div>
                {isCommand ? (
                  <CommandDetail command={selected as LibraryCommand} onRun={runSelected} running={running} />
                ) : (
                  <FlowDetail flow={selected as LibraryFlow} onRun={runSelected} running={running} />
                )}
                {execution ? (
                  <ExecutionMonitor
                    execution={execution}
                    onControl={(action) => void controlExecution(action)}
                    controlling={controlling}
                  />
                ) : null}
              </>
            ) : null}
            {!editor && !selected && !lib.detailLoading ? (
              <p className="flex min-h-[22rem] items-center justify-center p-8 text-center text-sm text-muted-foreground">请选择一个{isCommand ? "命令" : "流程"}查看或编辑。</p>
            ) : null}
          </section>
        </div>
      </main>
      <DeleteConfirm
        open={deleteTarget !== null}
        title={deleteTarget?.name ?? ""}
        heading={deleteTarget ? `确认删除“${deleteTarget.name}”？` : ""}
        description="删除后操作员将不能再执行它。"
        confirmLabel="删除"
        cancelLabel="取消"
        error={deleteError}
        confirming={deleting}
        onCancel={() => {
          setDeleteError(null);
          setDeleteTarget(null);
        }}
        onConfirm={() => void confirmRemoveSelected()}
      />
    </div>
  );
}
