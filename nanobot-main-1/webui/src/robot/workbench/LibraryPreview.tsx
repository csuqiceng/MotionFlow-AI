import { useTranslation } from "react-i18next";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";

export function LibraryPreview({ item, kind }: { item: LibraryCommand | LibraryFlow; kind: "command" | "flow" }) {
  const { t } = useTranslation();
  if (kind === "command") {
    const command = item as LibraryCommand;
    return <section role="region" aria-label={t("library.workbench.structurePreview")} className="soft-card rounded-xl p-4 text-sm"><h3 className="mb-2 font-semibold text-foreground">{t("library.workbench.structurePreview")}</h3><p className="text-muted-foreground">{t("library.workbench.previewName", { name: command.name })}</p><p className="text-muted-foreground">{t("library.workbench.previewComponent", { component: command.component_id })}</p><h4 className="mt-2 font-medium text-foreground">{t("library.workbench.parameters")}</h4><dl className="mt-1 space-y-1">{Object.entries(command.parameters).map(([name, value]) => <div key={name} className="grid grid-cols-2 gap-2"><dt className="data-mono text-muted-foreground">{name}</dt><dd className="data-mono">{String(value)}</dd></div>)}</dl></section>;
  }
  const flow = item as LibraryFlow;
  return <section role="region" aria-label={t("library.workbench.structurePreview")} className="soft-card rounded-xl p-4 text-sm"><h3 className="mb-2 font-semibold text-foreground">{t("library.workbench.structurePreview")}</h3><p className="text-muted-foreground">{t("library.workbench.previewName", { name: flow.name })}</p><p className="text-muted-foreground">{t("library.workbench.stepDelayPreview", { delay: flow.step_delay_ms })}</p><ol className="mt-2 list-decimal pl-5 text-muted-foreground">{flow.steps.map((step) => <li key={String(step.step_id)}>{`${step.action} · Func${step.func_id} · ${step.spd_pct}%`}</li>)}</ol></section>;
}
