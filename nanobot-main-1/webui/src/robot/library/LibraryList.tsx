import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

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
  selectedIds?: string[];
  onToggleSelect?: (id: string) => void;
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
  selectedIds = [],
  onToggleSelect,
}: LibraryListProps) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
      <Input
        aria-label={t("library.search", { defaultValue: "Search" })}
        placeholder={t("library.search", { defaultValue: "Search" })}
        value={filters.q}
        onChange={(e) => onFiltersChange({ q: e.target.value })}
        className="field-input rounded-[0.75rem] border-border/50 bg-sidebar-accent/50 text-[13px]"
      />
      {loading ? <p className="px-1 text-xs text-muted-foreground">…</p> : null}
      {error ? <p className="px-1 text-xs text-destructive">{error}</p> : null}
      {!loading && !error && items.length === 0 ? (
        <p className="px-1 text-xs text-muted-foreground">
          {t("library.empty", { defaultValue: "No items." })}
        </p>
      ) : null}
      <div className="flex flex-col gap-0.5">
        {items.map((item) => {
          const id = (item as LibraryCommand).id ?? (item as LibraryFlow).flow_id;
          const label = (item as LibraryCommand).name ?? (item as LibraryFlow).name;
          const sub =
            tab === "commands"
              ? (item as LibraryCommand).component_id ?? ""
              : `${(item as LibraryFlow).steps?.length ?? 0} steps`;
          const active = selectedId === id;
          return (
            <div key={id} className="flex items-center gap-1">
              {onToggleSelect ? <input type="checkbox" aria-label={`Select ${label}`} checked={selectedIds.includes(id)} onChange={() => onToggleSelect(id)} className="ml-0.5" /> : null}
              <button
                type="button"
                aria-label={label}
                onClick={() => onSelect(id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex min-w-0 flex-1 flex-col items-start rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors",
                  active
                    ? "bg-[hsl(var(--accent-primary)/0.15)] text-sidebar-accent-foreground shadow-[inset_0_0_0_1px_hsl(var(--accent-primary)/0.22)]"
                    : "text-sidebar-foreground/82 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                )}
              >
                <span className="font-medium">{label}</span>
                <span className="text-[11px] text-muted-foreground/72">{sub}</span>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
