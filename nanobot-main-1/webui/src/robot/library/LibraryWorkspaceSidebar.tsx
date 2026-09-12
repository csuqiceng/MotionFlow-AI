import { ChevronLeft, MapPinned, Plus, SquareTerminal, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";
import type { LibraryFilters, LibraryTab } from "@/robot/hooks/useRobotLibrary";
import { LibraryList } from "@/robot/library/LibraryList";

export function LibraryWorkspaceSidebar({
  tab,
  onTabChange,
  items,
  loading,
  error,
  filters,
  onFiltersChange,
  selectedId,
  onSelect,
  onBackToChat,
  onCreate,
}: {
  tab: LibraryTab;
  onTabChange: (tab: LibraryTab) => void;
  items: LibraryCommand[] | LibraryFlow[];
  loading: boolean;
  error: string | null;
  filters: LibraryFilters;
  onFiltersChange: (patch: Partial<LibraryFilters>) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onBackToChat?: () => void;
  onCreate?: () => void;
}) {
  const { t } = useTranslation();
  const isCommand = tab === "commands";

  return (
    <aside className="flex h-[46%] min-h-[18rem] w-full shrink-0 flex-col border-b border-sidebar-border bg-sidebar/78 backdrop-blur-sm md:h-full md:min-h-0 md:w-[272px] md:border-b-0 md:border-r">
      <div className="shrink-0 px-4 pb-3 pt-4 md:pt-5">
        {onBackToChat ? (
          <button
            type="button"
            onClick={onBackToChat}
            className="mb-5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-foreground"
          >
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
            {t("settings.backToChat")}
          </button>
        ) : null}
        <div className="flex items-center gap-3 px-1">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[13px] bg-[hsl(var(--accent-primary)/0.12)] text-[hsl(var(--accent-primary))]">
            <MapPinned className="h-[18px] w-[18px]" aria-hidden />
          </div>
          <h2 className="text-[19px] font-normal text-sidebar-foreground">
            {t("sidebar.commandLibrary")}
          </h2>
        </div>
      </div>

      <nav className="grid shrink-0 grid-cols-2 gap-1 px-3 pb-3 md:block md:space-y-1" aria-label={t("sidebar.commandLibrary")}>
        {([
          ["commands", SquareTerminal, t("library.tabs.commands", { defaultValue: "Commands" })],
          ["flows", Workflow, t("library.tabs.flows", { defaultValue: "Flows" })],
        ] as const).map(([value, Icon, label]) => {
          const active = tab === value;
          return (
            <button
              key={value}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onTabChange(value)}
              className={cn(
                "relative flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left text-[13px] font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent/55 hover:text-sidebar-foreground",
                active && "bg-[hsl(var(--accent-primary)/0.13)] text-[hsl(var(--accent-primary))]",
              )}
            >
              {active ? (
                <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-[hsl(var(--accent-primary))]" />
              ) : null}
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              <span>{label}</span>
            </button>
          );
        })}
      </nav>

      <div className="mx-4 border-t border-sidebar-border/70" />
      <LibraryList
        tab={tab}
        items={items}
        loading={loading}
        error={error}
        filters={filters}
        onFiltersChange={onFiltersChange}
        selectedId={selectedId}
        onSelect={onSelect}
      />

      {onCreate ? (
        <div className="shrink-0 border-t border-sidebar-border/70 p-3">
          <Button className="btn-primary w-full" size="sm" onClick={onCreate}>
            <Plus className="mr-1.5 h-4 w-4" aria-hidden />
            {isCommand
              ? t("library.newCommand", { defaultValue: "New command" })
              : t("library.newFlow", { defaultValue: "New flow" })}
          </Button>
        </div>
      ) : null}
    </aside>
  );
}
