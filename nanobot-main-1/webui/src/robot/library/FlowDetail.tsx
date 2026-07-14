import { useTranslation } from "react-i18next";
import type { LibraryFlow } from "@/lib/robot-library-api";

export function FlowDetail({ flow }: { flow: LibraryFlow }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 p-4">
      <h2 className="text-lg font-semibold">{flow.name}</h2>
      {flow.description ? (
        <p className="text-sm text-muted-foreground">{flow.description}</p>
      ) : null}
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">{t("library.workbench.state")}</dt>
          <dd>{flow.state}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">{t("library.workbench.version")}</dt>
          <dd>{flow.version}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">{t("library.workbench.confirmed")}</dt>
          <dd>
            {flow.confirmed
              ? t("library.yes", { defaultValue: "yes" })
              : t("library.no", { defaultValue: "no" })}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">{t("library.workbench.stepDelay")}</dt>
          <dd>{flow.step_delay_ms}</dd>
        </div>
      </dl>
      <div>
        <p className="text-xs text-muted-foreground">{t("library.workbench.steps")}</p>
        <ol className="mt-1 flex flex-col gap-1 text-xs">
          {flow.steps.map((step, index) => (
            <li key={index} className="rounded border border-border/40 p-2">
              <span className="font-mono">#{index + 1}</span> {step.action}
              <span className="ml-2 text-muted-foreground">{t("library.workbench.function", { id: step.func_id })}</span>
              {step.description ? (
                <p className="text-muted-foreground">{step.description}</p>
              ) : null}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
