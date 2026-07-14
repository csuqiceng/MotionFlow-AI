import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  EngineerConflictError,
  engineerArchiveCommand,
  engineerArchiveFlow,
  engineerBulkArchiveCommands,
  engineerBulkArchiveFlows,
  engineerCreateCommand,
  engineerCreateFlow,
  engineerDuplicateCommand,
  engineerDuplicateFlow,
  engineerExportLibrary,
  engineerImportLibrary,
  engineerPublishCommand,
  engineerPublishFlow,
  engineerStartCommandDraft,
  engineerStartFlowDraft,
  engineerUpdateCommandDraft,
  engineerUpdateFlowDraft,
  engineerValidateFlowDraft,
  type EngineerCommandDraft,
  type EngineerEntity,
  type EngineerFlowDraft,
} from "@/lib/engineer-workbench-api";
import { libraryExecution, libraryExecutionControl, libraryExecutions, robotLibraryComponents, runLibraryCommand, runLibraryFlow, type LibraryCommand, type LibraryComponent, type LibraryExecution, type LibraryExecutionAction, type LibraryFlow } from "@/lib/robot-library-api";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryList } from "@/robot/library/LibraryList";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { CommandDraftEditor } from "./CommandDraftEditor";
import { FlowDraftEditor } from "./FlowDraftEditor";
import { ExecutionMonitor } from "./ExecutionMonitor";
import { LibraryTransferDialog } from "./LibraryTransferDialog";
import { LibraryPreview } from "./LibraryPreview";
import { ControllerDiagnostics } from "./ControllerDiagnostics";
import { EngineerLogCenter } from "./EngineerLogCenter";

type Editor =
  | { kind: "command"; id?: string; draft: EngineerCommandDraft; revision?: number }
  | { kind: "flow"; id?: string; draft: EngineerFlowDraft; revision?: number }
  | null;

const commandDraft = (item: LibraryCommand): EngineerCommandDraft => ({
  name: item.name,
  aliases: item.aliases,
  description: item.description,
  component_id: item.component_id,
  parameters: item.parameters,
});
const flowDraft = (item: LibraryFlow): EngineerFlowDraft => ({
  name: item.name,
  description: item.description,
  step_delay_ms: item.step_delay_ms,
  rehearsal_spd: item.rehearsal_spd,
  steps: item.steps,
});
const entityDraft = (entity: EngineerEntity) => (entity.draft ?? entity) as Record<string, unknown>;

export function EngineerWorkbench({ role, gatewayToken, userToken }: { role: "operator" | "engineer"; gatewayToken: string; userToken: string }) {
  if (role !== "engineer") return null;
  return <Workbench gatewayToken={gatewayToken} userToken={userToken} />;
}

function Workbench({ gatewayToken, userToken }: { gatewayToken: string; userToken: string }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<LibraryTab>("commands");
  const lib = useRobotLibrary(gatewayToken, tab, userToken);
  const commandLib = useRobotLibrary(gatewayToken, "commands", userToken);
  const [editor, setEditor] = useState<Editor>(null);
  const [publish, setPublish] = useState<Editor>(null);
  const [archive, setArchive] = useState<Pick<NonNullable<Editor>, "kind" | "id"> | null>(null);
  const [batchArchive, setBatchArchive] = useState<{ kind: "command" | "flow"; ids: string[] } | null>(null);
  const [duplicate, setDuplicate] = useState<{ kind: "command" | "flow"; id: string; name: string } | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [transferOpen, setTransferOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<string[] | null>(null);
  const [components, setComponents] = useState<LibraryComponent[]>([]);
  const [running, setRunning] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [runResult, setRunResult] = useState<string | null>(null);
  const [execution, setExecution] = useState<LibraryExecution | null>(null);
  const [executionHistory, setExecutionHistory] = useState<LibraryExecution[]>([]);
  const isCommand = tab === "commands";
  const selected = lib.detail as LibraryCommand | LibraryFlow | null;
  useEffect(() => {
    let cancelled = false;
    void robotLibraryComponents(gatewayToken).then((response) => {
      if (!cancelled) setComponents(response.data.items);
    }).catch(() => { if (!cancelled) setComponents([]); });
    return () => { cancelled = true; };
  }, [gatewayToken]);
  useEffect(() => {
    let cancelled = false;
    void libraryExecutions(gatewayToken, userToken).then((response) => {
      if (!cancelled) setExecutionHistory(response.data.items);
    }).catch(() => { if (!cancelled) setExecutionHistory([]); });
    return () => { cancelled = true; };
  }, [gatewayToken, userToken]);
  const entityName = (kind: "command" | "flow") => t(`library.workbench.${kind}`);
  const displayError = (cause: unknown) => {
    if (cause instanceof EngineerConflictError) {
      return `${cause.message} ${t("library.workbench.currentRevision", { revision: cause.currentRevision ?? "unknown" })}`;
    }
    return cause instanceof Error ? cause.message : String(cause);
  };
  const runSelected = async (id: string) => {
    setRunning(true); setRunResult(null); setExecution(null);
    try {
      const result = isCommand ? await runLibraryCommand(gatewayToken, userToken, id) : await runLibraryFlow(gatewayToken, userToken, id);
      const executionId = result.data.execution_id;
      const poll = async () => {
        const current = (await libraryExecution(gatewayToken, userToken, executionId)).data;
        setExecution(current);
        if (current.state === "queued" || current.state === "running" || current.state === "paused" || current.state === "stopping") window.setTimeout(() => void poll(), 350);
        else { setRunning(false); setRunResult(current.state === "completed" ? t("library.runComplete") : (current.message || t("library.runFailed"))); }
      };
      await poll();
    } catch (cause) {
      setRunResult(displayError(cause));
      setRunning(false);
    }
    finally { /* polling owns the running state until the execution reaches a terminal state */ }
  };
  const controlExecution = async (action: LibraryExecutionAction) => {
    if (!execution) return;
    setControlling(true);
    try {
      const current = (await libraryExecutionControl(gatewayToken, userToken, execution.execution_id, action)).data;
      setExecution(current);
      setRunResult(null);
    } catch (cause) {
      setRunResult(displayError(cause));
    } finally {
      setControlling(false);
    }
  };

  const begin = async () => {
    if (!selected) return;
    setError(null);
    try {
      const result = isCommand
        ? await engineerStartCommandDraft(gatewayToken, userToken, (selected as LibraryCommand).id)
        : await engineerStartFlowDraft(gatewayToken, userToken, (selected as LibraryFlow).flow_id);
      const entity = result.data as EngineerEntity;
      const draft = entityDraft(entity);
      const revision = Number(draft.revision ?? 1);
      setEditor(isCommand
        ? { kind: "command", id: (selected as LibraryCommand).id, draft: { ...commandDraft(selected as LibraryCommand), ...(draft as Partial<EngineerCommandDraft>) }, revision }
        : { kind: "flow", id: (selected as LibraryFlow).flow_id, draft: { ...flowDraft(selected as LibraryFlow), ...(draft as Partial<EngineerFlowDraft>) }, revision });
    } catch (cause) {
      setError(displayError(cause));
    }
  };

  const saveCommand = async (draft: EngineerCommandDraft) => {
    try {
      if (!editor?.id || editor.kind !== "command") {
        const entity = (await engineerCreateCommand(gatewayToken, userToken, draft)).data;
        setEditor({ kind: "command", id: String(entity.command_id), draft, revision: Number(entityDraft(entity).revision ?? 1) });
      } else {
        const entity = (await engineerUpdateCommandDraft(gatewayToken, userToken, editor.id, { ...draft, expected_revision: editor.revision ?? 0 })).data;
        setEditor({ ...editor, draft, revision: Number(entityDraft(entity).revision ?? editor.revision) });
      }
      lib.refresh();
    } catch (cause) {
      setError(displayError(cause));
    }
  };

  const saveFlow = async (draft: EngineerFlowDraft) => {
    try {
      if (!editor?.id || editor.kind !== "flow") {
        const entity = (await engineerCreateFlow(gatewayToken, userToken, draft)).data;
        setEditor({ kind: "flow", id: String(entity.flow_id), draft, revision: Number(entityDraft(entity).revision ?? 1) });
      } else {
        const entity = (await engineerUpdateFlowDraft(gatewayToken, userToken, editor.id, { ...draft, expected_revision: editor.revision ?? 0 })).data;
        setEditor({ ...editor, draft, revision: Number(entityDraft(entity).revision ?? editor.revision) });
      }
      lib.refresh();
    } catch (cause) {
      setError(displayError(cause));
    }
  };

  const validate = async () => {
    if (editor?.kind !== "flow" || !editor.id) return;
    try {
      setValidation((await engineerValidateFlowDraft(gatewayToken, userToken, editor.id)).data.errors);
    } catch (cause) {
      setError(displayError(cause));
    }
  };
  const doPublish = async () => {
    if (!publish?.id) return;
    try {
      if (publish.kind === "command") await engineerPublishCommand(gatewayToken, userToken, publish.id);
      else await engineerPublishFlow(gatewayToken, userToken, publish.id);
      setEditor(null);
      setPublish(null);
      lib.refresh();
    } catch (cause) {
      setError(displayError(cause));
      setPublish(null);
    }
  };
  const doArchive = async () => {
    if (!archive?.id) return;
    try {
      if (archive.kind === "command") await engineerArchiveCommand(gatewayToken, userToken, archive.id);
      else await engineerArchiveFlow(gatewayToken, userToken, archive.id);
      setArchive(null);
      setEditor(null);
      lib.refresh();
    } catch (cause) {
      setError(displayError(cause));
      setArchive(null);
    }
  };
  const doBatchArchive = async () => {
    if (!batchArchive?.ids.length) return;
    try {
      const result = batchArchive.kind === "command"
        ? await engineerBulkArchiveCommands(gatewayToken, userToken, batchArchive.ids)
        : await engineerBulkArchiveFlows(gatewayToken, userToken, batchArchive.ids);
      setRunResult(result.data.failed.length ? `Archived ${result.data.archived.length}; skipped ${result.data.failed.length}.` : `Archived ${result.data.archived.length}.`);
      setSelectedIds([]);
      setBatchArchive(null);
      lib.refresh();
    } catch (cause) {
      setError(displayError(cause));
      setBatchArchive(null);
    }
  };
  const doDuplicate = async () => {
    if (!duplicate?.name.trim()) return;
    try {
      const entity = duplicate.kind === "command"
        ? (await engineerDuplicateCommand(gatewayToken, userToken, duplicate.id, duplicate.name.trim())).data
        : (await engineerDuplicateFlow(gatewayToken, userToken, duplicate.id, duplicate.name.trim())).data;
      const draft = entityDraft(entity);
      setEditor(duplicate.kind === "command"
        ? { kind: "command", id: String(entity.command_id), draft: draft as unknown as EngineerCommandDraft, revision: Number(draft.revision ?? 1) }
        : { kind: "flow", id: String(entity.flow_id), draft: draft as unknown as EngineerFlowDraft, revision: Number(draft.revision ?? 1) });
      setDuplicate(null);
      lib.refresh();
    } catch (cause) {
      setError(displayError(cause));
      setDuplicate(null);
    }
  };

  return (
    <div data-testid="engineer-workbench" className="flex h-full w-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div role="tablist" className="flex gap-2 border-b p-2">
          <button role="tab" aria-selected={isCommand} onClick={() => { setTab("commands"); setEditor(null); }}>{t("library.tabs.commands")}</button>
          <button role="tab" aria-selected={!isCommand} onClick={() => { setTab("flows"); setEditor(null); }}>{t("library.tabs.flows")}</button>
          <Button className="ml-auto" size="sm" onClick={() => setEditor(isCommand
            ? { kind: "command", draft: { name: "", aliases: [], description: "", component_id: "", parameters: {} } }
            : { kind: "flow", draft: { name: "", steps: [], description: "", step_delay_ms: 0, rehearsal_spd: 100 } })}
          >{isCommand ? t("library.workbench.newCommand") : t("library.workbench.newFlow")}</Button>
          <Button size="sm" variant="outline" onClick={() => setTransferOpen((open) => !open)}>{t("library.workbench.transferLibrary")}</Button>
        </div>
        <div className="flex min-h-0 flex-1">
          <LibraryList tab={tab} items={lib.items} loading={lib.loading} error={lib.error} filters={lib.filters} onFiltersChange={lib.setFilters} selectedId={lib.selectedId} selectedIds={selectedIds} onToggleSelect={(id) => setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])} onSelect={(id) => { setEditor(null); lib.select(id); }} />
          <div className="min-w-0 flex-1 overflow-y-auto">
            {error && <p role="alert" className="p-4 text-destructive">{error}</p>}
            <ControllerDiagnostics gatewayToken={gatewayToken} userToken={userToken} />
            <EngineerLogCenter gatewayToken={gatewayToken} userToken={userToken} />
            {transferOpen ? <LibraryTransferDialog onExport={async () => (await engineerExportLibrary(gatewayToken, userToken)).data} onImport={async (payload, strategy) => { const report = (await engineerImportLibrary(gatewayToken, userToken, payload, strategy)).data; lib.refresh(); return report; }} /> : null}
            {selectedIds.length > 0 && <div className="border-b p-3"><Button variant="destructive" onClick={() => setBatchArchive({ kind: isCommand ? "command" : "flow", ids: selectedIds })}>{t("library.workbench.batchArchive", { count: selectedIds.length })}</Button></div>}
            {validation && <div role="status" className="p-4">{validation.length ? validation.map((item) => <p key={item}>{item}</p>) : t("library.workbench.validationPassed")}</div>}
            {editor?.kind === "command" && <><CommandDraftEditor draft={editor.draft} components={components} onSave={saveCommand} />{editor.id && <Button className="m-4" onClick={() => setPublish(editor)}>{t("library.workbench.publishCommand")}</Button>}</>}
            {editor?.kind === "flow" && <><FlowDraftEditor draft={editor.draft} commands={commandLib.items as LibraryCommand[]} onSave={saveFlow} /><div className="flex gap-2 p-4"><Button variant="outline" disabled={!editor.id} onClick={() => void validate()}>{t("library.workbench.validate")}</Button>{editor.id && <Button onClick={() => setPublish(editor)}>{t("library.workbench.publishFlow")}</Button>}</div></>}
            {!editor && selected && <div className="flex gap-2 border-b p-3"><Button variant="outline" onClick={() => setPreviewOpen((open) => !open)}>{t("library.workbench.structurePreview")}</Button><Button variant="outline" onClick={() => setDuplicate({ kind: isCommand ? "command" : "flow", id: isCommand ? (selected as LibraryCommand).id : (selected as LibraryFlow).flow_id, name: `${selected.name} ${t("library.workbench.copySuffix")}` })}>{t("library.workbench.saveAs")}</Button></div>}
            {!editor && selected && <>{previewOpen ? <LibraryPreview item={selected} kind={isCommand ? "command" : "flow"} /> : null}<div className="flex gap-2 border-b p-3"><Button variant="outline" onClick={() => void begin()}>{t("library.workbench.editDraft")}</Button><Button variant="outline" onClick={() => void begin()}>{t("library.workbench.startDraft")}</Button><Button variant="destructive" onClick={() => setArchive({ kind: isCommand ? "command" : "flow", id: isCommand ? (selected as LibraryCommand).id : (selected as LibraryFlow).flow_id })}>{isCommand ? t("library.workbench.archiveCommand") : t("library.workbench.archiveFlow")}</Button></div>{isCommand ? <CommandDetail command={selected as LibraryCommand} onRun={runSelected} running={running} /> : <FlowDetail flow={selected as LibraryFlow} onRun={runSelected} running={running} />}{execution ? <ExecutionMonitor execution={execution} onControl={(action) => void controlExecution(action)} controlling={controlling} /> : null}<section aria-label={t("library.workbench.executionHistory")} className="border-t p-4"><h3 className="font-semibold">{t("library.workbench.executionHistory")}</h3><ol className="mt-2 space-y-1">{executionHistory.map((item) => <li key={item.execution_id}><button type="button" className="w-full rounded border p-2 text-left text-sm" onClick={() => setExecution(item)}>{item.source_id || item.execution_id} · {item.state}</button></li>)}</ol></section>{runResult ? <p role="status" className="p-4">{runResult}</p> : null}</>}
          </div>
        </div>
      </div>
      <AlertDialog open={!!publish} onOpenChange={(open) => !open && setPublish(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{t("library.workbench.publishTitle", { kind: publish ? entityName(publish.kind) : "" })}</AlertDialogTitle><AlertDialogDescription>{t("library.workbench.publishDescription")}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{t("library.workbench.cancel")}</AlertDialogCancel><AlertDialogAction onClick={(event) => { event.preventDefault(); void doPublish(); }}>{t("library.workbench.publish")}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
      <AlertDialog open={!!archive} onOpenChange={(open) => !open && setArchive(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{t("library.workbench.archiveTitle", { kind: archive ? entityName(archive.kind) : "" })}</AlertDialogTitle><AlertDialogDescription>{t("library.workbench.archiveDescription")}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{t("library.workbench.cancel")}</AlertDialogCancel><AlertDialogAction onClick={(event) => { event.preventDefault(); void doArchive(); }}>{t("library.workbench.archive")}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
      <AlertDialog open={!!batchArchive} onOpenChange={(open) => !open && setBatchArchive(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{`Archive selected (${batchArchive?.ids.length ?? 0})?`}</AlertDialogTitle><AlertDialogDescription>Draft-only items will be archived. Published or missing items will be skipped.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{t("library.workbench.cancel")}</AlertDialogCancel><AlertDialogAction onClick={(event) => { event.preventDefault(); void doBatchArchive(); }}>{t("library.workbench.archive")}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
      <AlertDialog open={!!duplicate} onOpenChange={(open) => !open && setDuplicate(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{t("library.workbench.saveAs")}</AlertDialogTitle><AlertDialogDescription>{t("library.workbench.saveAsDescription")}</AlertDialogDescription></AlertDialogHeader><label className="grid gap-2 text-sm">{t("library.workbench.copyName")}<input aria-label={t("library.workbench.copyName")} className="h-10 rounded-md border border-input bg-background px-3" value={duplicate?.name ?? ""} onChange={(event) => setDuplicate((current) => current ? { ...current, name: event.target.value } : null)} /></label><AlertDialogFooter><AlertDialogCancel>{t("library.workbench.cancel")}</AlertDialogCancel><AlertDialogAction disabled={!duplicate?.name.trim()} onClick={(event) => { event.preventDefault(); void doDuplicate(); }}>{t("library.workbench.createCopy")}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </div>
  );
}
