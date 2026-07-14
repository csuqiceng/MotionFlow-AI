import type { EngineerFlowStep } from "@/lib/engineer-workbench-api";

const renumber = (steps: EngineerFlowStep[]): EngineerFlowStep[] =>
  steps.map((step, index) => ({ ...step, step_id: index + 1 }));

export function moveFlowStep(steps: EngineerFlowStep[], from: number, to: number): EngineerFlowStep[] {
  if (from < 0 || to < 0 || from >= steps.length || to >= steps.length || from === to) return steps;
  const next = [...steps];
  const [step] = next.splice(from, 1);
  next.splice(to, 0, step);
  return renumber(next);
}

export function cloneFlowStep(steps: EngineerFlowStep[], index: number): EngineerFlowStep[] {
  const source = steps[index];
  if (!source) return steps;
  const next = [...steps];
  next.splice(index + 1, 0, { ...source, params: structuredClone(source.params) });
  return renumber(next);
}

export function removeFlowStep(steps: EngineerFlowStep[], index: number): EngineerFlowStep[] {
  return renumber(steps.filter((_, current) => current !== index));
}
