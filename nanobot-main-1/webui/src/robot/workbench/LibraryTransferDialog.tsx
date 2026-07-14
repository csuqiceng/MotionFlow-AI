import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { EngineerTransferReport } from "@/lib/engineer-workbench-api";

export function LibraryTransferDialog({ onImport, onExport }: { onImport: (payload: Record<string, unknown>, strategy: "skip" | "rename" | "overwrite-draft-only") => Promise<EngineerTransferReport>; onExport: () => Promise<Record<string, unknown>> }) {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [strategy, setStrategy] = useState<"skip" | "rename" | "overwrite-draft-only">("skip");
  const [report, setReport] = useState<EngineerTransferReport | null>(null);
  const [error, setError] = useState("");
  const readFile = async (file: File | undefined) => {
    if (!file) return;
    try { setPayload(JSON.parse(await file.text()) as Record<string, unknown>); setError(""); } catch { setPayload(null); setError("Invalid JSON file."); }
  };
  const exportFile = async () => {
    const data = await onExport();
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    anchor.download = "robot-library.json"; anchor.click(); URL.revokeObjectURL(anchor.href);
  };
  return <section aria-label="Library transfer" className="space-y-3 border-b p-3">
    <div className="flex gap-2"><Button variant="outline" onClick={() => void exportFile()}>Export library</Button></div>
    <label className="grid gap-1 text-sm">Import JSON file<input aria-label="Import JSON file" type="file" accept="application/json,.json" onChange={(e) => void readFile(e.target.files?.[0])} /></label>
    <label className="grid gap-1 text-sm">Conflict handling<select aria-label="Conflict handling" value={strategy} onChange={(e) => setStrategy(e.target.value as typeof strategy)}><option value="skip">Skip conflicts</option><option value="rename">Rename conflicts</option><option value="overwrite-draft-only">Overwrite draft-only</option></select></label>
    <Button disabled={!payload} onClick={() => { if (payload) void onImport(payload, strategy).then(setReport).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause))); }}>Import library</Button>
    {error ? <p role="alert">{error}</p> : null}
    {report ? <div role="status"><p>{`Imported commands: ${report.commands.imported.join(", ") || "none"}`}</p><p>{`Imported flows: ${report.flows.imported.join(", ") || "none"}`}</p>{report.errors.map((item) => <p key={item}>{item}</p>)}</div> : null}
  </section>;
}
