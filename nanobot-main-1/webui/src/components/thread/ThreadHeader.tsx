import { Menu, MessageSquare, Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ThreadHeaderProps {
  title: string;
  onToggleSidebar: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  hideSidebarToggleForHostChrome?: boolean;
  hostChromeTitleInset?: boolean;
  hideThemeButton?: boolean;
  minimal?: boolean;
  /** true while the active session is streaming a run (v3 运行中 pill). */
  running?: boolean;
  promptNavigatorAction?: ReactNode;
  sessionInfoAction?: ReactNode;
}

/**
 * v3 console header (console-v3.html): h-12 bar with a message-square accent
 * icon, session title, optional 运行中 status pill (run-pulse), and ghost
 * icon actions on the right.
 */
export function ThreadHeader({
  title,
  onToggleSidebar,
  theme,
  onToggleTheme,
  hideSidebarToggleForHostChrome = false,
  hostChromeTitleInset = false,
  hideThemeButton = false,
  minimal = false,
  running = false,
  promptNavigatorAction,
  sessionInfoAction,
}: ThreadHeaderProps) {
  const { t } = useTranslation();

  return (
    <header
      className={cn(
        "relative z-10 flex h-12 shrink-0 items-center gap-2 border-b border-border px-5",
        !minimal && hostChromeTitleInset && "lg:pl-[128px]",
      )}
    >
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("thread.header.toggleSidebar")}
        onClick={onToggleSidebar}
        className={cn(
          "h-8 w-8 rounded-lg text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors",
          hideSidebarToggleForHostChrome && "lg:hidden",
        )}
      >
        <Menu className="h-4 w-4" />
      </Button>

      {!minimal ? (
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <MessageSquare
            className="h-4 w-4 shrink-0 text-[hsl(var(--accent-primary))]"
            aria-hidden
          />
          <h2 className="truncate text-sm font-medium text-foreground">
            {title}
          </h2>
          {running ? (
            <span className="status-pill status-pill--ok hidden sm:inline-flex">
              <span className="run-pulse">
                <span className="run-pulse__dot" />
                <span className="run-pulse__ring" />
              </span>
              {t("chat.activity.running")}
            </span>
          ) : null}
        </div>
      ) : (
        <div className="min-w-0 flex-1" />
      )}

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {sessionInfoAction}
        {promptNavigatorAction}
        {!hideThemeButton ? (
          <ThemeButton
            theme={theme}
            onToggleTheme={onToggleTheme}
            label={t("thread.header.toggleTheme")}
          />
        ) : null}
      </div>
    </header>
  );
}

function ThemeButton({
  theme,
  onToggleTheme,
  label,
  className,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  label: string;
  className?: string;
}) {
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={label}
      onClick={onToggleTheme}
      className={cn(
        "host-no-drag h-8 w-8 rounded-lg text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors",
        className,
      )}
    >
      {theme === "dark" ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </Button>
  );
}
