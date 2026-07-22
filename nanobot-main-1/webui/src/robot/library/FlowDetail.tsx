import { useTranslation } from "react-i18next";
import type { LibraryFlow } from "@/lib/robot-library-api";
import { cn } from "@/lib/utils";

function stateTone(state: string): "ok" | "warn" | "idle" {
  const s = state.toLowerCase();
  if (s === "ready" || s === "published" || s === "running") return "ok";
  if (s === "draft" || s === "pending" || s === "paused") return "warn";
  return "idle";
}

const STATE_LABEL: Record<string, string> = {
  ready: "就绪",
  running: "运行中",
  draft: "草稿",
  pending: "待审",
  paused: "已暂停",
  archived: "已归档",
};

export function FlowDetail({ flow, onRun, running = false }: { flow: LibraryFlow; onRun?: (name: string) => void; running?: boolean }) {
  const { t } = useTranslation();
  const stateT = stateTone(flow.state);
  const stateLabel = STATE_LABEL[flow.state.toLowerCase()] ?? flow.state;
  const totalSteps = flow.steps.length;

  return (
    <div className="flex flex-col gap-5 p-5">
      {/* 标题 + 操作 */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-bold text-foreground">{flow.name}</h2>
          {flow.description ? (
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{flow.description}</p>
          ) : null}
        </div>
        {onRun ? (
          <button
            type="button"
            disabled={running}
            onClick={() => onRun(flow.name)}
            className="btn-primary flex h-9 shrink-0 items-center gap-2 rounded-lg px-4 text-sm"
          >
            {running ? t("library.running") : t("library.runFlow")}
          </button>
        ) : null}
      </div>

      {/* 元数据卡片 */}
      <div className="soft-card rounded-xl p-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.workbench.state")}</p>
            <span className={cn("status-pill mt-1", `status-pill--${stateT}`)}>
              <span className={cn("status-dot", `status-dot--${stateT}`)} />
              {stateLabel}
            </span>
          </div>
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.workbench.version")}</p>
            <p className="data-mono mt-1 text-sm font-semibold text-foreground">v{flow.version}</p>
          </div>
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.workbench.confirmed")}</p>
            <span className={cn("status-pill mt-1", flow.confirmed ? "status-pill--ok" : "status-pill--warn")}>
              <span className={cn("status-dot", flow.confirmed ? "status-dot--ok" : "status-dot--warn")} />
              {flow.confirmed
                ? t("library.yes", { defaultValue: "yes" })
                : t("library.no", { defaultValue: "no" })}
            </span>
          </div>
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.workbench.stepDelay")}</p>
            <p className="data-mono mt-1 text-sm font-semibold text-foreground">{flow.step_delay_ms} ms</p>
          </div>
        </div>
      </div>

      {/* 步骤列表 */}
      <div className="soft-card rounded-xl p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {t("library.workbench.steps")}
          </p>
          <span className="status-pill status-pill--idle">{totalSteps}</span>
        </div>
        <ol className="flex flex-col gap-2">
          {flow.steps.map((step, index) => (
            <li
              key={index}
              className="flex items-start gap-3 rounded-lg border border-border/60 bg-background/40 p-3"
            >
              <span className="data-mono flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-xs font-bold text-[hsl(var(--primary))]">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="data-mono truncate text-sm font-medium text-foreground">
                    {step.action}
                  </span>
                  <span className="status-pill status-pill--info shrink-0">
                    {t("library.workbench.function", { id: step.func_id })}
                  </span>
                </div>
                {step.description ? (
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {step.description}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
