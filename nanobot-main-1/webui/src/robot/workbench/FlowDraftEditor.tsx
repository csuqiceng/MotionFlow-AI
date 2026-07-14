import { useEffect, useState } from "react";
import type { EngineerFlowDraft, EngineerFlowStep } from "@/lib/engineer-workbench-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type EditableStep = Omit<EngineerFlowStep, "params"> & { params: Record<string, unknown> | string };
type EditorDraft = Omit<EngineerFlowDraft, "steps"> & { steps: EditableStep[] };
const blank = (index: number): EditableStep => ({ step_id: index + 1, action: "", func_id: 0, params: {}, position_name: null, spd_pct: 100, description: "" });

export function FlowDraftEditor({ draft, onSave, saving = false }: { draft: EngineerFlowDraft; onSave: (draft: EngineerFlowDraft) => void | Promise<void>; saving?: boolean }) {
  const [value, setValue] = useState<EditorDraft>(draft);
  const [errors, setErrors] = useState<Record<number, string>>({});
  useEffect(() => { setValue(draft); setErrors({}); }, [draft]);
  const patch = (index: number, next: Partial<EditableStep>) => setValue((current) => ({ ...current, steps: current.steps.map((step, i) => i === index ? { ...step, ...next } : step) }));
  const move = (index: number, offset: number) => setValue((current) => { const steps = [...current.steps]; const target = index + offset; if (target < 0 || target >= steps.length) return current; [steps[index], steps[target]] = [steps[target], steps[index]]; return { ...current, steps }; });
  const submit = () => { const nextErrors: Record<number, string> = {}; const steps = value.steps.map((step, index) => { try { const params = typeof step.params === "string" ? JSON.parse(step.params) : step.params; if (!params || Array.isArray(params) || typeof params !== "object") throw new Error("Parameters must be a JSON object."); return { ...step, params } as EngineerFlowStep; } catch (error) { nextErrors[index] = error instanceof Error ? error.message : "Parameters must be valid JSON."; return step as EngineerFlowStep; } }); setErrors(nextErrors); if (!Object.keys(nextErrors).length) void onSave({ ...value, steps }); };
  return <form className="flex flex-col gap-3 p-4" onSubmit={(event) => { event.preventDefault(); submit(); }}>
    <h2 className="text-lg font-semibold">Flow draft</h2>
    <label>Name<Input aria-label="Flow name" value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></label>
    <label>Description<textarea aria-label="Flow description" value={value.description ?? ""} onChange={(e) => setValue({ ...value, description: e.target.value })} /></label>
    <label>Step delay ms<Input aria-label="Step delay ms" type="number" value={value.step_delay_ms ?? 0} onChange={(e) => setValue({ ...value, step_delay_ms: Number(e.target.value) })} /></label>
    <label>Rehearsal speed<Input aria-label="Rehearsal speed" type="number" value={value.rehearsal_spd ?? 100} onChange={(e) => setValue({ ...value, rehearsal_spd: Number(e.target.value) })} /></label>
    <Button type="button" onClick={() => setValue((current) => ({ ...current, steps: [...current.steps, blank(current.steps.length)] }))}>Add step</Button>
    {value.steps.map((step, index) => <fieldset key={`${step.step_id}-${index}`} className="grid gap-2 rounded border p-2"><legend>Step {index + 1}</legend><Input aria-label={`Step ${index + 1} id`} type="number" value={step.step_id} onChange={(e) => patch(index, { step_id: Number(e.target.value) })} /><Input aria-label={`Step ${index + 1} action`} value={step.action} onChange={(e) => patch(index, { action: e.target.value })} /><Input aria-label={`Step ${index + 1} function`} type="number" value={step.func_id} onChange={(e) => patch(index, { func_id: Number(e.target.value) })} /><Input aria-label={`Step ${index + 1} speed`} type="number" value={step.spd_pct} onChange={(e) => patch(index, { spd_pct: Number(e.target.value) })} /><Input aria-label={`Step ${index + 1} position name`} value={step.position_name ?? ""} onChange={(e) => patch(index, { position_name: e.target.value || null })} /><Input aria-label={`Step ${index + 1} description`} value={step.description ?? ""} onChange={(e) => patch(index, { description: e.target.value })} /><textarea aria-label={`Step ${index + 1} parameters JSON`} value={typeof step.params === "string" ? step.params : JSON.stringify(step.params)} onChange={(e) => patch(index, { params: e.target.value })} />{errors[index] && <p role="alert">{errors[index]}</p>}<div><Button type="button" aria-label={`Move step ${index + 1} up`} onClick={() => move(index, -1)}>Up</Button><Button type="button" aria-label={`Move step ${index + 1} down`} onClick={() => move(index, 1)}>Down</Button><Button type="button" aria-label={`Remove step ${index + 1}`} onClick={() => setValue((current) => ({ ...current, steps: current.steps.filter((_, i) => i !== index) }))}>Remove</Button></div></fieldset>)}
    <Button type="submit" disabled={saving}>Save draft</Button>
  </form>;
}
