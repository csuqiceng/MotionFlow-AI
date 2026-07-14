import { useTranslation } from "react-i18next";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";

export function LibraryPreview({ item, kind }: { item: LibraryCommand | LibraryFlow; kind: "command" | "flow" }) {
  const { t } = useTranslation();
  if (kind === "command") {
    const command = item as LibraryCommand;
    return <section role="region" aria-label={t("library.workbench.structurePreview")} className="space-y-2 rounded border p-3 text-sm"><h3 className="font-semibold">{t("library.workbench.structurePreview")}</h3><p>{t("library.workbench.previewName", { name: command.name })}</p><p>{t("library.workbench.previewComponent", { component: command.component_id })}</p><h4 className="font-medium">{t("library.workbench.parameters")}</h4><dl>{Object.entries(command.parameters).map(([name, value]) => <div key={name} className="grid grid-cols-2 gap-2"><dt>{name}</dt><dd>{String(value)}</dd></div>)}</dl></section>;
  }
  const flow = item as LibraryFlow;
  return <section role="region" aria-label={t("library.workbench.structurePreview")} className="space-y-2 rounded border p-3 text-sm"><h3 className="font-semibold">{t("library.workbench.structurePreview")}</h3><p>{t("library.workbench.previewName", { name: flow.name })}</p><p>{t("library.workbench.stepDelayPreview", { delay: flow.step_delay_ms })}</p><ol className="list-decimal pl-5">{flow.steps.map((step) => <li key={String(step.step_id)}>{`${step.action} · Func${step.func_id} · ${step.spd_pct}%`}</li>)}</ol></section>;
}
