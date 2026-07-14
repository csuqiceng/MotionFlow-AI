import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";

export function LibraryPreview({ item, kind }: { item: LibraryCommand | LibraryFlow; kind: "command" | "flow" }) {
  if (kind === "command") {
    const command = item as LibraryCommand;
    return <section role="region" aria-label="Structure preview" className="space-y-2 rounded border p-3 text-sm"><h3 className="font-semibold">Structure preview</h3><p>{`Name: ${command.name}`}</p><p>{`Component: ${command.component_id}`}</p><h4 className="font-medium">Parameters</h4><dl>{Object.entries(command.parameters).map(([name, value]) => <div key={name} className="grid grid-cols-2 gap-2"><dt>{name}</dt><dd>{String(value)}</dd></div>)}</dl></section>;
  }
  const flow = item as LibraryFlow;
  return <section role="region" aria-label="Structure preview" className="space-y-2 rounded border p-3 text-sm"><h3 className="font-semibold">Structure preview</h3><p>{`Name: ${flow.name}`}</p><p>{`Step delay: ${flow.step_delay_ms} ms`}</p><ol className="list-decimal pl-5">{flow.steps.map((step) => <li key={String(step.step_id)}>{`${step.action} · Func${step.func_id} · ${step.spd_pct}%`}</li>)}</ol></section>;
}
