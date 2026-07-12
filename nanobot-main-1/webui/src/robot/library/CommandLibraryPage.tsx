import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { LibraryList } from "@/robot/library/LibraryList";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";

export function CommandLibraryPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<LibraryTab>("commands");
  const lib = useRobotLibrary(token, tab);
  const isCommand = tab === "commands";

  return (
    <div data-testid="command-library-page" className="flex h-full w-full overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col">
        <div role="tablist" className="flex gap-1 border-b border-border/70 px-3 py-2">
          <button
            type="button"
            role="tab"
            aria-selected={isCommand}
            onClick={() => setTab("commands")}
            className="rounded px-3 py-1 text-sm font-medium hover:bg-accent/50"
          >
            {t("library.tabs.commands", { defaultValue: "Commands" })}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={!isCommand}
            onClick={() => setTab("flows")}
            className="rounded px-3 py-1 text-sm font-medium hover:bg-accent/50"
          >
            {t("library.tabs.flows", { defaultValue: "Flows" })}
          </button>
        </div>
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <LibraryList
            tab={tab}
            items={lib.items}
            loading={lib.loading}
            error={lib.error}
            filters={lib.filters}
            onFiltersChange={lib.setFilters}
            selectedId={lib.selectedId}
            onSelect={lib.select}
          />
          <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
            {lib.detailError ? (
              <p className="p-4 text-sm text-destructive">{lib.detailError}</p>
            ) : null}
            {lib.detailLoading ? (
              <p className="p-4 text-sm text-muted-foreground">…</p>
            ) : null}
            {!lib.detail && !lib.detailLoading && !lib.detailError ? (
              <p className="p-4 text-sm text-muted-foreground">
                {t("library.detail.selectPrompt", {
                  defaultValue: "Select an item to view details.",
                })}
              </p>
            ) : null}
            {lib.detail && isCommand ? (
              <CommandDetail command={lib.detail as LibraryCommand} />
            ) : null}
            {lib.detail && !isCommand ? (
              <FlowDetail flow={lib.detail as LibraryFlow} />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
