import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { EngineerFlowDraft, EngineerFlowStep } from "@/lib/engineer-workbench-api";
import type { LibraryCommand } from "@/lib/robot-library-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cloneFlowStep, moveFlowStep, removeFlowStep } from "./flow-steps";

type EditableStep = Omit<EngineerFlowStep, "params"> & { params: Record<string, unknown> | string };
type EditorDraft = Omit<EngineerFlowDraft, "steps"> & { steps: EditableStep[] };
const blank = (index: number): EditableStep => ({ step_id: index + 1, action: "", func_id: 0, params: {}, position_name: null, spd_pct: 100, description: "" });

const componentFunc: Record<string, number> = { system_action: 104, linear_move: 108, delay: 110, io_write: 120 };

export function FlowDraftEditor({ draft, commands = [], onSave, saving = false }: { draft: EngineerFlowDraft; commands?: LibraryCommand[]; onSave: (draft: EngineerFlowDraft) => void | Promise<void>; saving?: boolean }) {
  const { t } = useTranslation();
  const [value, setValue] = useState<EditorDraft>(draft);
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [selectedCommandId, setSelectedCommandId] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  useEffect(() => { setValue(draft); setErrors({}); }, [draft]);
  const patch = (index: number, next: Partial<EditableStep>) => setValue((current) => ({ ...current, steps: current.steps.map((step, i) => i === index ? { ...step, ...next } : step) }));
  const move = (index: number, offset: number) => setValue((current) => ({ ...current, steps: moveFlowStep(current.steps as EngineerFlowStep[], index, index + offset) }));
  const addSelected = () => {
    const command = commands.find((item) => item.id === selectedCommandId);
    if (!command) return;
    setValue((current) => ({ ...current, steps: [...current.steps, { step_id: current.steps.length + 1, action: command.name, func_id: componentFunc[command.component_id] ?? 0, params: command.parameters, position_name: null, spd_pct: Number(command.parameters.spd_pct ?? 100), description: command.description ?? "" }] }));
  };
  const submit = () => { const nextErrors: Record<number, string> = {}; const steps = value.steps.map((step, index) => { try { const params = typeof step.params === "string" ? JSON.parse(step.params) : step.params; if (!params || Array.isArray(params) || typeof params !== "object") throw new Error(t("library.workbench.invalidParametersObject")); return { ...step, params } as EngineerFlowStep; } catch (error) { nextErrors[index] = error instanceof Error ? error.message : t("library.workbench.invalidParametersJson"); return step as EngineerFlowStep; } }); setErrors(nextErrors); if (!Object.keys(nextErrors).length) void onSave({ ...value, steps }); };
  return <form className="flex flex-col gap-3 p-4" onSubmit={(event) => { event.preventDefault(); submit(); }}>
    <h2 className="text-lg font-semibold">{t("library.workbench.flowDraft")}</h2>
    <label>{t("library.workbench.name")}<Input aria-label={t("library.workbench.flowName")} value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></label>
    <label>{t("library.workbench.description")}<textarea aria-label={t("library.workbench.description")} value={value.description ?? ""} onChange={(e) => setValue({ ...value, description: e.target.value })} /></label>
    <label>{t("library.workbench.stepDelayMs")}<Input aria-label={t("library.workbench.stepDelayMs")} type="number" value={value.step_delay_ms ?? 0} onChange={(e) => setValue({ ...value, step_delay_ms: Number(e.target.value) })} /></label>
    <label>{t("library.workbench.rehearsalSpeed")}<Input aria-label={t("library.workbench.rehearsalSpeed")} type="number" value={value.rehearsal_spd ?? 100} onChange={(e) => setValue({ ...value, rehearsal_spd: Number(e.target.value) })} /></label>
    {commands.length > 0 ? <div className="flex gap-2"><label className="flex-1">{t("library.workbench.availableCommands")}<select aria-label={t("library.workbench.availableCommands")} className="mt-1 h-10 w-full rounded border border-input bg-background px-2" value={selectedCommandId} onChange={(event) => setSelectedCommandId(event.target.value)}><option value="">{t("library.workbench.selectCommand")}</option>{commands.map((command) => <option key={command.id} value={command.id}>{command.name}</option>)}</select></label><Button className="self-end" type="button" disabled={!selectedCommandId} onClick={addSelected}>{t("library.workbench.addStep")}</Button></div> : <Button type="button" onClick={() => setValue((current) => ({ ...current, steps: [...current.steps, blank(current.steps.length)] }))}>{t("library.workbench.addStep")}</Button>}
    {value.steps.map((step, index) => <fieldset key={`${step.step_id}-${index}`} draggable onDragStart={() => setDragIndex(index)} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (dragIndex !== null) setValue((current) => ({ ...current, steps: moveFlowStep(current.steps as EngineerFlowStep[], dragIndex, index) })); setDragIndex(null); }} className="grid gap-2 rounded border p-2"><legend>{commands.length > 0 ? `${index + 1}. ${step.action}` : t("library.workbench.step", { number: index + 1 })}</legend>{commands.length === 0 && <><Input aria-label={t("library.workbench.stepId", { number: index + 1 })} type="number" value={step.step_id} onChange={(e) => patch(index, { step_id: Number(e.target.value) })} /><Input aria-label={t("library.workbench.stepAction", { number: index + 1 })} value={step.action} onChange={(e) => patch(index, { action: e.target.value })} /><Input aria-label={t("library.workbench.stepFunction", { number: index + 1 })} type="number" value={step.func_id} onChange={(e) => patch(index, { func_id: Number(e.target.value) })} /></>}<Input aria-label={t("library.workbench.stepSpeed", { number: index + 1 })} type="number" value={step.spd_pct} onChange={(e) => patch(index, { spd_pct: Number(e.target.value) })} />{commands.length === 0 && <textarea aria-label={t("library.workbench.stepParametersJson", { number: index + 1 })} value={typeof step.params === "string" ? step.params : JSON.stringify(step.params)} onChange={(e) => patch(index, { params: e.target.value })} />}{errors[index] && <p role="alert">{errors[index]}</p>}<div><Button type="button" aria-label={`复制步骤 ${index + 1}`} onClick={() => setValue((current) => ({ ...current, steps: cloneFlowStep(current.steps as EngineerFlowStep[], index) }))}>复制</Button><Button type="button" aria-label={t("library.workbench.moveStepUp", { number: index + 1 })} onClick={() => move(index, -1)}>{t("library.workbench.moveUp")}</Button><Button type="button" aria-label={t("library.workbench.moveStepDown", { number: index + 1 })} onClick={() => move(index, 1)}>{t("library.workbench.moveDown")}</Button><Button type="button" aria-label={t("library.workbench.removeStep", { number: index + 1 })} onClick={() => setValue((current) => ({ ...current, steps: removeFlowStep(current.steps as EngineerFlowStep[], index) }))}>{t("library.workbench.remove")}</Button></div></fieldset>)}
    <Button type="submit" disabled={saving}>{t("library.workbench.saveDraft")}</Button>
  </form>;
}
