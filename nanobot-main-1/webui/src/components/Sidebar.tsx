import { useState, type ReactNode } from "react";
import {
  Archive,
  BookOpen,
  Bot,
  CalendarClock,
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
 * v3 console sidebar (console-v3.html): brand header with gradient logo +
 * platform title, full-width btn-primary 新建对话, field-input search box,
 * session list, and bottom nav rows (命令库 / 设置 / 主题切换).
 */
export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();
  const [menuPortalContainer, setMenuPortalContainer] =
    useState<HTMLElement | null>(null);
  const collapsed = Boolean(props.collapsed);
  const toggleLabel = t("thread.header.toggleSidebar");
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
      {/* ================= 顶部品牌区（v2） ================= */}
      <div
        className={cn(
          "flex h-14 shrink-0 items-center gap-2.5 border-b border-sidebar-border px-4",
          props.hostChromeInset && "h-auto pb-2.5 pt-[2.85rem]",
          collapsed && "h-auto justify-center border-b-0 px-2 pb-2 pt-3",
          collapsed && props.hostChromeInset && "pt-[2.85rem]",
        )}
      >
        <button
          type="button"
          aria-label={collapsed ? toggleLabel : undefined}
          aria-hidden={collapsed ? undefined : true}
          title={collapsed ? toggleLabel : undefined}
          onClick={collapsed ? props.onExpand : undefined}
          tabIndex={collapsed ? 0 : -1}
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-xl transition-colors",
            collapsed ? "hover:bg-sidebar-accent/75" : "pointer-events-none",
          )}
        >
          <div className="flex h-9 w-9 select-none items-center justify-center rounded-xl bg-gradient-to-br from-[hsl(var(--accent-primary))] to-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] shadow-[0_4px_16px_-2px_hsl(var(--accent-primary)/0.45)]">
            <Bot className="h-5 w-5" strokeWidth={2} />
          </div>
        </button>
        {!collapsed ? (
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-sidebar-foreground">
              {t("app.brand")}
            </h1>
            <p className="data-mono truncate text-[11px] text-muted-foreground">
              机械手控制系统 · v2
            </p>
          </div>
        ) : null}
        {!collapsed && !props.hostChromeInset ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("sidebar.collapse")}
            onClick={props.onCollapse}
            className="h-8 w-8 rounded-lg text-muted-foreground hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
          >
            <PanelLeftClose className="h-4 w-4" />
          </Button>
        ) : null}
      </div>

      {collapsed ? (
        /* ================= 折叠 rail 模式 ================= */
        <>
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
          {/* 新建对话 — btn-primary 全宽 */}
          <div className="px-4 pt-4">
            <button
              type="button"
              onClick={props.onNewChat}
              aria-label={t("sidebar.newChat")}
              aria-keyshortcuts="Meta+Shift+O Control+Shift+O"
              title={`${t("sidebar.newChat")} (${newChatShortcut})`}
              className="btn-primary flex w-full items-center justify-center gap-2 px-3 py-2.5 text-sm"
            >
              <Plus className="h-4 w-4" />
              <span>{t("sidebar.newChat")}</span>
            </button>
          </div>

          {/* 会话列表 */}
          <div className="mt-3 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {chatList}
          </div>

          {/* 底部入口（v2：命令库 / 设置 / 主题切换） */}
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
