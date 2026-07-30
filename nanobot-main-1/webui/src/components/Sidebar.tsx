import { useState, type ReactNode } from "react";
import {
  Archive,
  BookOpen,
  CalendarClock,
  PanelLeft,
  PanelLeftClose,
  Plus,
  Settings,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ChatList } from "@/components/ChatList";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { Button } from "@/components/ui/button";
import type {
  ChatSummary,
  SidebarViewState,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface SidebarProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  onNewChat: () => void;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onTogglePin: (key: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onToggleArchive: (key: string) => void;
  onToggleGroup: (groupId: string) => void;
  onRequestRenameProject: (projectKey: string, label: string) => void;
  onNewChatInProject: (projectPath: string, projectName: string) => void;
  onOpenSettings: () => void;
  onOpenLibrary: () => void;
  onOpenAutomations: () => void;
  onOpenSearch: () => void;
  activeUtility?: "apps" | "skills" | "automations" | "library" | null;
  onToggleArchived: () => void;
  onCollapse: () => void;
  onExpand?: () => void;
  containActionMenus?: boolean;
  collapsed?: boolean;
  pinnedKeys?: string[];
  archivedKeys?: string[];
  titleOverrides?: Record<string, string>;
  projectNameOverrides?: Record<string, string>;
  collapsedGroups?: Record<string, boolean>;
  runningChatIds?: string[];
  updatedChatIds?: string[];
  viewState?: SidebarViewState;
  showArchived?: boolean;
  archivedCount?: number;
  defaultWorkspacePath?: string | null;
  hostChromeInset?: boolean;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
}

type NavigatorWithUserAgentData = Navigator & {
  userAgentData?: { platform?: string };
};

function isApplePlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const platform = navigator.platform || "";
  const userAgentPlatform =
    (navigator as NavigatorWithUserAgentData).userAgentData?.platform || "";
  return /mac|iphone|ipad|ipod/i.test(`${platform} ${userAgentPlatform}`);
}

function newChatShortcutLabel(): string {
  return isApplePlatform() ? "⌘⇧O" : "Ctrl+Shift+O";
}

/**
 * v3 console sidebar (console-v3.html): compact identity mark,
 * full-width btn-primary 新建对话, field-input search box,
 * session list, and bottom nav rows (位置库 / 设置 / 主题切换).
 */
export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();
  const [menuPortalContainer, setMenuPortalContainer] =
    useState<HTMLElement | null>(null);
  const collapsed = Boolean(props.collapsed);
  const newChatShortcut = newChatShortcutLabel();

  const chatList = (
    <ChatList
      sessions={props.sessions}
      activeKey={props.activeKey}
      loading={props.loading}
      emptyLabel={t("chat.noSessions")}
      onSelect={props.onSelect}
      onRequestDelete={props.onRequestDelete}
      onTogglePin={props.onTogglePin}
      onRequestRename={props.onRequestRename}
      onToggleArchive={props.onToggleArchive}
      onToggleGroup={props.onToggleGroup}
      onRequestRenameProject={props.onRequestRenameProject}
      onNewChatInProject={props.onNewChatInProject}
      pinnedKeys={props.pinnedKeys}
      archivedKeys={props.archivedKeys}
      titleOverrides={props.titleOverrides}
      projectNameOverrides={props.projectNameOverrides}
      collapsedGroups={props.collapsedGroups}
      runningChatIds={props.runningChatIds}
      updatedChatIds={props.updatedChatIds}
      density={props.viewState?.density}
      showPreviews={props.viewState?.show_previews}
      showTimestamps={props.viewState?.show_timestamps}
      sort={props.viewState?.sort}
      showArchived={props.showArchived}
      defaultWorkspacePath={props.defaultWorkspacePath}
      actionMenuPortalContainer={
        props.containActionMenus ? menuPortalContainer : undefined
      }
    />
  );

  return (
    <nav
      ref={props.containActionMenus ? setMenuPortalContainer : undefined}
      aria-label={t("sidebar.navigation")}
      className={cn(
        "flex h-full w-full min-w-0 flex-col text-sidebar-foreground",
        props.hostChromeInset ? "bg-transparent" : "bg-sidebar",
        !props.hostChromeInset && "border-r border-sidebar-border",
      )}
    >
      {collapsed ? (
        /* ================= 折叠 rail 模式 ================= */
        <>
          <div className="flex h-14 w-14 shrink-0 items-center justify-center border-b border-sidebar-border">
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("thread.header.toggleSidebar")}
              title={t("thread.header.toggleSidebar")}
              onClick={props.onExpand ?? props.onCollapse}
              className="h-9 w-9 rounded-xl text-muted-foreground hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
            >
              <PanelLeft className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex w-14 flex-col items-center space-y-1.5 px-0 pb-2">
            <SidebarRailButton
              label={t("sidebar.newChat")}
              onClick={props.onNewChat}
              icon={<Plus className="h-4 w-4" />}
              shortcut={newChatShortcut}
              ariaKeyShortcuts="Meta+Shift+O Control+Shift+O"
            />
            <SidebarRailButton
              label={t("sidebar.commandLibrary")}
              onClick={props.onOpenLibrary}
              active={props.activeUtility === "library"}
              icon={<BookOpen className="h-4 w-4" />}
            />
            <SidebarRailButton
              label={t("sidebar.automations", { defaultValue: "Automations" })}
              onClick={props.onOpenAutomations}
              active={props.activeUtility === "automations"}
              icon={<CalendarClock className="h-4 w-4" />}
            />
            {props.archivedCount ? (
              <SidebarRailButton
                label={props.showArchived ? t("chat.hideArchived") : t("chat.showArchived")}
                onClick={props.onToggleArchived}
                icon={<Archive className="h-4 w-4" />}
              />
            ) : null}
          </div>
          <div className="min-h-0 flex-1" />
          <div className="flex w-14 flex-col items-center gap-1 px-0 py-2.5">
            <SidebarRailButton
              label={t("sidebar.settings")}
              onClick={props.onOpenSettings}
              icon={<Settings className="h-4 w-4" />}
            />
            <ConnectionBadge />
          </div>
        </>
      ) : (
        /* ================= 展开模式（v3 布局） ================= */
        <>
          {/* Primary action and collapse control share one deliberate toolbar. */}
          <div className="flex shrink-0 items-center gap-2 px-3 pt-3">
            <button
              type="button"
              onClick={props.onNewChat}
              aria-label={t("sidebar.newChat")}
              aria-keyshortcuts="Meta+Shift+O Control+Shift+O"
              title={`${t("sidebar.newChat")} (${newChatShortcut})`}
              className="btn-primary flex min-w-0 flex-1 items-center justify-center gap-2 px-3 py-2.5 text-sm"
            >
              <Plus className="h-4 w-4" />
              <span>{t("sidebar.newChat")}</span>
            </button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("sidebar.collapse")}
              title={t("sidebar.collapse")}
              onClick={props.onCollapse}
              className="h-10 w-10 shrink-0 rounded-xl border border-sidebar-border/75 text-muted-foreground hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
            >
              <PanelLeftClose className="h-4 w-4" />
            </Button>
          </div>

          {/* 会话列表 */}
          <div className="mt-3 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {chatList}
          </div>

          {/* 底部入口（v2：位置库 / 设置 / 主题切换） */}
          <div className="shrink-0 space-y-1 border-t border-sidebar-border p-3">
            <SidebarNavRow
              icon={<BookOpen className="h-4 w-4" />}
              label={t("sidebar.commandLibrary")}
              onClick={props.onOpenLibrary}
              active={props.activeUtility === "library"}
            />
            <SidebarNavRow
              icon={<CalendarClock className="h-4 w-4" />}
              label={t("sidebar.automations", { defaultValue: "Automations" })}
              onClick={props.onOpenAutomations}
              active={props.activeUtility === "automations"}
            />
            {props.archivedCount ? (
              <SidebarNavRow
                icon={<Archive className="h-4 w-4" />}
                label={props.showArchived ? t("chat.hideArchived") : t("chat.showArchived")}
                onClick={props.onToggleArchived}
              />
            ) : null}
            <SidebarNavRow
              icon={<Settings className="h-4 w-4" />}
              label={t("sidebar.settings")}
              onClick={props.onOpenSettings}
            />
          </div>
        </>
      )}
    </nav>
  );
}

/** Icon-only button used by the collapsed rail layout. */
function SidebarRailButton({
  label,
  icon,
  onClick,
  active = false,
  shortcut,
  ariaKeyShortcuts,
}: {
  label: string;
  icon: ReactNode;
  onClick: () => void;
  active?: boolean;
  shortcut?: string;
  ariaKeyShortcuts?: string;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      aria-label={label}
      aria-current={active ? "page" : undefined}
      aria-keyshortcuts={ariaKeyShortcuts}
      title={shortcut ? `${label} (${shortcut})` : label}
      onClick={() => onClick()}
      className={cn(
        "h-9 w-9 justify-center rounded-xl px-0 font-medium text-sidebar-foreground/85",
        "transition-colors duration-200 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground",
        active &&
          "bg-[hsl(var(--accent-primary)/0.12)] text-[hsl(var(--accent-primary))] shadow-[inset_0_0_0_1px_hsl(var(--accent-primary)/0.25)] dark:shadow-glow",
      )}
    >
      <span className="flex shrink-0 items-center justify-center" aria-hidden>
        {icon}
      </span>
    </Button>
  );
}

/** Bottom nav row — v3 console style (icon + label, rounded-lg, ghost hover). */
function SidebarNavRow({
  icon,
  label,
  onClick,
  active = false,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-current={active ? "page" : undefined}
      onClick={() => onClick()}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
        active
          ? "bg-[hsl(var(--accent-primary)/0.12)] text-[hsl(var(--accent-primary))]"
          : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
      )}
    >
      <span className="flex shrink-0 items-center justify-center" aria-hidden>
        {icon}
      </span>
      <span className="truncate">{label}</span>
    </button>
  );
}
