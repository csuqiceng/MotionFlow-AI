import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Bot, Loader2, Moon, PanelLeft, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { RenameChatDialog } from "@/components/RenameChatDialog";
import { Sidebar } from "@/components/Sidebar";
import { SessionSearchDialog } from "@/components/SessionSearchDialog";
import { SettingsView, type SettingsSectionKey } from "@/components/settings/SettingsView";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { CommandLibraryPage, RobotSidePanel } from "@/robot";

import { useSessions } from "@/hooks/useSessions";
import { useDeferredTitleRefresh } from "@/hooks/useDeferredTitleRefresh";
import { useSidebarState } from "@/hooks/useSidebarState";
import { useSkills } from "@/hooks/useSkills";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import {
  deriveWsUrl,
  fetchBootstrap,
  fetchLoginPreflight,
  fetchLogin,
  fetchLogout,
  type LoginPreflightResponse,
} from "@/lib/bootstrap";
import { displayTitle } from "@/lib/chat-groups";
import { LoginPage, type LoginPageError } from "@/components/LoginPage";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import type {
  ChatSummary,
  RuntimeSurface,
  SessionAutomationJob,
  SettingsPayload,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { fetchSettings, fetchWorkspaces } from "@/lib/api";
import {
  createRuntimeHost,
  getHostApi,
  toRuntimeSurface,
} from "@/lib/runtime";
import { projectNameFromPath } from "@/lib/workspace";

type BootUser = {
  user_id: string;
  username: string;
  role: "operator" | "engineer";
};

type BootState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "auth";
      /** true when the bootstrap (console-connection) step failed. */
      bootstrapError?: boolean;
      /** last login-attempt error surfaced to LoginPage. */
      loginError?: LoginPageError;
      preflight?: LoginPreflightResponse;
    }
  | {
      status: "ready";
      client: NanobotClient;
      /** WebSocket (gateway) bootstrap token. */
      token: string;
      /** Slice ② user session token (WS auth first-frame). In-memory only. */
      userToken: string;
      user: BootUser;
      tokenExpiresAt: number;
      modelName: string | null;
      runtimeSurface: RuntimeSurface;
    };

const SIDEBAR_STORAGE_KEY = "nanobot-webui.sidebar";
const SESSION_UPDATES_STORAGE_KEY = "nanobot-webui.sidebar.session-updates.v1";
const LEGACY_COMPLETED_RUNS_STORAGE_KEY = "nanobot-webui.sidebar.completed-runs.v1";
const RESTART_STARTED_KEY = "nanobot-webui.restartStartedAt";
const SIDEBAR_WIDTH = 240;
const SIDEBAR_RAIL_WIDTH = 56;
const MOBILE_SIDEBAR_WIDTH = `min(${SIDEBAR_WIDTH}px, calc(100vw - 0.75rem))`;
const TOKEN_REFRESH_MARGIN_MS = 30_000;
const TOKEN_REFRESH_MIN_DELAY_MS = 5_000;
type ShellView = "chat" | "settings" | "apps" | "automations" | "skills" | "library";
export type ShellRoute = {
  view: ShellView;
  activeKey: string | null;
  settingsSection: SettingsSectionKey;
};

const SETTINGS_SECTION_KEYS: SettingsSectionKey[] = [
  "overview",
  "appearance",
  "image",
  "voice",
  "browser",
  "apps",
  "automations",
  "skills",
  "runtime",
  "advanced",
  "accounts",
];

function isSettingsSectionKey(value: string | null): value is SettingsSectionKey {
  return SETTINGS_SECTION_KEYS.includes(value as SettingsSectionKey);
}

function defaultShellRoute(): ShellRoute {
  return { view: "chat", activeKey: null, settingsSection: "overview" };
}

function shellViewForSettingsSection(section: SettingsSectionKey): ShellView {
  if (section === "apps" || section === "automations" || section === "skills") return section;
  return "settings";
}

export function readShellRoute(): ShellRoute {
  if (typeof window === "undefined") return defaultShellRoute();
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  if (!hash || hash === "/" || hash === "/new") return defaultShellRoute();

  const [path, query = ""] = hash.split("?", 2);
  const params = new URLSearchParams(query);
  const rawSettingsSection = params.get("section");
  const settingsSection = isSettingsSectionKey(rawSettingsSection)
    ? rawSettingsSection
    : "overview";
  const activeKey = params.get("chat")?.trim() || null;

  if (path === "/settings") {
    return {
      view: shellViewForSettingsSection(settingsSection),
      activeKey,
      settingsSection,
    };
  }
  if (path === "/apps") {
    return { view: "apps", activeKey, settingsSection: "apps" };
  }
  if (path === "/automations") {
    return { view: "automations", activeKey, settingsSection: "automations" };
  }
  if (path === "/skills") {
    return { view: "skills", activeKey, settingsSection: "skills" };
  }
  if (path === "/library") {
    return { view: "library", activeKey, settingsSection: "overview" };
  }
  if (path === "/operator") {
    // Operator console: same chat view, but the entry hash #/operator is
    // preserved (with ?chat=<key>) so chatting doesn't jump to #/chat.
    return { view: "chat", activeKey, settingsSection: "overview" };
  }
  if (path.startsWith("/chat/")) {
    const encoded = path.slice("/chat/".length);
    try {
      const key = decodeURIComponent(encoded).trim();
      return key
        ? { view: "chat", activeKey: key, settingsSection: "overview" }
        : defaultShellRoute();
    } catch {
      return defaultShellRoute();
    }
  }
  return defaultShellRoute();
}

export function shellRouteHash(route: ShellRoute, operator = false): string {
  if (route.view === "chat") {
    if (operator) {
      return route.activeKey
        ? `#/operator?chat=${encodeURIComponent(route.activeKey)}`
        : "#/operator";
    }
    return route.activeKey
      ? `#/chat/${encodeURIComponent(route.activeKey)}`
      : "#/new";
  }
  const params = new URLSearchParams();
  if (route.activeKey) params.set("chat", route.activeKey);
  if (route.view === "settings" && route.settingsSection !== "overview") {
    params.set("section", route.settingsSection);
  }
  const query = params.toString();
  return `#/${route.view}${query ? `?${query}` : ""}`;
}

function writeShellRoute(route: ShellRoute, replace = false, operator = false): void {
  if (typeof window === "undefined") return;
  const nextHash = shellRouteHash(route, operator);
  if (window.location.hash === nextHash) return;
  if (replace) {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}${nextHash}`,
    );
    return;
  }
  window.location.hash = nextHash;
}

function bootstrapTokenExpiresAt(expiresInSeconds: number): number {
  return Date.now() + Math.max(0, expiresInSeconds) * 1000;
}

function tokenRefreshDelayMs(expiresAt: number): number {
  const remaining = Math.max(0, expiresAt - Date.now());
  const margin = Math.min(
    TOKEN_REFRESH_MARGIN_MS,
    Math.max(1_000, remaining / 2),
  );
  return Math.max(TOKEN_REFRESH_MIN_DELAY_MS, remaining - margin);
}

function readSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

function readSessionUpdateChatIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw =
      window.localStorage.getItem(SESSION_UPDATES_STORAGE_KEY)
      ?? window.localStorage.getItem(LEGACY_COMPLETED_RUNS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string"));
  } catch {
    return new Set();
  }
}

function writeSessionUpdateChatIds(chatIds: Set<string>): void {
  try {
    window.localStorage.setItem(
      SESSION_UPDATES_STORAGE_KEY,
      JSON.stringify(Array.from(chatIds)),
    );
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

function normalizeWorkspaceScope(scope: WorkspaceScopePayload): WorkspaceScopePayload {
  const accessMode = scope.access_mode === "restricted" ? "restricted" : "full";
  return {
    ...scope,
    project_name: scope.project_name ?? projectNameFromPath(scope.project_path),
    access_mode: accessMode,
    restrict_to_workspace: accessMode === "restricted",
  };
}

function HostChrome({
  onToggleSidebar,
  sidebarOpen = true,
  rightAction,
}: {
  onToggleSidebar?: () => void;
  sidebarOpen?: boolean;
  rightAction?: ReactNode;
}) {
  const { t } = useTranslation();

  return (
    <header className="host-drag-region pointer-events-none absolute inset-x-0 top-0 z-40 hidden h-11 bg-transparent text-foreground/90 lg:block">
      {onToggleSidebar && !sidebarOpen ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar")}
          data-testid="host-sidebar-toggle"
          onClick={onToggleSidebar}
          data-sidebar-state={sidebarOpen ? "open" : "closed"}
          style={{ left: 12 }}
          className="host-no-drag pointer-events-auto absolute top-[8px] h-7 w-7 rounded-lg bg-sidebar/80 text-muted-foreground/85 shadow-none hover:bg-sidebar-accent/80 hover:text-foreground"
        >
          <PanelLeft className="h-[15px] w-[15px]" strokeWidth={1.75} />
        </Button>
      ) : null}
      {rightAction ? (
        <div className="host-no-drag pointer-events-auto absolute right-3 top-2">
          {rightAction}
        </div>
      ) : null}
    </header>
  );
}

export default function App() {
  const { t } = useTranslation();
  const [state, setState] = useState<BootState>({ status: "loading" });
  // Holds the bootstrap (ws token + url + payload) between the bootstrap step
  // and the login step. The ws connection is only opened after a successful
  // login so the auth first-frame carries a real user token. In-memory only.
  const wsBootRef = useRef<{
    wsToken: string;
    wsUrl: string;
    boot: Awaited<ReturnType<typeof fetchBootstrap>>;
  } | null>(null);

  const refreshReadyClient = useCallback(
    async (client: NanobotClient, fallbackSurface: RuntimeSurface) => {
      // Slice ②: the ws token is refreshed over localhost bootstrap with NO
      // secret (the gateway is localhost-only). The user token is unaffected.
      const boot = await fetchBootstrap();
      const url = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
      const runtimeSurface = boot.runtime_surface
        ? toRuntimeSurface(boot.runtime_surface)
        : fallbackSurface;
      const runtimeHost = createRuntimeHost(runtimeSurface, boot.runtime_capabilities);
      const tokenExpiresAt = bootstrapTokenExpiresAt(boot.expires_in);
      if (runtimeHost.socketFactory) {
        client.updateUrl(url, runtimeHost.socketFactory);
      } else {
        client.updateUrl(url);
      }
      // Keep wsBootRef in sync so a later onReauth sees the fresh ws token.
      wsBootRef.current = { wsToken: boot.token, wsUrl: url, boot };
      setState((current) =>
        current.status === "ready" && current.client === client
          ? {
              ...current,
              token: boot.token,
              tokenExpiresAt,
              modelName: boot.model_name ?? current.modelName,
              runtimeSurface,
            }
          : current,
      );
      return { token: boot.token, url };
    },
    [],
  );

  /** Pull the HTTP status code out of a thrown error message (e.g. "login
   * failed: HTTP 401"). `fetchLogin` throws a plain Error, so we parse the
   * trailing `HTTP <code>` if present; otherwise undefined. */
  function deriveLoginError(e: unknown): LoginPageError {
    const msg = (e as Error)?.message ?? "";
    const match = msg.match(/HTTP\s+(\d{3})/);
    if (match) return { status: Number(match[1]) };
    return {};
  }

  const handleBootstrap = useCallback(() => {
    let cancelled = false;
    (async () => {
      setState({ status: "loading" });
      try {
        const boot = await fetchBootstrap(); // localhost, NO secret
        if (cancelled) return;
        const wsUrl = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
        wsBootRef.current = { wsToken: boot.token, wsUrl, boot };
        let preflight: LoginPreflightResponse | undefined;
        try {
          preflight = await fetchLoginPreflight("10.168.3.21", boot.token);
        } catch {
          // Login stays available to engineers even when diagnostics fail.
        }
        setState({ status: "auth", preflight }); // show login page
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "";
        if (message.startsWith("This WebUI supports protocol version")) {
          setState({ status: "error", message });
          return;
        }
        // Console connection failed → stay on auth with the bootstrap error
        // shown (LoginPage disables submit + shows the connection message).
        setState({ status: "auth", bootstrapError: true });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogin = useCallback(
    (creds: { username: string; password: string; role: "operator" | "engineer" }) => {
      let cancelled = false;
      (async () => {
        try {
          let ws = wsBootRef.current;
          if (!ws) {
            const boot = await fetchBootstrap();
            ws = {
              wsToken: boot.token,
              wsUrl: deriveWsUrl(boot.ws_path, boot.token, boot.ws_url),
              boot,
            };
            wsBootRef.current = ws;
          }
          let res;
          try {
            res = await fetchLogin(creds, ws.wsToken);
          } catch (error) {
            if (!((error as Error)?.message ?? "").includes("gateway_token_expired")) throw error;
            const boot = await fetchBootstrap();
            ws = {
              wsToken: boot.token,
              wsUrl: deriveWsUrl(boot.ws_path, boot.token, boot.ws_url),
              boot,
            };
            wsBootRef.current = ws;
            res = await fetchLogin(creds, ws.wsToken);
          }
          if (cancelled) return;
          const { user_token: userToken, user } = res.data;
          const runtimeSurface = toRuntimeSurface(ws.boot.runtime_surface ?? "browser");
          const runtimeHost = createRuntimeHost(
            runtimeSurface,
            ws.boot.runtime_capabilities,
          );
          const client = new NanobotClient({
            url: ws.wsUrl,
            socketFactory: runtimeHost.socketFactory,
            onReauth: async () => {
              try {
                const refreshed = await refreshReadyClient(client, runtimeSurface);
                return refreshed.url;
              } catch {
                return null;
              }
            },
            onAuthFailed: () => {
              // User token rejected/expired by the WS auth gate → bounce to the
              // login page (no localStorage to clear; tokens are in-memory only).
              setState({ status: "auth" });
            },
          });
          client.setAuthToken(userToken);
          client.connect();
          setState({
            status: "ready",
            client,
            token: ws.wsToken,
            userToken,
            user,
            tokenExpiresAt: bootstrapTokenExpiresAt(ws.boot.expires_in),
            modelName: ws.boot.model_name ?? null,
            runtimeSurface,
          });
          // Route to the role's entry hash — but only when the user landed on a
          // bare root (no prior route to restore). Preserves deep links like
          // #/chat/<key> or #/settings?section=voice across a login redirect.
          // The cross-role redirect effect below enforces role/hash alignment.
          const currentHash = window.location.hash;
          const isBareRoot =
            !currentHash ||
            currentHash === "#" ||
            currentHash === "#/" ||
            currentHash === "#/new";
          if (isBareRoot) {
            window.location.hash =
              user.role === "engineer" ? "#/engineer" : "#/operator";
          } else if (
            (user.role === "operator" && currentHash.startsWith("#/engineer")) ||
            (user.role === "engineer" && currentHash.startsWith("#/operator"))
          ) {
            // Cross-role entry hash: snap to this role's entry.
            window.location.hash =
              user.role === "engineer" ? "#/engineer" : "#/operator";
          }
        } catch (e) {
          if (cancelled) return;
          setState({ status: "auth", loginError: deriveLoginError(e) });
        }
      })();
      return () => {
        cancelled = true;
      };
    },
    [refreshReadyClient],
  );

  useEffect(() => {
    if (state.status !== "ready") return;
    const client = state.client;
    const timer = window.setTimeout(async () => {
      try {
        await refreshReadyClient(client, state.runtimeSurface);
      } catch (e) {
        const msg = (e as Error).message;
        if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
          // ws-token refresh rejected → back to login.
          setState({ status: "auth" });
        }
      }
    }, tokenRefreshDelayMs(state.tokenExpiresAt));
    return () => window.clearTimeout(timer);
  }, [refreshReadyClient, state]);

  // Cross-role hash redirect: a user may only sit on their own role's hash.
  useEffect(() => {
    if (state.status !== "ready") return;
    const role = state.user.role;
    const apply = () => {
      const hash = window.location.hash;
      if (role === "operator" && hash.startsWith("#/engineer")) {
        window.location.hash = "#/operator";
      } else if (role === "engineer" && hash.startsWith("#/operator")) {
        window.location.hash = "#/engineer";
      }
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, [state]);

  useEffect(() => {
    return handleBootstrap();
  }, [handleBootstrap]);

  if (state.status === "loading") {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center gap-4 animate-in fade-in-0 duration-300">
          <div className="relative flex h-14 w-14 items-center justify-center">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-2xl bg-[hsl(var(--accent-primary)/0.25)]" />
            <span className="absolute inline-flex h-full w-full rounded-2xl border-2 border-[hsl(var(--accent-primary)/0.2)]" />
            <Loader2 className="absolute h-14 w-14 animate-spin text-[hsl(var(--accent-primary)/0.5)]" strokeWidth={1.5} />
            <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-[hsl(var(--accent-primary)/0.15)] text-[hsl(var(--accent-primary))]">
              <Bot className="h-5 w-5" strokeWidth={2} />
            </div>
          </div>
        </div>
      </div>
    );
  }
  if (state.status === "auth") {
    return (
      <LoginPage
        bootstrapOk={!state.bootstrapError}
        error={state.loginError ?? null}
        preflight={state.preflight}
        onPreflight={async (host) => {
          const ws = wsBootRef.current;
          if (!ws) throw new Error("bootstrap unavailable");
          const preflight = await fetchLoginPreflight(host, ws.wsToken);
          setState((current) => current.status === "auth" ? { ...current, preflight } : current);
          return preflight;
        }}
        onSubmit={handleLogin}
      />
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center px-4 text-center">
        <div className="flex max-w-md flex-col items-center gap-3">
          <p className="text-lg font-semibold">{t("app.error.title")}</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <p className="text-xs text-muted-foreground">
            {t("app.error.gatewayHint")}
          </p>
        </div>
      </div>
    );
  }

  const handleModelNameChange = (modelName: string | null) => {
    setState((current) =>
      current.status === "ready" ? { ...current, modelName } : current,
    );
  };

  const handleLogout = () => {
    if (state.status === "ready") {
      void fetchLogout(state.token, state.userToken).catch(() => {});
      state.client.close();
    }
    wsBootRef.current = null;
    setState({ status: "auth" }); // back to login (no localStorage to clear)
  };

  const handleNativeEngineRestart = async (): Promise<string> => {
    const hostApi = getHostApi();
    if (!hostApi?.restartEngine) {
      throw new Error("native engine restart is unavailable");
    }
    await hostApi.restartEngine();
    const refreshed = await refreshReadyClient(state.client, state.runtimeSurface);
    return refreshed.token;
  };

  return (
    <ClientProvider
      client={state.client}
      token={state.token}
      userToken={state.userToken}
      user={state.user}
      modelName={state.modelName}
    >
      <Shell
        runtimeSurface={state.runtimeSurface}
        userRole={state.user.role}
        onModelNameChange={handleModelNameChange}
        onLogout={handleLogout}
        onNativeEngineRestart={handleNativeEngineRestart}
        rightPanel={<RobotSidePanel token={state.token} userToken={state.userToken} />}
      />
    </ClientProvider>
  );
}

function Shell({
  runtimeSurface,
  userRole,
  onModelNameChange,
  onLogout,
  onNativeEngineRestart,
  rightPanel,
}: {
  runtimeSurface: RuntimeSurface;
  userRole: "operator" | "engineer";
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
  onNativeEngineRestart: () => Promise<string>;
  rightPanel?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const { client, token, userToken } = useClient();
  const { theme, toggle } = useTheme();
  const {
    sessions,
    loading,
    refresh,
    createChat,
    forkChat,
    deleteChat,
    getSessionAutomations,
  } = useSessions();
  const { state: sidebarState, update: updateSidebarState } =
    useSidebarState(sessions, !loading);
  const initialRouteRef = useRef<ShellRoute | null>(null);
  if (!initialRouteRef.current) initialRouteRef.current = readShellRoute();
  const [activeKey, setActiveKey] = useState<string | null>(
    initialRouteRef.current.activeKey,
  );
  const [view, setView] = useState<ShellView>(initialRouteRef.current.view);
  const [settingsInitialSection, setSettingsInitialSection] =
    useState<SettingsSectionKey>(initialRouteRef.current.settingsSection);
  const [hostSidebarOpen, setHostSidebarOpen] =
    useState<boolean>(readSidebarOpen);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sessionSearchOpen, setSessionSearchOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{
    key: string;
    label: string;
    automations?: SessionAutomationJob[];
  } | null>(null);
  const [pendingRename, setPendingRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const [pendingProjectRename, setPendingProjectRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const restartSawDisconnectRef = useRef(false);
  const [restartToast, setRestartToast] = useState<string | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [runningChatIds, setRunningChatIds] = useState<Set<string>>(() => new Set());
  const [updatedChatIds, setUpdatedChatIds] = useState<Set<string>>(readSessionUpdateChatIds);
  const [workspaces, setWorkspaces] = useState<WorkspacesPayload | null>(null);
  const skills = useSkills(token);
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsPayload | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [draftWorkspaceScope, setDraftWorkspaceScope] =
    useState<WorkspaceScopePayload | null>(null);
  const [workspaceOverrides, setWorkspaceOverrides] =
    useState<Record<string, WorkspaceScopePayload>>({});
  const runningChatIdsRef = useRef<Set<string>>(new Set());
  const activeChatIdRef = useRef<string | null>(null);
  const effectiveRuntimeSurface =
    settingsSnapshot?.surface ?? settingsSnapshot?.runtime_surface ?? runtimeSurface;
  const showHostChrome = effectiveRuntimeSurface === "native";
  const showMainSidebar = view !== "settings";

  // Operator console: the operator role keeps the hash on #/operator (carrying
  // the active session as ?chat=<key>) instead of rewriting it to #/chat/<key>.
  // The engineer role uses the standard #/new, #/chat/<key> routing. Both roles
  // render the same shell incl. the RobotSidePanel (rightPanel is always set).
  const isOperatorConsole = userRole === "operator";
  const navigate = useCallback(
    (route: ShellRoute, options?: { replace?: boolean }) => {
      setActiveKey(route.activeKey);
      setView(route.view);
      setSettingsInitialSection(route.settingsSection);
      writeShellRoute(route, options?.replace, isOperatorConsole);
    },
    [isOperatorConsole],
  );

  useEffect(() => {
    const applyRoute = () => {
      const route = readShellRoute();
      setActiveKey(route.activeKey);
      setView(route.view);
      setSettingsInitialSection(route.settingsSection);
      setWorkspaceError(null);
      if (route.view === "chat" && !route.activeKey) {
        setDraftWorkspaceScope(null);
      }
    };
    window.addEventListener("hashchange", applyRoute);
    return () => window.removeEventListener("hashchange", applyRoute);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) setSettingsSnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) setSettingsSnapshot(null);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_STORAGE_KEY,
        hostSidebarOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors (private mode, etc.)
    }
  }, [hostSidebarOpen]);

  useEffect(() => {
    writeSessionUpdateChatIds(updatedChatIds);
  }, [updatedChatIds]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);
  const runningChatIdList = useMemo(() => Array.from(runningChatIds), [runningChatIds]);
  const updatedChatIdList = useMemo(() => Array.from(updatedChatIds), [updatedChatIds]);
  const activeChatId = activeSession?.chatId ?? null;
  useEffect(() => {
    activeChatIdRef.current = activeChatId;
    if (!activeChatId) return;
    setUpdatedChatIds((current) => {
      if (!current.has(activeChatId)) return current;
      const next = new Set(current);
      next.delete(activeChatId);
      return next;
    });
  }, [activeChatId]);
  const activeWorkspaceScope = useMemo<WorkspaceScopePayload | null>(() => {
    if (activeChatId && workspaceOverrides[activeChatId]) {
      return workspaceOverrides[activeChatId];
    }
    if (activeSession?.workspaceScope) {
      return activeSession.workspaceScope;
    }
    return draftWorkspaceScope ?? workspaces?.default_scope ?? null;
  }, [
    activeChatId,
    activeSession?.workspaceScope,
    draftWorkspaceScope,
    workspaceOverrides,
    workspaces?.default_scope,
  ]);
  const activeChatRunning = activeChatId ? runningChatIds.has(activeChatId) : false;

  const refreshWorkspaces = useCallback(async () => {
    try {
      const payload = await fetchWorkspaces(token);
      setWorkspaces(payload);
    } catch {
      setWorkspaces(null);
    }
  }, [token]);

  useEffect(() => {
    void refreshWorkspaces();
  }, [refreshWorkspaces]);

  useEffect(() => {
    if (loading) return;
    const knownChatIds = new Set(sessions.map((session) => session.chatId));
    setUpdatedChatIds((current) => {
      const next = new Set(
        Array.from(current).filter((chatId) => knownChatIds.has(chatId)),
      );
      return next.size === current.size ? current : next;
    });
    setWorkspaceOverrides((current) => {
      const entries = Object.entries(current).filter(([chatId]) => knownChatIds.has(chatId));
      return entries.length === Object.keys(current).length ? current : Object.fromEntries(entries);
    });
  }, [loading, sessions]);

  useEffect(() => {
    if (loading || !activeKey) return;
    if (sessions.some((session) => session.key === activeKey)) return;
    const currentRoute = readShellRoute();
    navigate(
      currentRoute.view === "chat"
        ? defaultShellRoute()
        : {
            ...currentRoute,
            activeKey: null,
          },
      { replace: true },
    );
  }, [activeKey, loading, navigate, sessions]);

  useEffect(() => {
    return client.onSessionUpdate((chatId, scope, workspaceScope) => {
      if (scope === "thread") {
        setUpdatedChatIds((current) => {
          const next = new Set(current);
          if (activeChatIdRef.current === chatId) {
            next.delete(chatId);
          } else {
            next.add(chatId);
          }
          return next.size === current.size && next.has(chatId) === current.has(chatId)
            ? current
            : next;
        });
      }
      if (!workspaceScope) return;
      const next = normalizeWorkspaceScope(workspaceScope);
      setWorkspaceOverrides((current) => ({
        ...current,
        [chatId]: next,
      }));
      setDraftWorkspaceScope(next);
      setWorkspaceError(null);
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces]);

  useEffect(() => {
    return client.onError((error) => {
      if (error.kind !== "workspace_scope_rejected") return;
      setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces, t]);

  useEffect(() => {
    if (loading) return;
    const activeRunIds = sessions
      .filter((session) => typeof session.runStartedAt === "number")
      .map((session) => session.chatId);
    if (activeRunIds.length === 0) return;

    for (const chatId of activeRunIds) {
      client.attach(chatId);
    }
    setRunningChatIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const chatId of activeRunIds) {
        if (!next.has(chatId)) changed = true;
        next.add(chatId);
      }
      if (!changed) return current;
      runningChatIdsRef.current = next;
      return next;
    });
    setUpdatedChatIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const chatId of activeRunIds) {
        if (next.delete(chatId)) changed = true;
      }
      return changed ? next : current;
    });
  }, [client, loading, sessions]);

  const closeHostSidebar = useCallback(() => {
    setHostSidebarOpen(false);
  }, []);

  const openHostSidebar = useCallback(() => {
    setHostSidebarOpen(true);
  }, []);

  const toggleHostSidebar = useCallback(() => {
    setHostSidebarOpen((v) => !v);
  }, []);

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    const isNativeHost =
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches;
    if (isNativeHost) {
      setHostSidebarOpen((v) => !v);
    } else {
      setMobileSidebarOpen((v) => !v);
    }
  }, []);

  const applyWorkspaceScope = useCallback(
    (scope: WorkspaceScopePayload) => {
      const next = normalizeWorkspaceScope(scope);
      setWorkspaceError(null);
      if (activeChatId) {
        if (!activeChatRunning) {
          client.setWorkspaceScope(activeChatId, next);
        }
        return;
      }
      setDraftWorkspaceScope(next);
    },
    [activeChatId, activeChatRunning, client],
  );

  const onCreateChat = useCallback(async (workspaceScope?: WorkspaceScopePayload | null) => {
    try {
      const scope = workspaceScope ?? activeWorkspaceScope;
      const chatId = await createChat(scope);
      navigate({
        view: "chat",
        activeKey: `robot-server:${chatId}`,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      if (scope) {
        setWorkspaceOverrides((current) => ({
          ...current,
          [chatId]: normalizeWorkspaceScope(scope),
        }));
      }
      return chatId;
    } catch (e) {
      console.error("Failed to create chat", e);
      if (e instanceof Error && e.message.startsWith("workspace_scope_rejected:")) {
        setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      }
      return null;
    }
  }, [activeWorkspaceScope, createChat, navigate, t]);

  const onForkChat = useCallback(async (
    sourceChatId: string,
    beforeUserIndex: number,
  ) => {
    try {
      const sourceSession = sessions.find((session) => session.chatId === sourceChatId);
      const sourceTitle = sourceSession
        ? displayTitle(sourceSession, sidebarState.title_overrides, t("chat.newChat"))
        : t("chat.newChat");
      const chatId = await forkChat(
        sourceChatId,
        beforeUserIndex,
        t("chat.forkTitle", { title: sourceTitle }),
      );
      navigate({
        view: "chat",
        activeKey: `robot-server:${chatId}`,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      return chatId;
    } catch (e) {
      console.error("Failed to fork chat", e);
      return null;
    }
  }, [forkChat, navigate, sessions, sidebarState.title_overrides, t]);

  const onNewChat = useCallback(() => {
    navigate(defaultShellRoute());
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
    setSessionSearchOpen(false);
    setMobileSidebarOpen(false);
  }, [navigate]);

  const onNewChatInProject = useCallback(
    (projectPath: string, projectName: string) => {
      const base = workspaces?.default_scope ?? activeWorkspaceScope;
      const trimmed = projectPath.trim();
      if (!base || !trimmed) {
        onNewChat();
        return;
      }
      navigate(defaultShellRoute());
      setDraftWorkspaceScope(normalizeWorkspaceScope({
        project_path: trimmed,
        project_name: projectName || projectNameFromPath(trimmed),
        access_mode: base.access_mode,
        restrict_to_workspace: base.access_mode === "restricted",
      }));
      setWorkspaceError(null);
      setMobileSidebarOpen(false);
    },
    [activeWorkspaceScope, navigate, onNewChat, workspaces?.default_scope],
  );

  const onSelectChat = useCallback(
    (key: string) => {
      const selected = sessions.find((session) => session.key === key);
      const selectedChatId = selected?.chatId;
      if (selectedChatId) {
        setUpdatedChatIds((current) => {
          if (!current.has(selectedChatId)) return current;
          const next = new Set(current);
          next.delete(selectedChatId);
          return next;
        });
      }
      if (selected?.workspaceScope) {
        setDraftWorkspaceScope(normalizeWorkspaceScope(selected.workspaceScope));
      } else {
        setDraftWorkspaceScope(null);
      }
      setWorkspaceError(null);
      navigate({ view: "chat", activeKey: key, settingsSection: "overview" });
      setMobileSidebarOpen(false);
    },
    [navigate, sessions],
  );

  const onTogglePin = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const pinned = new Set(current.pinned_keys);
        if (pinned.has(key)) {
          pinned.delete(key);
        } else {
          pinned.add(key);
        }
        return {
          ...current,
          pinned_keys: Array.from(pinned),
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRename = useCallback((key: string, label: string) => {
    setPendingRename({ key, label });
  }, []);

  const onConfirmRename = useCallback(
    (title: string) => {
      if (!pendingRename) return;
      const key = pendingRename.key;
      setPendingRename(null);
      void updateSidebarState((current) => {
        const titleOverrides = { ...current.title_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          titleOverrides[key] = cleaned;
        } else {
          delete titleOverrides[key];
        }
        return {
          ...current,
          title_overrides: titleOverrides,
        };
      });
    },
    [pendingRename, updateSidebarState],
  );

  const onToggleGroup = useCallback(
    (groupId: string) => {
      void updateSidebarState((current) => {
        const collapsedGroups = { ...current.collapsed_groups };
        if (groupId === "workspace:chats" || groupId === "date:all") {
          if (collapsedGroups[groupId] === false) {
            delete collapsedGroups[groupId];
          } else {
            collapsedGroups[groupId] = false;
          }
          return {
            ...current,
            collapsed_groups: collapsedGroups,
          };
        }
        if (collapsedGroups[groupId]) {
          delete collapsedGroups[groupId];
        } else {
          collapsedGroups[groupId] = true;
        }
        return {
          ...current,
          collapsed_groups: collapsedGroups,
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRenameProject = useCallback((key: string, label: string) => {
    setPendingProjectRename({ key, label });
  }, []);

  const onConfirmProjectRename = useCallback(
    (title: string) => {
      if (!pendingProjectRename) return;
      const key = pendingProjectRename.key;
      setPendingProjectRename(null);
      void updateSidebarState((current) => {
        const projectNameOverrides = { ...current.project_name_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          projectNameOverrides[key] = cleaned;
        } else {
          delete projectNameOverrides[key];
        }
        return {
          ...current,
          project_name_overrides: projectNameOverrides,
        };
      });
    },
    [pendingProjectRename, updateSidebarState],
  );

  const onToggleArchive = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const archived = new Set(current.archived_keys);
        const pinned = current.pinned_keys.filter((item) => item !== key);
        if (archived.has(key)) {
          archived.delete(key);
        } else {
          archived.add(key);
        }
        return {
          ...current,
          pinned_keys: pinned,
          archived_keys: Array.from(archived),
        };
      });
      if (activeKey === key && !sidebarState.archived_keys.includes(key)) {
        const archived = new Set([...sidebarState.archived_keys, key]);
        const next = sessions.find((session) => !archived.has(session.key));
        navigate({
          view: "chat",
          activeKey: next?.key ?? null,
          settingsSection: "overview",
        });
      }
    },
    [activeKey, navigate, sessions, sidebarState.archived_keys, updateSidebarState],
  );

  const onToggleArchived = useCallback(() => {
    void updateSidebarState((current) => ({
      ...current,
      view: {
        ...current.view,
        show_archived: !current.view.show_archived,
      },
    }));
  }, [updateSidebarState]);

  const onOpenSessionSearch = useCallback(() => {
    setMobileSidebarOpen(false);
    setSessionSearchOpen(true);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const commandShiftO =
        (event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey;
      if (commandShiftO && event.key.toLowerCase() === "o") {
        event.preventDefault();
        onNewChat();
        return;
      }
      const plainCommandK =
        (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
      if (!plainCommandK) return;
      if (event.key.toLowerCase() !== "k") return;
      event.preventDefault();
      onOpenSessionSearch();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onNewChat, onOpenSessionSearch]);

  const onSelectSearchResult = useCallback(
    (key: string) => {
      setSessionSearchOpen(false);
      onSelectChat(key);
    },
    [onSelectChat],
  );

  const onOpenSettings = useCallback((section: SettingsSectionKey = "overview") => {
    setSessionSearchOpen(false);
    navigate({ view: "settings", activeKey, settingsSection: section });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onOpenModelSettings = useCallback(() => {
    onOpenSettings("models");
  }, [onOpenSettings]);

  const onOpenAutomations = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "automations", activeKey, settingsSection: "automations" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onOpenLibrary = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "library", activeKey, settingsSection: "overview" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onSettingsSectionChange = useCallback(
    (section: SettingsSectionKey) => {
      navigate({
        view: shellViewForSettingsSection(section),
        activeKey,
        settingsSection: section,
      });
    },
    [activeKey, navigate],
  );

  const onBackToChat = useCallback(() => {
    setMobileSidebarOpen(false);
    const nextKey = (() => {
      if (!activeKey) return null;
      if (sessions.some((session) => session.key === activeKey)) return activeKey;
      return sessions[0]?.key ?? null;
    })();
    navigate({
      view: "chat",
      activeKey: nextKey,
      settingsSection: "overview",
    });
  }, [activeKey, navigate, sessions]);

  const onRestart = useCallback(() => {
    const chatId = activeSession?.chatId ?? client.defaultChatId;
    if (!chatId) return;
    restartSawDisconnectRef.current = false;
    setIsRestarting(true);
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(Date.now()));
    } catch {
      // ignore storage errors
    }
    client.sendMessage(chatId, "/restart");
  }, [activeSession?.chatId, client]);

  useEffect(() => {
    return client.onRuntimeModelUpdate((modelName) => {
      onModelNameChange(modelName);
    });
  }, [client, onModelNameChange]);

  useEffect(() => {
    return client.onRunStatus((chatId, startedAt) => {
      if (startedAt != null) {
        const nextRunning = new Set(runningChatIdsRef.current);
        nextRunning.add(chatId);
        runningChatIdsRef.current = nextRunning;
        setRunningChatIds(nextRunning);
        setUpdatedChatIds((current) => {
          if (!current.has(chatId)) return current;
          const next = new Set(current);
          next.delete(chatId);
          return next;
        });
        return;
      }

      if (!runningChatIdsRef.current.has(chatId)) return;
      const nextRunning = new Set(runningChatIdsRef.current);
      nextRunning.delete(chatId);
      runningChatIdsRef.current = nextRunning;
      setRunningChatIds(nextRunning);
      setUpdatedChatIds((current) => {
        const next = new Set(current);
        if (activeChatIdRef.current === chatId) {
          next.delete(chatId);
        } else {
          next.add(chatId);
        }
        return next;
      });
    });
  }, [client]);

  useEffect(() => {
    return client.onStatus((status) => {
      const startedAt = (() => {
        try {
          return Number(window.localStorage.getItem(RESTART_STARTED_KEY) ?? "0");
        } catch {
          return 0;
        }
      })();
      if (!startedAt) return;
      if (status !== "open") {
        restartSawDisconnectRef.current = true;
        return;
      }
      const elapsedMs = Date.now() - startedAt;
      if (!restartSawDisconnectRef.current && elapsedMs < 1500) return;
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
      } catch {
        // ignore storage errors
      }
      setIsRestarting(false);
      setRestartToast(t("app.restart.completed", { seconds: (elapsedMs / 1000).toFixed(1) }));
      window.setTimeout(() => setRestartToast(null), 3_500);
    });
  }, [client, t]);

  const onTurnEnd = useDeferredTitleRefresh(activeSession, refresh);

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const key = pendingDelete.key;
    const hasAutomations = (pendingDelete.automations?.length ?? 0) > 0;
    const deletingActive = activeKey === key;
    const currentIndex = sessions.findIndex((s) => s.key === key);
    const fallbackKey = deletingActive
      ? (sessions[currentIndex + 1]?.key ?? sessions[currentIndex - 1]?.key ?? null)
      : activeKey;
    try {
      const result = await deleteChat(
        key,
        hasAutomations ? { deleteAutomations: true } : undefined,
      );
      if (result.blocked_by_automations) {
        setPendingDelete({
          ...pendingDelete,
          automations: result.automations ?? [],
        });
        return;
      }
      setPendingDelete(null);
      if (deletingActive) {
        navigate({
          view: "chat",
          activeKey: fallbackKey,
          settingsSection: "overview",
        }, { replace: true });
      }
    } catch (e) {
      console.error("Failed to delete session", e);
    }
  }, [pendingDelete, deleteChat, activeKey, navigate, sessions]);

  const onRequestDelete = useCallback(async (key: string, label: string) => {
    let automations: SessionAutomationJob[] = [];
    try {
      automations = await getSessionAutomations(key);
    } catch {
      // Delete remains protected by the backend block; prefetch only improves the first prompt.
    }
    setPendingDelete({ key, label, automations });
  }, [getSessionAutomations]);

  const headerTitle = activeSession
    ? displayTitle(activeSession, sidebarState.title_overrides, t("chat.newChat"))
    : t("app.brand");

  useEffect(() => {
    // Electron mirrors document.title into the native window chrome. Keep it
    // stable so opening a conversation or utility view never renames the app.
    document.title = t("app.documentTitle.base");
  }, [i18n.resolvedLanguage, t]);

  const sidebarProps = {
    sessions,
    activeKey,
    loading,
    onNewChat,
    onSelect: onSelectChat,
    onRequestDelete,
    onTogglePin,
    onRequestRename,
    onToggleArchive,
    onToggleGroup,
    onRequestRenameProject,
    onNewChatInProject,
    onOpenSettings,
    onOpenLibrary,
    onOpenAutomations,
    onOpenSearch: onOpenSessionSearch,
    activeUtility: view === "apps" || view === "automations" || view === "skills" || view === "library" ? view : null,
    onToggleArchived,
    pinnedKeys: sidebarState.pinned_keys,
    archivedKeys: sidebarState.archived_keys,
    titleOverrides: sidebarState.title_overrides,
    projectNameOverrides: sidebarState.project_name_overrides,
    collapsedGroups: sidebarState.collapsed_groups,
    runningChatIds: runningChatIdList,
    updatedChatIds: updatedChatIdList,
    viewState: sidebarState.view,
    showArchived: sidebarState.view.show_archived,
    archivedCount: sidebarState.archived_keys.length,
    defaultWorkspacePath: workspaces?.default_scope.project_path ?? null,
    theme,
    onToggleTheme: toggle,
  };
  const hostSidebarCollapsed = showHostChrome && !hostSidebarOpen;
  const hostSidebarFlowWidth = showHostChrome
    ? (hostSidebarOpen ? SIDEBAR_WIDTH : 0)
    : (hostSidebarOpen ? SIDEBAR_WIDTH : SIDEBAR_RAIL_WIDTH);
  const renderHostSidebarFlowContent = !showHostChrome || hostSidebarOpen;

  useEffect(() => {
    document.documentElement.classList.toggle("native-host", showHostChrome);
    return () => {
      document.documentElement.classList.remove("native-host");
    };
  }, [showHostChrome]);

  return (
    <ThemeProvider theme={theme}>
      <div
        className={cn(
          "relative h-full w-full overflow-hidden",
          showHostChrome && "host-window-shell",
        )}
      >
        {showHostChrome ? (
          <HostChrome
            onToggleSidebar={showMainSidebar ? toggleHostSidebar : undefined}
            sidebarOpen={hostSidebarOpen}
            rightAction={
              view === "chat" ? undefined : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("thread.header.toggleTheme")}
                  onClick={toggle}
                  className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
                >
                  {theme === "dark" ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </Button>
              )
            }
          />
        ) : null}
        <div
          className={cn(
            "relative flex h-full w-full overflow-hidden",
          )}
        >
          {/* Host sidebar: in normal flow, so the thread area width stays honest. */}
          {showMainSidebar ? (
            <aside
              data-testid="host-sidebar-flow"
              className={cn(
                "relative z-20 hidden shrink-0 overflow-hidden lg:block",
                "transition-[width] duration-300 ease-out",
              )}
              style={{
                width: hostSidebarFlowWidth,
              }}
            >
              {renderHostSidebarFlowContent ? (
                <div
                  className={cn(
                    "absolute inset-y-0 left-0 h-full w-full overflow-hidden",
                    showHostChrome
                      ? "host-sidebar-glass"
                      : "bg-sidebar shadow-inner-right",
                  )}
                >
                  <Sidebar
                    {...sidebarProps}
                    collapsed={!showHostChrome && !hostSidebarOpen}
                    hostChromeInset={showHostChrome}
                    onCollapse={closeHostSidebar}
                    onExpand={openHostSidebar}
                  />
                </div>
              ) : null}
            </aside>
          ) : null}

          {showMainSidebar ? (
            <Sheet
              open={mobileSidebarOpen}
              onOpenChange={(open) => setMobileSidebarOpen(open)}
            >
              <SheetContent
                side="left"
                showCloseButton={false}
                aria-describedby={undefined}
                className="p-0 lg:hidden"
                style={{ width: MOBILE_SIDEBAR_WIDTH, maxWidth: MOBILE_SIDEBAR_WIDTH }}
              >
                <SheetTitle className="sr-only">{t("sidebar.navigation")}</SheetTitle>
                <Sidebar
                  {...sidebarProps}
                  onCollapse={closeMobileSidebar}
                  containActionMenus
                />
              </SheetContent>
            </Sheet>
          ) : null}

          <SessionSearchDialog
            open={sessionSearchOpen}
            onOpenChange={setSessionSearchOpen}
            sessions={sessions}
            activeKey={activeKey}
            loading={loading}
            titleOverrides={sidebarState.title_overrides}
            onSelect={onSelectSearchResult}
          />
        <main
          className={cn(
            "relative flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-background",
            showHostChrome && hostSidebarOpen && "border-l border-border/55",
          )}
        >
            {view === "chat" ? (
              <div className="absolute inset-0 flex flex-col">
              <ThreadShell
                session={activeSession}
                title={headerTitle}
                onToggleSidebar={toggleSidebar}
                onNewChat={onNewChat}
                onCreateChat={onCreateChat}
                onForkChat={onForkChat}
                onTurnEnd={onTurnEnd}
                theme={theme}
                onToggleTheme={toggle}
                hideSidebarToggleForHostChrome
                hostChromeTitleInset={hostSidebarCollapsed}
                hideHeader={false}
                workspaceScope={activeWorkspaceScope}
                workspaceDefaultScope={workspaces?.default_scope ?? null}
                workspaceControls={workspaces?.controls ?? null}
                workspaceScopeDisabled={activeChatRunning}
                workspaceError={workspaceError}
                onWorkspaceScopeChange={applyWorkspaceScope}
                settingsSnapshot={settingsSnapshot}
                onOpenModelSettings={onOpenModelSettings}
                skills={skills}
              />
              </div>
            ) : null}
            {view !== "chat" && view !== "library" && (
              <div className="absolute inset-0 flex flex-col">
                <SettingsView
                  theme={theme}
                  initialSection={settingsInitialSection}
                  initialSettings={settingsSnapshot}
                  showSidebar={view === "settings"}
                  onToggleTheme={toggle}
                  onBackToChat={onBackToChat}
                  onModelNameChange={onModelNameChange}
                  onSettingsChange={setSettingsSnapshot}
                  skills={skills}
                  onSectionChange={onSettingsSectionChange}
                  onLogout={onLogout}
                  onRestart={onRestart}
                  onNativeEngineRestart={onNativeEngineRestart}
                  isRestarting={isRestarting}
                />
              </div>
            )}
            {view === "library" && (
              <div className="absolute inset-0 flex flex-col">
                <CommandLibraryPage token={token} role={userRole} userToken={userToken} />
              </div>
            )}
          </main>
          {view !== "library" && view !== "automations" && view !== "settings" && rightPanel}
        </div>

        <DeleteConfirm
          open={!!pendingDelete}
          title={pendingDelete?.label ?? ""}
          automations={pendingDelete?.automations}
          onCancel={() => setPendingDelete(null)}
          onConfirm={onConfirmDelete}
        />
        <RenameChatDialog
          open={!!pendingRename}
          title={pendingRename?.label ?? ""}
          onCancel={() => setPendingRename(null)}
          onConfirm={onConfirmRename}
        />
        <RenameChatDialog
          open={!!pendingProjectRename}
          title={pendingProjectRename?.label ?? ""}
          dialogTitle={t("chat.renameProjectTitle")}
          description={t("chat.renameProjectDescription")}
          placeholder={t("chat.renameProjectPlaceholder")}
          onCancel={() => setPendingProjectRename(null)}
          onConfirm={onConfirmProjectRename}
        />
        {restartToast ? (
          <div
            role="status"
            className="fixed left-1/2 top-[calc(0.75rem+env(safe-area-inset-top))] z-50 max-w-[calc(100vw-1rem)] -translate-x-1/2 rounded-full border border-border/70 bg-popover px-4 py-2 text-sm font-medium text-popover-foreground shadow-lg"
          >
            {restartToast}
          </div>
        ) : null}
      </div>
    </ThemeProvider>
  );
}
