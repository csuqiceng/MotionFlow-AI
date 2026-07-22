import { useTranslation } from "react-i18next";
import type { LibraryCommand } from "@/lib/robot-library-api";
import { cn } from "@/lib/utils";

function riskTone(risk: string): "danger" | "warn" | "ok" | "idle" {
  const r = risk.toLowerCase();
  if (r === "high" || r === "critical") return "danger";
  if (r === "medium" || r === "moderate") return "warn";
  if (r === "low" || r === "minimal") return "ok";
  return "idle";
}

function statusTone(status: string): "ok" | "warn" | "idle" {
  const s = status.toLowerCase();
  if (s === "published") return "ok";
  if (s === "draft" || s === "pending") return "warn";
  return "idle";
}

const RISK_LABEL: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
  critical: "严重",
  minimal: "极低",
};

const STATUS_LABEL: Record<string, string> = {
  published: "已发布",
  draft: "草稿",
  pending: "待审",
  archived: "已归档",
};

export function CommandDetail({ command, onRun, running = false }: { command: LibraryCommand; onRun?: (id: string) => void; running?: boolean }) {
  const { t } = useTranslation();
  const riskT = riskTone(command.risk_level);
  const statusT = statusTone(command.status);
  const riskLabel = RISK_LABEL[command.risk_level.toLowerCase()] ?? command.risk_level;
  const statusLabel = STATUS_LABEL[command.status.toLowerCase()] ?? command.status;
  const params = Object.entries(command.parameters);

  return (
    <div className="flex flex-col gap-5 p-5">
      {/* 标题 + 操作 */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-bold text-foreground">{command.name}</h2>
          {command.description ? (
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{command.description}</p>
          ) : null}
        </div>
        {command.status === "published" && onRun ? (
          <button
            type="button"
            disabled={running}
            onClick={() => onRun(command.id)}
            className="btn-primary flex h-9 shrink-0 items-center gap-2 rounded-lg px-4 text-sm"
          >
            {running ? t("library.running") : t("library.runCommand")}
          </button>
        ) : null}
      </div>

      {/* 别名 */}
      {command.aliases.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">{t("library.aliases", { defaultValue: "Aliases" })}</span>
          {command.aliases.map((alias) => (
            <span key={alias} className="status-pill status-pill--idle">
              {alias}
            </span>
          ))}
        </div>
      ) : null}

      {/* 元数据卡片 */}
      <div className="soft-card rounded-xl p-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.detail.componentId")}</p>
            <p className="data-mono mt-1 text-sm font-semibold text-foreground">{command.component_id}</p>
          </div>
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.detail.version")}</p>
            <p className="data-mono mt-1 text-sm font-semibold text-foreground">v{command.version}</p>
          </div>
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.detail.riskLevel")}</p>
            <span className={cn("status-pill mt-1", `status-pill--${riskT}`)}>
              <span className={cn("status-dot", `status-dot--${riskT}`)} />
              {riskLabel}
            </span>
          </div>
          <div className="data-cell">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("library.detail.status")}</p>
            <span className={cn("status-pill mt-1", `status-pill--${statusT}`)}>
              <span className={cn("status-dot", `status-dot--${statusT}`)} />
              {statusLabel}
            </span>
          </div>
        </div>
      </div>

      {/* 参数表 */}
      {params.length > 0 ? (
        <div className="soft-card rounded-xl p-4">
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {t("library.detail.parameters")}
          </p>
          <div className="space-y-1.5">
            {params.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-3 text-sm">
                <span className="data-mono min-w-0 truncate text-muted-foreground">{k}</span>
                <span className="data-mono shrink-0 font-medium text-foreground">{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
