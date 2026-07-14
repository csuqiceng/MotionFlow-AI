import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";
import type { LibraryFilters, LibraryTab } from "@/robot/hooks/useRobotLibrary";

interface LibraryListProps {
  tab: LibraryTab;
  items: LibraryCommand[] | LibraryFlow[];
  loading: boolean;
  error: string | null;
  filters: LibraryFilters;
  onFiltersChange: (patch: Partial<LibraryFilters>) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function LibraryList({
  tab,
  items,
  loading,
  error,
  filters,
  onFiltersChange,
  selectedId,
  onSelect,
}: LibraryListProps) {
  const { t } = useTranslation();
  return (
    <div className="flex w-72 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border/70 bg-muted/20 p-3">
      <Input
        aria-label={t("library.search", { defaultValue: "Search" })}
        placeholder={t("library.search", { defaultValue: "Search" })}
        value={filters.q}
        onChange={(e) => onFiltersChange({ q: e.target.value })}
      />
      {tab === "commands" ? (
        <select
          aria-label={t("library.filters.risk", { defaultValue: "Risk level" })}
          className="h-8 rounded border border-border/60 bg-background px-2 text-xs"
          value={filters.risk_level}
          onChange={(e) => onFiltersChange({ risk_level: e.target.value })}
        >
          <option value="">{t("library.filters.risk", { defaultValue: "Risk level" })}</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="critical">critical</option>
        </select>
      ) : null}
      {loading ? <p className="text-xs text-muted-foreground">…</p> : null}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      {!loading && !error && items.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("library.empty", { defaultValue: "No items." })}
        </p>
      ) : null}
      <div className="flex flex-col gap-1">
        {items.map((item) => {
          const id = (item as LibraryCommand).id ?? (item as LibraryFlow).flow_id;
          const label = (item as LibraryCommand).name ?? (item as LibraryFlow).name;
          const sub =
            tab === "commands"
              ? (item as LibraryCommand).component_id ?? ""
              : `${(item as LibraryFlow).steps?.length ?? 0} steps`;
          return (
            <button
              key={id}
              type="button"
              aria-label={label}
              onClick={() => onSelect(id)}
              aria-current={selectedId === id ? "page" : undefined}
              className="flex flex-col items-start rounded px-2 py-1.5 text-left text-xs hover:bg-accent/50"
            >
              <span className="font-medium">{label}</span>
              <span className="text-muted-foreground">{sub}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
