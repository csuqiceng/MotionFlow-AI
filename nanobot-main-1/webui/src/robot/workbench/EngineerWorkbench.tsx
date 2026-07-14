import { useState } from "react";
import { EngineerConflictError, engineerArchiveCommand, engineerArchiveFlow, engineerCreateCommand, engineerCreateFlow, engineerPublishCommand, engineerPublishFlow, engineerStartCommandDraft, engineerStartFlowDraft, engineerUpdateCommandDraft, engineerUpdateFlowDraft, engineerValidateFlowDraft, type EngineerCommandDraft, type EngineerEntity, type EngineerFlowDraft } from "@/lib/engineer-workbench-api";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";
import { Button } from "@/components/ui/button";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryList } from "@/robot/library/LibraryList";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { CommandDraftEditor } from "./CommandDraftEditor";
import { FlowDraftEditor } from "./FlowDraftEditor";

type Editor = { kind: "command"; id?: string; draft: EngineerCommandDraft; revision?: number } | { kind: "flow"; id?: string; draft: EngineerFlowDraft; revision?: number } | null;
const commandDraft = (item: LibraryCommand): EngineerCommandDraft => ({ name: item.name, aliases: item.aliases, description: item.description, component_id: item.component_id, parameters: item.parameters });
const flowDraft = (item: LibraryFlow): EngineerFlowDraft => ({ name: item.name, description: item.description, step_delay_ms: item.step_delay_ms, rehearsal_spd: item.rehearsal_spd, steps: item.steps });
const entityDraft = (entity: EngineerEntity) => (entity.draft ?? entity) as Record<string, unknown>;
const errorMessage = (error: unknown) => error instanceof EngineerConflictError ? `${error.message} Current revision: ${error.currentRevision ?? "unknown"}.` : error instanceof Error ? error.message : String(error);

export function EngineerWorkbench({ role, gatewayToken, userToken }: { role: "operator" | "engineer"; gatewayToken: string; userToken: string }) {
  if (role !== "engineer") return null;
  return <Workbench gatewayToken={gatewayToken} userToken={userToken} />;
}

function Workbench({ gatewayToken, userToken }: { gatewayToken: string; userToken: string }) {
  const [tab, setTab] = useState<LibraryTab>("commands");
  const lib = useRobotLibrary(gatewayToken, tab);
  const [editor, setEditor] = useState<Editor>(null);
  const [publish, setPublish] = useState<Editor>(null);
  const [archive, setArchive] = useState<Pick<NonNullable<Editor>, "kind" | "id"> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<string[] | null>(null);
  const isCommand = tab === "commands";
  const selected = lib.detail as LibraryCommand | LibraryFlow | null;
  const begin = async () => {
    if (!selected) return; setError(null);
    try {
      const result = isCommand ? await engineerStartCommandDraft(gatewayToken, userToken, (selected as LibraryCommand).id) : await engineerStartFlowDraft(gatewayToken, userToken, (selected as LibraryFlow).flow_id);
      const entity = result.data as EngineerEntity; const draft = entityDraft(entity); const revision = Number(draft.revision ?? 1);
      setEditor(isCommand ? { kind: "command", id: (selected as LibraryCommand).id, draft: { ...commandDraft(selected as LibraryCommand), ...(draft as Partial<EngineerCommandDraft>) }, revision } : { kind: "flow", id: (selected as LibraryFlow).flow_id, draft: { ...flowDraft(selected as LibraryFlow), ...(draft as Partial<EngineerFlowDraft>) }, revision });
    } catch (cause) { setError(errorMessage(cause)); }
  };
  const saveCommand = async (draft: EngineerCommandDraft) => { try { if (!editor?.id || editor.kind !== "command") { const entity = (await engineerCreateCommand(gatewayToken, userToken, draft)).data; setEditor({ kind: "command", id: String(entity.command_id), draft, revision: Number(entityDraft(entity).revision ?? 1) }); } else { const entity = (await engineerUpdateCommandDraft(gatewayToken, userToken, editor.id, { ...draft, expected_revision: editor.revision ?? 0 })).data; setEditor({ ...editor, draft, revision: Number(entityDraft(entity).revision ?? editor.revision) }); } lib.refresh(); } catch (cause) { setError(errorMessage(cause)); } };
  const saveFlow = async (draft: EngineerFlowDraft) => { try { if (!editor?.id || editor.kind !== "flow") { const entity = (await engineerCreateFlow(gatewayToken, userToken, draft)).data; setEditor({ kind: "flow", id: String(entity.flow_id), draft, revision: Number(entityDraft(entity).revision ?? 1) }); } else { const entity = (await engineerUpdateFlowDraft(gatewayToken, userToken, editor.id, { ...draft, expected_revision: editor.revision ?? 0 })).data; setEditor({ ...editor, draft, revision: Number(entityDraft(entity).revision ?? editor.revision) }); } lib.refresh(); } catch (cause) { setError(errorMessage(cause)); } };
  const validate = async () => { if (editor?.kind !== "flow" || !editor.id) return; try { setValidation((await engineerValidateFlowDraft(gatewayToken, userToken, editor.id)).data.errors); } catch (cause) { setError(errorMessage(cause)); } };
  const doPublish = async () => { if (!publish?.id) return; try { if (publish.kind === "command") await engineerPublishCommand(gatewayToken, userToken, publish.id); else await engineerPublishFlow(gatewayToken, userToken, publish.id); setEditor(null); setPublish(null); lib.refresh(); } catch (cause) { setError(errorMessage(cause)); setPublish(null); } };
  const doArchive = async () => { if (!archive?.id) return; try { if (archive.kind === "command") await engineerArchiveCommand(gatewayToken, userToken, archive.id); else await engineerArchiveFlow(gatewayToken, userToken, archive.id); setArchive(null); setEditor(null); lib.refresh(); } catch (cause) { setError(errorMessage(cause)); setArchive(null); } };
  return <div data-testid="engineer-workbench" className="flex h-full w-full"><div className="flex min-w-0 flex-1 flex-col"><div role="tablist" className="flex gap-2 border-b p-2"><button role="tab" aria-selected={isCommand} onClick={() => { setTab("commands"); setEditor(null); }}>Commands</button><button role="tab" aria-selected={!isCommand} onClick={() => { setTab("flows"); setEditor(null); }}>Flows</button><Button className="ml-auto" size="sm" onClick={() => setEditor(isCommand ? { kind: "command", draft: { name: "", aliases: [], description: "", component_id: "", parameters: {} } } : { kind: "flow", draft: { name: "", steps: [], description: "", step_delay_ms: 0, rehearsal_spd: 100 } })}>New {isCommand ? "command" : "flow"}</Button></div><div className="flex min-h-0 flex-1"><LibraryList tab={tab} items={lib.items} loading={lib.loading} error={lib.error} filters={lib.filters} onFiltersChange={lib.setFilters} selectedId={lib.selectedId} onSelect={(id) => { setEditor(null); lib.select(id); }} /><div className="min-w-0 flex-1 overflow-y-auto">{error && <p role="alert" className="p-4 text-destructive">{error}</p>}{validation && <div role="status" className="p-4">{validation.length ? validation.map((item) => <p key={item}>{item}</p>) : "Validation passed."}</div>}{editor?.kind === "command" && <><CommandDraftEditor draft={editor.draft} onSave={saveCommand} />{editor.id && <Button className="m-4" onClick={() => setPublish(editor)}>Publish command</Button>}</>}{editor?.kind === "flow" && <><FlowDraftEditor draft={editor.draft} onSave={saveFlow} /><div className="flex gap-2 p-4"><Button variant="outline" disabled={!editor.id} onClick={() => void validate()}>Validate</Button>{editor.id && <Button onClick={() => setPublish(editor)}>Publish flow</Button>}</div></>}{!editor && selected && <><div className="flex gap-2 border-b p-3"><Button variant="outline" onClick={() => void begin()}>Edit draft</Button><Button variant="outline" onClick={() => void begin()}>Start draft to publish</Button><Button variant="destructive" onClick={() => setArchive({ kind: isCommand ? "command" : "flow", id: isCommand ? (selected as LibraryCommand).id : (selected as LibraryFlow).flow_id })}>Archive {isCommand ? "command" : "flow"}</Button></div>{isCommand ? <CommandDetail command={selected as LibraryCommand} /> : <FlowDetail flow={selected as LibraryFlow} />}</>}</div></div></div><AlertDialog open={!!publish} onOpenChange={(open) => !open && setPublish(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Publish {publish?.kind}?</AlertDialogTitle><AlertDialogDescription>Publishing makes this draft available in the library. It does not execute the robot.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={(event) => { event.preventDefault(); void doPublish(); }}>Publish</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog><AlertDialog open={!!archive} onOpenChange={(open) => !open && setArchive(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Archive {archive?.kind}?</AlertDialogTitle><AlertDialogDescription>Archiving removes this item from the editable library. It does not execute the robot.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={(event) => { event.preventDefault(); void doArchive(); }}>Archive</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></div>;
}
