import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { EngineerTransferReport } from "@/lib/engineer-workbench-api";

export function LibraryTransferDialog({ onImport, onExport }: { onImport: (payload: Record<string, unknown>, strategy: "skip" | "rename" | "overwrite-draft-only") => Promise<EngineerTransferReport>; onExport: () => Promise<Record<string, unknown>> }) {
  const { t } = useTranslation();
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [strategy, setStrategy] = useState<"skip" | "rename" | "overwrite-draft-only">("skip");
  const [report, setReport] = useState<EngineerTransferReport | null>(null);
  const [error, setError] = useState("");
  const readFile = async (file: File | undefined) => {
    if (!file) return;
    try { setPayload(JSON.parse(await file.text()) as Record<string, unknown>); setError(""); } catch { setPayload(null); setError(t("library.workbench.invalidJsonFile")); }
  };
  const exportFile = async () => {
    const data = await onExport();
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    anchor.download = "robot-library.json"; anchor.click(); URL.revokeObjectURL(anchor.href);
  };
  return <section aria-label={t("library.workbench.libraryTransfer")} className="space-y-3 border-b p-3">
    <div className="flex gap-2"><Button variant="outline" onClick={() => void exportFile()}>{t("library.workbench.exportLibrary")}</Button></div>
    <label className="grid gap-1 text-sm">{t("library.workbench.importJsonFile")}<input aria-label={t("library.workbench.importJsonFile")} type="file" accept="application/json,.json" onChange={(e) => void readFile(e.target.files?.[0])} /></label>
    <label className="grid gap-1 text-sm">{t("library.workbench.conflictHandling")}<select aria-label={t("library.workbench.conflictHandling")} value={strategy} onChange={(e) => setStrategy(e.target.value as typeof strategy)}><option value="skip">{t("library.workbench.skipConflicts")}</option><option value="rename">{t("library.workbench.renameConflicts")}</option><option value="overwrite-draft-only">{t("library.workbench.overwriteDraftOnly")}</option></select></label>
    <Button disabled={!payload} onClick={() => { if (payload) void onImport(payload, strategy).then(setReport).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause))); }}>{t("library.workbench.importLibrary")}</Button>
    {error ? <p role="alert">{error}</p> : null}
    {report ? <div role="status"><p>{t("library.workbench.importedCommands", { items: report.commands.imported.join(", ") || t("library.workbench.none") })}</p><p>{t("library.workbench.importedFlows", { items: report.flows.imported.join(", ") || t("library.workbench.none") })}</p>{report.errors.map((item) => <p key={item}>{item}</p>)}</div> : null}
  </section>;
}
