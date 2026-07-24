import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { ChatSummary, SessionAutomationJob } from "@/lib/types";

const connectSpy = vi.fn();
const refreshSpy = vi.fn();
const createChatSpy = vi.fn().mockResolvedValue("chat-1");
const deleteChatSpy = vi.fn();
const getSessionAutomationsSpy = vi.fn<(key: string) => Promise<SessionAutomationJob[]>>();
const toggleThemeSpy = vi.fn();
const updateUrlSpy = vi.fn();
const attachSpy = vi.fn();
const runStatusHandlers = new Set<(chatId: string, startedAt: number | null) => void>();
const sessionUpdateHandlers = new Set<(chatId: string, scope?: string) => void>();
let mockSessions: ChatSummary[] = [];
const HERO_GREETING_PATTERN =
  /What should we work on\?|Where should we start\?|What are we building today\?|What should we tackle together\?/;

function setNavigatorPlatform(platform: string): void {
  Object.defineProperty(window.navigator, "platform", {
    configurable: true,
    value: platform,
  });
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function mockFetchRoutes(routes: Record<string, unknown>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const body = routes[String(input)];
      return body === undefined
        ? ({ ok: false, status: 404, json: async () => ({}) } as Response)
        : jsonResponse(body);
    }),
  );
}

function baseSettingsPayload() {
  return {
    agent: {
      model: "openai/gpt-4o",
      provider: "auto",
      resolved_provider: "openai",
      has_api_key: true,
      model_preset: "default",
      max_tokens: 8192,
      context_window_tokens: 65536,
      temperature: 0.1,
      reasoning_effort: null,
      timezone: "UTC",
      bot_name: "nanobot",
      bot_icon: "nb",
      tool_hint_max_length: 40,
    },
    model_presets: [{
      name: "default",
      label: "Default",
      active: true,
      is_default: true,
      model: "openai/gpt-4o",
      provider: "auto",
      max_tokens: 8192,
      context_window_tokens: 65536,
      temperature: 0.1,
      reasoning_effort: null,
    }],
    providers: [],
    web_search: {
      provider: "duckduckgo",
      api_key_hint: null,
      base_url: null,
      max_results: 5,
      timeout: 30,
      providers: [{ name: "duckduckgo", label: "DuckDuckGo", credential: "none" }],
    },
    web: {
      enable: true,
      proxy: null,
      user_agent: null,
      search: { max_results: 5, timeout: 30 },
      fetch: { use_jina_reader: true },
    },
    image_generation: {
      enabled: false,
      provider: "openrouter",
      provider_configured: false,
      model: "openai/gpt-5.4-image-2",
      default_aspect_ratio: "1:1",
      default_image_size: "1K",
      max_images_per_turn: 4,
      save_dir: "generated",
      providers: [],
    },
    runtime: {
      config_path: "/tmp/config.json",
      workspace_path: "/tmp/workspace",
      gateway_host: "127.0.0.1",
      gateway_port: 18790,
      heartbeat: {
        enabled: true,
        interval_s: 1800,
        keep_recent_messages: 8,
      },
      dream: {
        schedule: "every 2h",
        max_batch_size: 20,
        max_iterations: 15,
        annotate_line_ages: true,
      },
      unified_session: false,
    },
    advanced: {
      restrict_to_workspace: false,
      webui_allow_local_service_access: true,
      webui_default_access_mode: "default",
      private_service_protection_enabled: true,
      ssrf_whitelist_count: 0,
      mcp_server_count: 0,
      exec_enabled: true,
      exec_sandbox: null,
      exec_path_prepend_set: false,
      exec_path_append_set: false,
    },
    requires_restart: false,
  };
}

vi.mock("@/hooks/useSessions", async (importOriginal) => {
  const React = await import("react");
  const actual = await importOriginal<typeof import("@/hooks/useSessions")>();
  return {
    ...actual,
    useSessions: () => {
      const [sessions, setSessions] = React.useState(mockSessions);
      return {
        sessions,
        loading: false,
        error: null,
        refresh: refreshSpy,
        createChat: createChatSpy,
        forkChat: async () => "fork-chat",
        getSessionAutomations: getSessionAutomationsSpy,
        deleteChat: async (key: string, options?: { deleteAutomations?: boolean }) => {
          if (options === undefined) await deleteChatSpy(key);
          else await deleteChatSpy(key, options);
          setSessions((prev: ChatSummary[]) => prev.filter((s) => s.key !== key));
          return { deleted: true };
        },
      };
    },
  };
});

vi.mock("@/hooks/useTheme", async () => {
  const React = await import("react");
  return {
    ThemeProvider: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
    useTheme: () => ({
      theme: "light" as const,
      toggle: toggleThemeSpy,
    }),
    useThemeValue: () => "light" as const,
  };
});

vi.mock("@/lib/bootstrap", () => ({
  fetchBootstrap: vi.fn().mockResolvedValue({
    token: "tok",
    ws_path: "/",
    expires_in: 300,
  }),
  deriveWsUrl: vi.fn(() => "ws://test"),
  // Slice ②: secret helpers removed from bootstrap; login/logout added.
  fetchLogin: vi.fn(),
  fetchLogout: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/nanobot-client", () => {
  class MockClient {
    status = "idle" as const;
    defaultChatId: string | null = null;
    connect = connectSpy;
    onStatus = () => () => {};
    onRuntimeModelUpdate = () => () => {};
    onError = () => () => {};
    onChat = () => () => {};
    onSessionUpdate = (handler: (chatId: string, scope?: string) => void) => {
      sessionUpdateHandlers.add(handler);
      return () => sessionUpdateHandlers.delete(handler);
    };
    onRunStatus = (handler: (chatId: string, startedAt: number | null) => void) => {
      runStatusHandlers.add(handler);
      return () => runStatusHandlers.delete(handler);
    };
    getRunStartedAt = () => null;
    getGoalState = () => undefined;
    sendMessage = vi.fn();
    newChat = vi.fn();
    attach = attachSpy;
    close = vi.fn();
    updateUrl = updateUrlSpy;
    // Slice ②: auth first-frame token setter (no-op in tests).
    setAuthToken = vi.fn();
  }

  return { NanobotClient: MockClient };
});

import { deriveWsUrl, fetchBootstrap, fetchLogin } from "@/lib/bootstrap";
import App from "@/App";

/** Default successful login response (engineer, matches loginViaForm default). */
function loginResponse(role: "operator" | "engineer" = "engineer") {
  return {
    ok: true,
    data: {
      user_token: "user-tok",
      expires_in: 3600,
      user: {
        user_id: role === "engineer" ? "eng-1" : "op-1",
        username: role === "engineer" ? "engineer" : "operator",
        role,
      },
    },
  };
}

/** Drive the LoginPage form to submit credentials and reach the ready shell.
 * Defaults to the engineer role so the standard #/new, #/chat, #/settings hash
 * routing applies (operator role uses #/operator routing). Locale-independent:
 * locates the form by aria-label, fills its two inputs, and submits. Also
 * stages the matching fetchLogin response so the role drives downstream
 * routing. */
async function loginViaForm(role: "operator" | "engineer" = "engineer"): Promise<void> {
  vi.mocked(fetchLogin).mockResolvedValueOnce(loginResponse(role));
  const form = await screen.findByRole("form");
  const usernameInput = form.querySelector('input[autocomplete="username"]') as HTMLElement;
  const passwordInput = form.querySelector('input[type="password"]') as HTMLElement;
  fireEvent.change(usernameInput, { target: { value: role } });
  fireEvent.change(passwordInput, { target: { value: "pass" } });
  fireEvent.click(form.querySelector('button[type="submit"]') as HTMLElement);
  await waitFor(() => expect(connectSpy).toHaveBeenCalled());
}

describe("App layout", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    mockSessions = [];
    connectSpy.mockClear();
    updateUrlSpy.mockClear();
    refreshSpy.mockReset();
    createChatSpy.mockClear();
    deleteChatSpy.mockReset();
    getSessionAutomationsSpy.mockReset().mockResolvedValue([]);
    toggleThemeSpy.mockReset();
    attachSpy.mockReset();
    runStatusHandlers.clear();
    sessionUpdateHandlers.clear();
    window.history.replaceState(null, "", "/");
    setNavigatorPlatform("Linux x86_64");
    localStorage.removeItem("nanobot-webui.sidebar");
    localStorage.removeItem("nanobot-webui.sidebar.completed-runs.v1");
    localStorage.removeItem("nanobot-webui.sidebar.session-updates.v1");
    vi.mocked(fetchBootstrap).mockReset().mockResolvedValue({
      token: "tok",
      ws_path: "/",
      expires_in: 300,
    });
    vi.mocked(deriveWsUrl).mockReset().mockReturnValue("ws://test");
    vi.mocked(fetchLogin).mockReset().mockResolvedValue(loginResponse());
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("auth state renders LoginPage with operator/engineer tabs (not legacy secret field)", async () => {
    render(<App />);

    // Bootstrap succeeds → auth (login) state. LoginPage shows role tabs.
    expect(await screen.findByRole("tab", { name: "Operator" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Engineer" })).toBeInTheDocument();
    // Legacy single-secret form is gone: no "Connect" button, no password-only form.
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
    // Username field is present (the new form has username + password).
    expect(screen.getByPlaceholderText("Username")).toBeInTheDocument();
    expect(connectSpy).not.toHaveBeenCalled();
  });

  it("refreshes an expired bootstrap token and retries login once", async () => {
    vi.mocked(fetchBootstrap)
      .mockResolvedValueOnce({ token: "expired-token", ws_path: "/", expires_in: 300 })
      .mockResolvedValueOnce({ token: "fresh-token", ws_path: "/", expires_in: 300 });
    vi.mocked(fetchLogin)
      .mockRejectedValueOnce(new Error("login failed: gateway_token_expired"))
      .mockResolvedValueOnce(loginResponse("engineer"));

    render(<App />);

    const form = await screen.findByRole("form");
    fireEvent.click(screen.getByRole("tab", { name: "Engineer" }));
    fireEvent.change(form.querySelector('input[autocomplete="username"]') as HTMLElement, {
      target: { value: "admin" },
    });
    fireEvent.change(form.querySelector('input[type="password"]') as HTMLElement, {
      target: { value: "0000" },
    });
    fireEvent.click(form.querySelector('button[type="submit"]') as HTMLElement);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    expect(fetchLogin).toHaveBeenCalledTimes(2);
    expect(fetchLogin).toHaveBeenLastCalledWith(
      { username: "admin", password: "0000", role: "engineer" },
      "fresh-token",
    );
  });

  it("does not retry a rejected username or password", async () => {
    vi.mocked(fetchLogin).mockRejectedValueOnce(new Error("login failed: invalid_credentials (HTTP 401)"));

    render(<App />);

    const form = await screen.findByRole("form");
    fireEvent.click(screen.getByRole("tab", { name: "Engineer" }));
    fireEvent.change(form.querySelector('input[autocomplete="username"]') as HTMLElement, {
      target: { value: "admin" },
    });
    fireEvent.change(form.querySelector('input[type="password"]') as HTMLElement, {
      target: { value: "wrong" },
    });
    fireEvent.click(form.querySelector('button[type="submit"]') as HTMLElement);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(fetchLogin).toHaveBeenCalledTimes(1);
    expect(fetchBootstrap).toHaveBeenCalledTimes(1);
  });

  it("shows a bootstrap connection error when the console cannot be reached", async () => {
    vi.mocked(fetchBootstrap).mockRejectedValue(
      new Error("bootstrap failed: HTTP 500"),
    );

    render(<App />);

    expect(await screen.findByText("Cannot establish a connection to the console.")).toBeInTheDocument();
    expect(connectSpy).not.toHaveBeenCalled();
  });

  it("engineer role renders the same shell incl RobotSidePanel", async () => {
    vi.mocked(fetchLogin).mockResolvedValueOnce(loginResponse("engineer"));
    mockFetchRoutes({
      "/api/robot/status": {
        ok: true,
        data: { robot_state: { mode: "idle" }, execution_mode: "dry_run_only" },
      },
    });

    render(<App />);
    await loginViaForm("engineer");

    // Engineer lands on #/engineer and gets the same shell + RobotSidePanel.
    await waitFor(() => expect(window.location.hash).toBe("#/engineer"));
    expect(await screen.findByText("末端位姿")).toBeInTheDocument();
  });

  it("operator hitting #/engineer redirects to #/operator", async () => {
    render(<App />);
    await loginViaForm("operator");

    // Operator lands on #/operator initially.
    await waitFor(() => expect(window.location.hash).toBe("#/operator"));
    // Manually navigate into the engineer hash.
    window.history.replaceState(null, "", "/#/engineer");
    fireEvent(window, new HashChangeEvent("hashchange"));
    await waitFor(() => expect(window.location.hash).toBe("#/operator"));
  });

  it("login success keeps tokens out of localStorage", async () => {
    render(<App />);
    await loginViaForm("operator");

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    // No secrets or tokens are persisted to localStorage.
    const stored = Object.keys(localStorage);
    expect(stored.some((k) => /token|secret|user_token|ws_token/i.test(k))).toBe(false);
  });

  it("keeps sidebar layout out of the main thread width contract", async () => {
    const { container } = render(<App />);

    await loginViaForm();

    const main = container.querySelector("main");
    expect(main).toBeInTheDocument();
    expect(main).not.toHaveAttribute("style");

    const asideClassNames = Array.from(container.querySelectorAll("aside")).map(
      (el) => el.className,
    );
    expect(asideClassNames.some((cls) => cls.includes("lg:block"))).toBe(true);
  });

  // Replaces the stale "places Automations after Skills" test (A2 removed the
  // Apps/Skills sidebar buttons). Verifies the post-login shell exposes the
  // command library entry in the sidebar.
  it("renders the command library entry in the sidebar after login", async () => {
    render(<App />);

    await loginViaForm("operator");
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).getByRole("button", { name: "Commands" })).toBeInTheDocument();
    // Apps/Skills main-sidebar buttons remain removed (A2).
    expect(within(sidebar).queryByRole("button", { name: "Apps" })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: "Skills" })).not.toBeInTheDocument();
  });

  // Replaces the stale "opens Skills from the main sidebar" skip (A2 removed
  // the main-sidebar Skills button). Verifies the post-login engineer shell
  // reaches the Settings surface (where Skills/Apps configuration now lives).
  it("engineer login reaches the Settings surface from the sidebar", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });

    render(<App />);

    await loginViaForm("engineer");
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Settings sections" })).toBeInTheDocument();
  });

  it("opens Automations from the main sidebar", async () => {
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": {
        jobs: [
          {
            id: "job-1",
            name: "Daily repo check",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "every", every_ms: 86_400_000 },
            payload: {
              message: "Check the repo status",
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0),
              last_status: "ok",
              pending: false,
              run_history: [],
            },
            origin: {
              session_key: "websocket:chat-a",
              channel: "websocket",
              chat_id: "chat-a",
              title: "Release prep",
              preview: "Check release blockers",
            },
          },
          {
            id: "external-quiz",
            name: "WeChat quiz",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "cron", expr: "30 9-23 * * *", tz: "Asia/Shanghai" },
            payload: {
              message: "Send a quiz",
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 17, 11, 30, 0),
              last_status: "ok",
              pending: false,
              run_history: [],
            },
            origin: {
              channel: "weixin",
              title: "",
              preview: "",
            },
          },
          {
            id: "heartbeat",
            name: "heartbeat",
            enabled: true,
            protected: true,
            schedule: { kind: "every", every_ms: 60_000 },
            payload: { message: "", kind: "system_event" },
            state: { next_run_at_ms: null, pending: false, run_history: [] },
            origin: null,
          },
        ],
      },
    });

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const automationsButton = within(sidebar).getByRole("button", {
      name: "Automations",
    });

    fireEvent.click(automationsButton);

    const heading = await screen.findByRole("heading", { name: "Automations" });
    expect(heading).toBeInTheDocument();
    const automationsMain = heading.closest("main");
    expect(automationsMain).not.toBeNull();
    expect(within(automationsMain as HTMLElement).queryByText("Settings")).not.toBeInTheDocument();
    expect(screen.getAllByText("Daily repo check").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Check the repo status").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Release prep").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("WeChat quiz")).toBeInTheDocument();
    expect(screen.getByText("WeChat")).toBeInTheDocument();
    expect(screen.queryByText("weixin:wx-chat")).not.toBeInTheDocument();
    expect(screen.queryByText("memory with dream state")).not.toBeInTheDocument();
    expect(screen.getByText("heartbeat")).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Automations" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(document.title).toBe("Automations · Arm Platform");

    const searchInput = within(automationsMain as HTMLElement).getByPlaceholderText(
      "Search task, message, linked chat, or schedule",
    );
    fireEvent.change(searchInput, { target: { value: "WeChat" } });
    await waitFor(() => expect(screen.queryByText("Daily repo check")).not.toBeInTheDocument());
    expect(screen.getAllByText("WeChat quiz").length).toBeGreaterThanOrEqual(1);

    fireEvent.change(searchInput, { target: { value: "09-23" } });
    await waitFor(() => expect(screen.queryByText("Daily repo check")).not.toBeInTheDocument());
    expect(screen.getAllByText("WeChat quiz").length).toBeGreaterThanOrEqual(1);
  });

  it("edits a past one-time automation without resubmitting its old schedule", async () => {
    const pastOneShot = {
      id: "past-one-shot",
      name: "Past one-shot",
      enabled: true,
      protected: false,
      delete_after_run: true,
      schedule: { kind: "at", at_ms: 1 },
      payload: {
        message: "Old one-shot message",
        kind: "agent_turn",
      },
      state: {
        next_run_at_ms: null,
        last_status: "ok",
        pending: false,
        run_history: [],
      },
      origin: {
        session_key: "websocket:chat-a",
        channel: "websocket",
        chat_id: "chat-a",
        title: "Release prep",
        preview: "Check release blockers",
      },
    };
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": { jobs: [pastOneShot] },
      "/api/webui/automations/update?id=past-one-shot": {
        jobs: [
          {
            ...pastOneShot,
            payload: { ...pastOneShot.payload, message: "Updated one-shot message" },
          },
        ],
      },
    });

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Automations" }));

    expect((await screen.findAllByText("Past one-shot")).length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.queryByText("Run time must be in the future.")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Update the prompt and schedule. The linked chat stays unchanged."),
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Old one-shot message")).toHaveClass(
      "min-h-[160px]",
      "resize-none",
    );

    fireEvent.change(screen.getByDisplayValue("Old one-shot message"), {
      target: { value: "Updated one-shot message" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/webui/automations/update?id=past-one-shot",
        expect.any(Object),
      );
    });
    const updateCall = vi.mocked(fetch).mock.calls.find(
      ([url]) => String(url) === "/api/webui/automations/update?id=past-one-shot",
    );
    expect(updateCall).toBeTruthy();
    const headers = updateCall?.[1]?.headers as Record<string, string>;
    expect(JSON.parse(decodeURIComponent(headers["X-Nanobot-Automation-Values"]))).toEqual({
      name: "Past one-shot",
      message: "Updated one-shot message",
    });
  });

  it("keeps long automation details expandable without nested scrolling", async () => {
    const longMessage = [
      "Review the release plan and prepare a concise status update for the channel.",
      "Include blockers, owners, follow-up dates, and any risky assumptions that changed since yesterday.",
      "Keep the output actionable and avoid repeating context that the team already confirmed in the thread.",
      "If a dependency looks stale, call it out explicitly and ask for a fresh owner update.",
      "This message is intentionally long enough to require progressive disclosure in the automation details panel.",
      "The full content should remain available without forcing the user into a small nested scroll area.",
    ].join("\n");
    const history = [
      { run_at_ms: Date.UTC(2026, 3, 12, 10, 0, 0), status: "error", duration_ms: 900, error: "oldest failure" },
      { run_at_ms: Date.UTC(2026, 3, 13, 10, 0, 0), status: "error", duration_ms: 800, error: "second oldest failure" },
      { run_at_ms: Date.UTC(2026, 3, 14, 10, 0, 0), status: "ok", duration_ms: 700 },
      { run_at_ms: Date.UTC(2026, 3, 15, 10, 0, 0), status: "ok", duration_ms: 600 },
      { run_at_ms: Date.UTC(2026, 3, 16, 10, 0, 0), status: "ok", duration_ms: 500 },
      { run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0), status: "ok", duration_ms: 400 },
    ];
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": {
        jobs: [
          {
            id: "long-details",
            name: "Long detail automation",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "every", every_ms: 3_600_000 },
            payload: {
              message: longMessage,
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 18, 10, 0, 0),
              last_status: "ok",
              pending: false,
              run_history: history,
            },
            origin: {
              session_key: "websocket:chat-a",
              channel: "websocket",
              chat_id: "chat-a",
              title: "Release prep",
              preview: "Check release blockers",
            },
          },
        ],
      },
    });

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Automations" }));

    const detailHeading = await screen.findByRole("heading", { name: "Long detail automation" });
    const detailPanel = detailHeading.closest("article") as HTMLElement;
    expect(detailPanel).not.toBeNull();
    const message = Array.from(detailPanel.querySelectorAll("section div")).find(
      (node) => node.textContent === longMessage,
    ) as HTMLElement | undefined;
    expect(message).toBeTruthy();
    expect(message!).toHaveClass("line-clamp-6");

    fireEvent.click(within(detailPanel).getByRole("button", { name: "Show full message" }));
    expect(within(detailPanel).getByRole("button", { name: "Show less" })).toBeInTheDocument();
    expect(message!).not.toHaveClass("line-clamp-6");

    expect(within(detailPanel).queryByText("Recent health")).not.toBeInTheDocument();
    expect(within(detailPanel).queryByRole("button", { name: /Run history/ })).not.toBeInTheDocument();
    expect(within(detailPanel).queryByText(/oldest failure/)).not.toBeInTheDocument();
    expect(within(detailPanel).queryByText("No error recorded")).not.toBeInTheDocument();
  });

  it("localizes the Automations surface", async () => {
    await i18n.changeLanguage("zh-CN");
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": {
        jobs: [
          {
            id: "job-zh",
            name: "每日检查",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "every", every_ms: 86_400_000 },
            payload: {
              message: "检查仓库状态",
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0),
              last_run_at_ms: Date.UTC(2026, 3, 16, 10, 0, 0),
              last_status: "ok",
              pending: false,
              run_history: [
                {
                  run_at_ms: Date.UTC(2026, 3, 16, 10, 0, 0),
                  status: "ok",
                  duration_ms: 500,
                },
              ],
            },
            origin: {
              session_key: "websocket:chat-a",
              channel: "websocket",
              chat_id: "chat-a",
              title: "发布准备",
              preview: "检查发布阻塞项",
            },
          },
        ],
      },
    });

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "侧边栏导航" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "自动任务" }));

    const heading = await screen.findByRole("heading", { name: "自动任务" });
    expect(heading).toBeInTheDocument();
    const automationsMain = heading.closest("main");
    expect(automationsMain).not.toBeNull();
    expect(within(automationsMain as HTMLElement).queryByText("设置")).not.toBeInTheDocument();
    expect(screen.getByText("任务队列")).toBeInTheDocument();
    expect(screen.getAllByText("每日检查").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("检查仓库状态").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("每 1天")).toBeInTheDocument();
    expect(screen.queryByText("最近健康状态")).not.toBeInTheDocument();
    expect(screen.queryByText("近期无问题")).not.toBeInTheDocument();
    expect(screen.queryByText("Workspace automations")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新" })).not.toBeInTheDocument();
    expect(document.title).toBe("自动任务 · 机械手平台");
  });

  it("fully collapses the native host sidebar and reopens it only on click", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Desktop chat",
      },
    ];
    vi.mocked(fetchBootstrap).mockResolvedValue({
      token: "tok",
      ws_path: "/",
      expires_in: 300,
      runtime_surface: "native",
    });

    // Native runtime defaults to the operator console; force the engineer Shell
    // so this test's host-sidebar assertions still apply.
    window.history.replaceState(null, "", "/#/engineer");

    render(<App />);

    await loginViaForm();
    const flowSidebar = screen.getByTestId("host-sidebar-flow");
    const toggle = screen.getByTestId("host-sidebar-toggle");
    expect(flowSidebar).toHaveStyle({ width: "272px" });
    expect(toggle).toHaveStyle({ left: "236px" });
    expect(
      screen.getByRole("navigation", { name: "Sidebar navigation" }),
    ).toBeInTheDocument();

    fireEvent.click(toggle);
    await waitFor(() => expect(flowSidebar).toHaveStyle({ width: "0px" }));
    expect(toggle).toHaveStyle({ left: "12px" });
    expect(
      screen.queryByRole("navigation", { name: "Sidebar navigation" }),
    ).not.toBeInTheDocument();

    fireEvent.mouseEnter(toggle);
    expect(screen.queryByTestId("host-sidebar-preview")).not.toBeInTheDocument();
    expect(flowSidebar).toHaveStyle({ width: "0px" });

    fireEvent.click(toggle);
    expect(flowSidebar).toHaveStyle({ width: "272px" });
    expect(
      screen.getByRole("navigation", { name: "Sidebar navigation" }),
    ).toBeInTheDocument();
  });

  it("uses only the mobile drawer trigger below the desktop sidebar breakpoint", async () => {
    vi.mocked(fetchBootstrap).mockResolvedValue({
      token: "tok",
      ws_path: "/",
      expires_in: 300,
      runtime_surface: "native",
    });
    window.history.replaceState(null, "", "/#/engineer");
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("1024px") ? false : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));

    render(<App />);
    await loginViaForm();

    expect(screen.getByTestId("host-sidebar-toggle").closest("header")).toHaveClass("hidden", "lg:block");
    expect(
      screen.getAllByRole("button", { name: "Toggle sidebar" }).find(
        (button) => button.classList.contains("lg:hidden"),
      ),
    ).toBeDefined();
  });

  it("switches to the next session when deleting the active chat", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^First chat$/ }),
      ).toBeInTheDocument(),
    );

    fireEvent.pointerDown(screen.getByLabelText("Chat actions for First chat"), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));

    await waitFor(() =>
      expect(screen.getByText("Delete this chat?")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(deleteChatSpy).toHaveBeenCalledWith("websocket:chat-a"),
    );
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^Second chat$/ }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Delete this chat?")).not.toBeInTheDocument();
    expect(document.body.style.pointerEvents).not.toBe("none");
  }, 15_000);

  it("shows localized bound automations in the first delete confirmation", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];
    getSessionAutomationsSpy.mockResolvedValue([
      {
        id: "job-1",
        name: "Daily repo check",
        enabled: true,
        schedule: { kind: "every", every_ms: 86_400_000 },
        payload: { message: "Check the repo" },
        state: { next_run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0) },
      },
    ]);
    await i18n.changeLanguage("zh-CN");

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "侧边栏导航" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^First chat$/ }),
      ).toBeInTheDocument(),
    );

    fireEvent.pointerDown(screen.getByLabelText(/First chat.*会话操作/), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }));

    await waitFor(() =>
      expect(screen.getByText("Daily repo check")).toBeInTheDocument(),
    );
    expect(getSessionAutomationsSpy).toHaveBeenCalledWith("websocket:chat-a");
    expect(
      screen.getByText("这个对话有关联的自动任务。删除对话也会删除这些自动任务。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("This chat has scheduled automations. Deleting it will also delete them."),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除" }));

    await waitFor(() =>
      expect(deleteChatSpy).toHaveBeenCalledWith("websocket:chat-a", {
        deleteAutomations: true,
      }),
    );
    expect(deleteChatSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Daily repo check")).not.toBeInTheDocument();
  }, 15_000);

  it("keeps the mobile session action menu inside the sidebar sheet", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: !query.includes("1024px"),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );

    render(<App />);

    await loginViaForm();
    fireEvent.click(screen.getByRole("button", { name: "Toggle sidebar" }));

    const sheet = await screen.findByRole("dialog");
    const mobileSidebar = within(sheet).getByRole("navigation", {
      name: "Sidebar navigation",
    });
    await waitFor(() =>
      expect(
        within(mobileSidebar).getByRole("button", { name: /^Existing chat$/ }),
      ).toBeInTheDocument(),
    );

    fireEvent.pointerDown(
      within(mobileSidebar).getByLabelText("Chat actions for Existing chat"),
      { button: 0 },
    );

    const deleteItem = await within(sheet).findByRole("menuitem", {
      name: "Delete",
    });
    expect(deleteItem).toBeInTheDocument();

    fireEvent.click(deleteItem);
    await waitFor(() =>
      expect(screen.getByText("Delete this chat?")).toBeInTheDocument(),
    );
  }, 15_000);

  it("applies persisted sidebar workspace state from the gateway", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];
    const initialState = {
      schema_version: 1,
      pinned_keys: ["websocket:chat-b"],
      archived_keys: ["websocket:chat-a"],
      title_overrides: { "websocket:chat-b": "Roadmap" },
      tags_by_key: {},
      collapsed_groups: {},
      view: {
        density: "comfortable",
        show_previews: false,
        show_timestamps: false,
        show_archived: false,
        sort: "updated_desc",
      },
      updated_at: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string | URL | Request) => {
        const href = String(url);
        if (href === "/api/webui/sidebar-state") {
          return { ok: true, json: async () => initialState };
        }
        if (href.startsWith("/api/webui/sidebar-state/update?")) {
          const encoded = new URLSearchParams(href.split("?", 2)[1]).get("state");
          return {
            ok: true,
            json: async () => JSON.parse(encoded ?? "{}"),
          };
        }
        return { ok: false, status: 404 };
      }),
    );

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByText("Pinned")).toBeInTheDocument(),
    );
    expect(within(sidebar).getByRole("button", { name: /^Roadmap$/ })).toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: /^First chat$/ })).not.toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", { name: "Show archived" }));
    await waitFor(() =>
      expect(within(sidebar).getByText("Archived")).toBeInTheDocument(),
    );
    expect(within(sidebar).getByRole("button", { name: /^First chat$/ })).toBeInTheDocument();
    const updateUrl = vi.mocked(fetch).mock.calls
      .map(([url]) => String(url))
      .find((url) => url.startsWith("/api/webui/sidebar-state/update?"));
    expect(updateUrl).toBeTruthy();
    const encoded = new URLSearchParams(updateUrl?.split("?", 2)[1]).get("state");
    expect(JSON.parse(encoded ?? "{}").view.show_archived).toBe(true);

    expect(within(sidebar).queryByRole("button", { name: "View" })).not.toBeInTheDocument();
  });

  it("sorts chats by displayed title when A-Z is persisted", async () => {
    mockSessions = [
      {
        key: "websocket:zulu",
        channel: "websocket",
        chatId: "zulu",
        createdAt: "2026-04-16T12:00:00Z",
        updatedAt: "2026-04-16T12:00:00Z",
        title: "Zulu work",
        preview: "later",
      },
      {
        key: "websocket:new",
        channel: "websocket",
        chatId: "new",
        createdAt: "2026-04-15T12:00:00Z",
        updatedAt: "2026-04-15T12:00:00Z",
        preview: "hi nanobot",
      },
      {
        key: "websocket:alpha",
        channel: "websocket",
        chatId: "alpha",
        createdAt: "2026-04-14T12:00:00Z",
        updatedAt: "2026-04-14T12:00:00Z",
        title: "Alpha plan",
        preview: "earlier",
      },
    ];
    const initialState = {
      schema_version: 1,
      pinned_keys: [],
      archived_keys: [],
      title_overrides: {},
      tags_by_key: {},
      collapsed_groups: {},
      view: {
        density: "comfortable",
        show_previews: false,
        show_timestamps: false,
        show_archived: false,
        sort: "title_asc",
      },
      updated_at: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string | URL | Request) => {
        const href = String(url);
        if (href === "/api/webui/sidebar-state") {
          return { ok: true, json: async () => initialState };
        }
        return { ok: false, status: 404 };
      }),
    );

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByText("Chats")).toBeInTheDocument(),
    );
    const group = within(sidebar).getByText("Chats").closest("section");
    expect(group).toBeTruthy();
    const labels = within(group as HTMLElement)
      .getAllByRole("button")
      .map((button) => button.textContent?.trim())
      .filter(Boolean);

    expect(labels).toEqual(["Alpha plan", "New chat", "Zulu work"]);
  });

  it("shows running and completed session indicators in the sidebar", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Working chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Quiet chat",
      },
    ];

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^Working chat$/ }),
      ).toBeInTheDocument(),
    );

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", 12_345);
    });
    expect(within(sidebar).getByTitle("Agent running")).toBeInTheDocument();

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", null);
    });
    expect(within(sidebar).queryByTitle("Agent running")).not.toBeInTheDocument();
    expect(within(sidebar).getByTitle("New activity")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Working chat$/ }));
    });
    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();
  });

  it("does not show an updated dot later when the active session finishes", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Active work",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Other chat",
      },
    ];

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^Active work$/ }),
      ).toBeInTheDocument(),
    );

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Active work$/ }));
    });
    await waitFor(() => expect(document.title).toContain("Active work"));

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", 12_345);
    });
    expect(within(sidebar).getByTitle("Agent running")).toBeInTheDocument();

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", null);
    });
    expect(within(sidebar).queryByTitle("Agent running")).not.toBeInTheDocument();
    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Other chat$/ }));
    });
    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();
  });

  it("marks inactive sessions when a thread update arrives", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Open chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Scheduled update target",
      },
    ];

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Open chat$/ }));
    });

    act(() => {
      for (const handler of sessionUpdateHandlers) handler("chat-b", "thread");
    });

    expect(within(sidebar).getByTitle("New activity")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Scheduled update target$/ }));
    });

    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();
  });

  it("restores sidebar run indicators after a page reload", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Running after reload",
        runStartedAt: 12_345,
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Completed after reload",
      },
    ];
    localStorage.setItem(
      "nanobot-webui.sidebar.session-updates.v1",
      JSON.stringify(["chat-b"]),
    );

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByTitle("Agent running")).toBeInTheDocument(),
    );
    expect(within(sidebar).getByTitle("New activity")).toBeInTheDocument();
    expect(attachSpy).toHaveBeenCalledWith("chat-a");
  });

  it("restores the active chat from the URL hash after a page reload", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Active after reload",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Other chat",
      },
    ];
    window.history.replaceState(
      null,
      "",
      `/#/chat/${encodeURIComponent("websocket:chat-a")}`,
    );

    render(<App />);

    await loginViaForm();
    await waitFor(() => expect(document.title).toBe("Active after reload · Arm Platform"));
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(
      within(sidebar).getByRole("button", { name: /^Active after reload$/ }),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe(
      `#/chat/${encodeURIComponent("websocket:chat-a")}`,
    );
  });

  it("opens the settings view from the sidebar footer", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const href = String(input);
        if (href === "/api/settings/provider-models?provider=openai") {
          return jsonResponse({
            provider: "openai",
            label: "OpenAI",
            status: "available",
            catalog_kind: "official",
            models: [
              { id: "openai/gpt-4o", owned_by: "openai", context_window: 128000 },
              { id: "openai/gpt-4o-mini", owned_by: "openai", context_window: 128000 },
            ],
            model_count: 2,
            fetched_at: 1,
          });
        }
        if (href.includes("/api/settings")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              agent: {
                model: "openai/gpt-4o",
                provider: "auto",
                resolved_provider: "openai",
                has_api_key: true,
                model_preset: "default",
                max_tokens: 8192,
                context_window_tokens: 65536,
                temperature: 0.1,
                reasoning_effort: null,
                timezone: "UTC",
                bot_name: "nanobot",
                bot_icon: "nb",
                tool_hint_max_length: 40,
              },
              model_presets: [
                {
                  name: "default",
                  label: "Default",
                  active: true,
                  is_default: true,
                  model: "openai/gpt-4o",
                  provider: "auto",
                  max_tokens: 8192,
                  context_window_tokens: 65536,
                  temperature: 0.1,
                  reasoning_effort: null,
                },
                {
                  name: "deep",
                  label: "deep",
                  active: false,
                  is_default: false,
                  model: "anthropic/claude-opus-4-5",
                  provider: "anthropic",
                  max_tokens: 8192,
                  context_window_tokens: 200000,
                  temperature: 0.1,
                  reasoning_effort: "high",
                },
              ],
              providers: [
                {
                  name: "openai",
                  label: "OpenAI",
                  configured: true,
                  api_key_hint: "open••••-key",
                },
                {
                  name: "openrouter",
                  label: "OpenRouter",
                  configured: false,
                  api_key_required: true,
                  default_api_base: "https://openrouter.ai/api/v1",
                },
                {
                  name: "ant_ling",
                  label: "Ant Ling",
                  configured: false,
                  api_key_required: true,
                  default_api_base: "https://api.ant-ling.com/v1",
                },
                {
                  name: "azure_openai",
                  label: "Azure OpenAI",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "huggingface",
                  label: "Hugging Face",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "siliconflow",
                  label: "SiliconFlow",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "volcengine",
                  label: "VolcEngine",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "byteplus",
                  label: "BytePlus",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "qianfan",
                  label: "Qianfan",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "atomic_chat",
                  label: "Atomic Chat",
                  configured: false,
                  api_key_required: false,
                  default_api_base: "http://localhost:1337/v1",
                },
              ],
              web_search: {
                provider: "brave",
                api_key_hint: "BSAo••••ew20",
                base_url: null,
                max_results: 5,
                timeout: 30,
                providers: [
                  { name: "duckduckgo", label: "DuckDuckGo", credential: "none" },
                  { name: "brave", label: "Brave Search", credential: "api_key" },
                  { name: "tavily", label: "Tavily", credential: "api_key" },
                ],
              },
              web: {
                enable: true,
                proxy: null,
                user_agent: null,
                search: { max_results: 5, timeout: 30 },
                fetch: { use_jina_reader: true },
              },
              image_generation: {
                enabled: false,
                provider: "openrouter",
                provider_configured: true,
                model: "openai/gpt-5.4-image-2",
                default_aspect_ratio: "1:1",
                default_image_size: "1K",
                max_images_per_turn: 4,
                save_dir: "generated",
                providers: [
                  {
                    name: "openrouter",
                    label: "OpenRouter",
                    configured: true,
                    api_key_hint: "sk-o••••test",
                    api_base: "https://openrouter.ai/api/v1",
                    default_api_base: "https://openrouter.ai/api/v1",
                  },
                  {
                    name: "gemini",
                    label: "Gemini",
                    configured: false,
                    api_key_hint: null,
                    api_base: null,
                    default_api_base: "https://generativelanguage.googleapis.com/v1beta/openai/",
                  },
                ],
              },
              runtime: {
                config_path: "/tmp/config.json",
                workspace_path: "/tmp/workspace",
                gateway_host: "127.0.0.1",
                gateway_port: 18790,
                heartbeat: {
                  enabled: true,
                  interval_s: 1800,
                  keep_recent_messages: 8,
                },
                dream: {
                  schedule: "every 2h",
                },
                unified_session: false,
              },
              advanced: {
                restrict_to_workspace: false,
                webui_allow_local_service_access: true,
                webui_default_access_mode: "default",
                private_service_protection_enabled: true,
                ssrf_whitelist_count: 0,
                mcp_server_count: 0,
                exec_enabled: true,
                exec_sandbox: null,
                exec_path_prepend_set: false,
                exec_path_append_set: false,
              },
              requires_restart: false,
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const commandsButton = within(sidebar).getByRole("button", { name: "Commands" });
    expect(within(sidebar).queryByRole("textbox", { name: "Search" })).not.toBeInTheDocument();
    expect(commandsButton).toBeInTheDocument();
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(document.title).toBe("Settings · Arm Platform");
    expect(screen.getByTestId("overview-logo-openai")).toBeInTheDocument();
    expect(screen.getByTestId("overview-logo-brave")).toBeInTheDocument();
    expect(screen.getByTestId("overview-logo-openrouter")).toBeInTheDocument();
    expect(screen.queryByTestId("overview-logo-nanobot-gateway")).not.toBeInTheDocument();
    expect(screen.queryByTestId("overview-logo-nanobot-workspace")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Sidebar navigation" })).not.toBeInTheDocument();
    const settingsNav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(settingsNav.className).toContain("overflow-x-auto");
    expect(settingsNav.className).not.toContain("grid-cols-2");
    expect(within(settingsNav).getByRole("button", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(settingsNav).getByRole("button", { name: "Models" })).toBeInTheDocument();
    expect(within(settingsNav).queryByRole("button", { name: "Providers" })).not.toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Image" })).toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Web" })).toBeInTheDocument();
    expect(within(settingsNav).queryByRole("button", { name: "Apps" })).not.toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Security" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    fireEvent.click(within(settingsNav).getByRole("button", { name: "Appearance" }));
    expect(screen.getByText("Brand logos")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Brand logos" })).toBeInTheDocument();
    fireEvent.click(within(settingsNav).getByRole("button", { name: "Models" }));
    expect(screen.queryByText("AI")).not.toBeInTheDocument();
    expect(screen.getByText("Current configuration")).toBeInTheDocument();
    expect(screen.queryByText("Presets")).not.toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Current configuration" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Add configuration" }));
    const modelDialog = await screen.findByRole("dialog", { name: "New model configuration" });
    expect(within(modelDialog).getByText("Save a provider and model as a one-click option.")).toBeInTheDocument();
    fireEvent.change(within(modelDialog).getByPlaceholderText("Fast writing"), {
      target: { value: "Fast writing" },
    });
    fireEvent.change(within(modelDialog).getByPlaceholderText("openai/gpt-4.1"), {
      target: { value: "openai/gpt-4.1-mini" },
    });
    expect(within(modelDialog).getByRole("button", { name: /OpenAI/ })).toBeInTheDocument();
    expect(within(modelDialog).getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(within(modelDialog).getByRole("button", { name: "Cancel" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: /Auto/ }));
    expect(screen.getAllByTestId("provider-picker-logo-openai").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("menuitem", { name: /Auto/ }));
    const openModelPicker = () => {
      const modelButtons = screen.getAllByRole("button", { name: /openai\/gpt-4o/ });
      fireEvent.pointerDown(modelButtons[modelButtons.length - 1]);
    };
    openModelPicker();
    await screen.findByText("openai/gpt-4o-mini");
    fireEvent.click(screen.getAllByText("openai/gpt-4o-mini")[0]);
    expect(screen.getByText("Unsaved changes.").parentElement?.className).toContain(
      "text-blue-600",
    );
    const updatedModelButtons = screen.getAllByRole("button", { name: /openai\/gpt-4o-mini/ });
    fireEvent.pointerDown(updatedModelButtons[updatedModelButtons.length - 1]);
    await screen.findByText("openai/gpt-4o");
    fireEvent.click(screen.getAllByText("openai/gpt-4o")[0]);
    expect(screen.getByText("OpenRouter")).toBeInTheDocument();
    expect(screen.getByText("Ant Ling")).toBeInTheDocument();
    expect(screen.getByTestId("provider-logo-openai")).toBeInTheDocument();
    expect(screen.getByText(/Product names, logos, and brands/)).toBeInTheDocument();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
    const clickProviderRow = (label: string) => {
      const providerLabel = screen
        .getAllByText(label)
        .find((element) => element.className.includes("font-semibold"));
      expect(providerLabel).toBeTruthy();
      fireEvent.click(providerLabel!);
    };
    clickProviderRow("OpenAI");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByPlaceholderText("Leave blank to keep the current key"), {
      target: { value: "unsaved-openai-key" },
    });
    clickProviderRow("OpenRouter");
    clickProviderRow("OpenAI");
    expect(screen.getByText("open••••-key")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("unsaved-openai-key")).not.toBeInTheDocument();
    clickProviderRow("Ant Ling");
    expect(screen.getByDisplayValue("https://api.ant-ling.com/v1")).toBeInTheDocument();
    clickProviderRow("Atomic Chat");
    expect(screen.getByDisplayValue("http://localhost:1337/v1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save provider" })).toBeEnabled();

    fireEvent.click(within(settingsNav).getByRole("button", { name: "Image" }));
    expect(screen.getByRole("heading", { name: "Image" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Image generation" })).toBeInTheDocument();
    expect(screen.getByText("Provider status")).toBeInTheDocument();
    expect(screen.getByDisplayValue("openai/gpt-5.4-image-2")).toBeInTheDocument();
    expect(screen.getByText("Save directory")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    fireEvent.click(within(settingsNav).getByRole("button", { name: "Web" }));
    expect(screen.getByText("Search provider")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Jina reader" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Brave Search/ })).toBeInTheDocument();
    expect(screen.getByTestId("provider-picker-logo-brave")).toBeInTheDocument();
    expect(screen.getByText("BSAo••••ew20")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByPlaceholderText("Leave blank to keep the current key"), {
      target: { value: "unsaved-brave-key" },
    });
    fireEvent.pointerDown(screen.getByRole("button", { name: /Brave Search/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Tavily" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: /Tavily/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Brave Search" }));
    expect(screen.getByText("BSAo••••ew20")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("unsaved-brave-key")).not.toBeInTheDocument();

    fireEvent.click(within(settingsNav).getByRole("button", { name: "System" }));
    expect(screen.queryByText("Bot name")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool hint length")).not.toBeInTheDocument();
    expect(screen.queryByText("Heartbeat")).not.toBeInTheDocument();
    expect(screen.queryByText("Dream")).not.toBeInTheDocument();
    expect(screen.queryByText("Unified session")).not.toBeInTheDocument();
    expect(screen.getByText("Default workspace")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.pointerDown(screen.getByRole("button", { name: "UTC" }));
    expect(screen.getByPlaceholderText("Search timezone")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search timezone"), {
      target: { value: "Shanghai" },
    });
    fireEvent.click(screen.getByRole("menuitem", { name: /Asia\/Shanghai/ }));
    expect(screen.getByRole("button", { name: "Asia/Shanghai" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("restores the settings section from the URL hash after a page reload", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });
    window.history.replaceState(null, "", "/#/settings?section=voice");

    render(<App />);

    await loginViaForm();
    expect(await screen.findByRole("heading", { name: "Voice input" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings?section=voice");
  });

  it("updates the URL hash when switching settings sections", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings");

    const settingsNav = screen.getByRole("navigation", { name: "Settings sections" });
    fireEvent.click(within(settingsNav).getByRole("button", { name: "Models" }));

    expect(await screen.findByRole("heading", { name: "Models" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings?section=models");

    fireEvent.click(within(settingsNav).getByRole("button", { name: "Voice" }));

    expect(await screen.findByRole("heading", { name: "Voice input" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings?section=voice");
  });

  // Replaces the stale "opens Apps from the main sidebar" skip (A2 removed the
  // main-sidebar Apps button). Verifies the engineer shell exposes the Commands
  // (command library) entry that replaced Apps/Skills in the main sidebar.
  it("engineer shell exposes the Commands entry after login", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });

    render(<App />);

    await loginViaForm("engineer");
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).getByRole("button", { name: "Commands" })).toBeInTheDocument();
  });

  it("returns from settings to the blank start page when no session was active", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/api/settings")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              agent: {
                model: "openai/gpt-4o",
                provider: "openai",
                resolved_provider: "openai",
                has_api_key: true,
                model_preset: "default",
                max_tokens: 8192,
                context_window_tokens: 65536,
                temperature: 0.1,
                reasoning_effort: null,
                timezone: "UTC",
                bot_name: "nanobot",
                bot_icon: "nb",
                tool_hint_max_length: 40,
              },
              model_presets: [
                {
                  name: "default",
                  label: "Default",
                  active: true,
                  is_default: true,
                  model: "openai/gpt-4o",
                  provider: "openai",
                  max_tokens: 8192,
                  context_window_tokens: 65536,
                  temperature: 0.1,
                  reasoning_effort: null,
                },
              ],
              providers: [{ name: "openai", label: "OpenAI", configured: true }],
              web_search: {
                provider: "duckduckgo",
                api_key_hint: null,
                base_url: null,
                max_results: 5,
                timeout: 30,
                providers: [
                  { name: "duckduckgo", label: "DuckDuckGo", credential: "none" },
                  { name: "brave", label: "Brave Search", credential: "api_key" },
                ],
              },
              web: {
                enable: true,
                proxy: null,
                user_agent: null,
                search: { max_results: 5, timeout: 30 },
                fetch: { use_jina_reader: true },
              },
              image_generation: {
                enabled: false,
                provider: "openrouter",
                provider_configured: false,
                model: "openai/gpt-5.4-image-2",
                default_aspect_ratio: "1:1",
                default_image_size: "1K",
                max_images_per_turn: 4,
                save_dir: "generated",
                providers: [
                  {
                    name: "openrouter",
                    label: "OpenRouter",
                    configured: false,
                    api_key_hint: null,
                    api_base: null,
                    default_api_base: "https://openrouter.ai/api/v1",
                  },
                ],
              },
              runtime: {
                config_path: "/tmp/config.json",
                workspace_path: "/tmp/workspace",
                gateway_host: "127.0.0.1",
                gateway_port: 18790,
                heartbeat: {
                  enabled: true,
                  interval_s: 1800,
                  keep_recent_messages: 8,
                },
                dream: {
                  schedule: "every 2h",
                },
                unified_session: false,
              },
              advanced: {
                restrict_to_workspace: false,
                webui_allow_local_service_access: true,
                webui_default_access_mode: "default",
                private_service_protection_enabled: true,
                ssrf_whitelist_count: 0,
                mcp_server_count: 0,
                exec_enabled: true,
                exec_sandbox: null,
                exec_path_prepend_set: false,
                exec_path_append_set: false,
              },
              requires_restart: false,
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "New chat" }));
    await waitFor(() => expect(document.title).toBe("Robotic Arm Platform"));

    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));

    await waitFor(() => expect(document.title).toBe("Robotic Arm Platform"));
    expect(screen.getByText(HERO_GREETING_PATTERN)).toBeInTheDocument();
  });

  it("filters sessions in the centered search dialog from the keyboard shortcut", async () => {
    mockSessions = [
      {
        key: "websocket:chat-alpha",
        channel: "websocket",
        chatId: "chat-alpha",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        title: "Q2 roadmap",
        preview: "Project planning notes",
      },
      {
        key: "websocket:chat-beta",
        channel: "websocket",
        chatId: "chat-beta",
        createdAt: "2026-04-15T10:00:00Z",
        updatedAt: "2026-04-15T10:00:00Z",
        preview: "Travel ideas",
      },
    ];

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(sidebar).getByText("Travel ideas")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Search" });
    expect(dialog).toHaveClass("origin-center");
    expect(dialog.className).not.toContain("translate-x");
    expect(dialog.className).not.toContain("translate-y");
    expect(dialog.querySelector("kbd")).toBeNull();
    expect(within(dialog).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(dialog).getByText("Travel ideas")).toBeInTheDocument();
    expect(within(dialog).queryByText("websocket")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("#1")).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search" }), {
      target: { value: "planning" },
    });

    expect(within(dialog).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(dialog).queryByText("Travel ideas")).not.toBeInTheDocument();
    expect(within(sidebar).getByText("Travel ideas")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search" }), {
      target: { value: "road q2" },
    });

    expect(within(dialog).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(dialog).queryByText("Travel ideas")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: /Q2 roadmap/ }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument(),
    );
  });

  it("opens search from the keyboard shortcut", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    render(<App />);

    await loginViaForm();
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    const dialog = await screen.findByRole("dialog", { name: "Search" });
    expect(within(dialog).queryByText("Global actions")).not.toBeInTheDocument();
    expect(within(dialog).getByText("Existing chat")).toBeInTheDocument();

    const textbox = within(dialog).getByRole("textbox", { name: "Search" });
    fireEvent.change(textbox, { target: { value: "missing" } });
    expect(within(dialog).queryByText("Existing chat")).not.toBeInTheDocument();

    fireEvent.change(textbox, { target: { value: "existing" } });
    expect(within(dialog).getByText("Existing chat")).toBeInTheDocument();

    fireEvent.keyDown(textbox, { key: "Enter" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument(),
    );
    expect(createChatSpy).not.toHaveBeenCalled();
  });

  it.each([
    ["Command", { metaKey: true }],
    ["Control", { ctrlKey: true }],
  ])("starts a new chat from the %s keyboard shortcut", async (_label, modifier) => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    render(<App />);

    await loginViaForm();
    fireEvent.keyDown(window, { key: "O", shiftKey: true, ...modifier });

    expect(window.location.hash).toBe("#/new");
  });

  it("closes search when starting a new chat from the keyboard shortcut", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    render(<App />);

    await loginViaForm();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(await screen.findByRole("dialog", { name: "Search" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "O", shiftKey: true, metaKey: true });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument(),
    );
    expect(window.location.hash).toBe("#/new");
  });

  it("exposes the new chat keyboard shortcut in the sidebar title", async () => {
    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });

    const newChatButton = within(sidebar).getByRole("button", { name: "New chat" });
    expect(newChatButton).toHaveAttribute(
      "title",
      "New chat (Ctrl+Shift+O)",
    );
    expect(newChatButton).toHaveAttribute(
      "aria-keyshortcuts",
      "Meta+Shift+O Control+Shift+O",
    );
  });

  it("uses macOS shortcut glyphs in the sidebar title", async () => {
    setNavigatorPlatform("MacIntel");
    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });

    expect(within(sidebar).getByRole("button", { name: "New chat" })).toHaveAttribute(
      "title",
      "New chat (⌘⇧O)",
    );
  });

  it("keeps large sidebars light while search still covers every chat", async () => {
    mockSessions = Array.from({ length: 170 }, (_, index) => {
      const chatId = `chat-${index}`;
      return {
        key: `websocket:${chatId}`,
        channel: "websocket" as const,
        chatId,
        createdAt: new Date(Date.UTC(2026, 3, 16, 12, 0 - index)).toISOString(),
        updatedAt: new Date(Date.UTC(2026, 3, 16, 12, 0 - index)).toISOString(),
        title: index === 169 ? "Hidden target" : `Bulk chat ${index}`,
        preview: "",
      };
    });

    render(<App />);

    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByRole("button", { name: "Bulk chat 0" })).toBeInTheDocument(),
    );
    expect(within(sidebar).queryByText("Hidden target")).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Show 10 more" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Search" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search" }), {
      target: { value: "hidden" },
    });
    expect(within(dialog).getByText("Hidden target")).toBeInTheDocument();
  });

  it("opens a blank start page without creating an empty chat", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    const matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("1024px"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", matchMedia);

    const { container } = render(<App />);

    await loginViaForm();

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme from header" }));
    expect(toggleThemeSpy).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    const sidebarAside = container.querySelector("aside.lg\\:block") as HTMLElement;
    await waitFor(() => expect(sidebarAside.style.width).toBe("56px"));

    expect(screen.queryByRole("button", { name: "Start a new chat" })).not.toBeInTheDocument();
    const rail = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(rail).getByRole("button", { name: "New chat" })).toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: "Search" })).not.toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: "View" })).not.toBeInTheDocument();
    expect(within(rail).queryByText("Existing chat")).not.toBeInTheDocument();

    fireEvent.click(within(rail).getByRole("button", { name: "Toggle sidebar" }));
    await waitFor(() => expect(sidebarAside.style.width).toBe("272px"));

    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "New chat" }));
    expect(createChatSpy).not.toHaveBeenCalled();
    expect(screen.getByText(HERO_GREETING_PATTERN)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a new chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toggle theme from header" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Settings" })).toBeInTheDocument();

    expect(within(sidebar).getByText("Existing chat")).toBeInTheDocument();
  });

  it("refreshes the bootstrap token before REST settings auth expires", async () => {
    vi.useFakeTimers();
    vi.mocked(fetchBootstrap)
      .mockResolvedValueOnce({
        token: "tok-1",
        ws_path: "/",
        expires_in: 30,
      })
      .mockResolvedValueOnce({
        token: "tok-2",
        ws_path: "/",
        expires_in: 300,
      });
    vi.mocked(deriveWsUrl).mockImplementation(
      (_wsPath: string, token: string) => `ws://test?token=${token}`,
    );

    const { unmount } = render(<App />);
    // Bootstrap → auth; drive login to reach the ready state (ws-token refresh
    // timer only runs once ready). Fake timers are on, so flush via act and
    // query synchronously instead of findBy* (which polls on faked setTimeout).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      const form = screen.getByRole("form");
      fireEvent.change(form.querySelector('input[autocomplete="username"]')!, { target: { value: "engineer" } });
      fireEvent.change(form.querySelector('input[type="password"]')!, { target: { value: "pass" } });
      fireEvent.click(form.querySelector('button[type="submit"]')!);
    });

    expect(connectSpy).toHaveBeenCalled();
    expect(fetchBootstrap).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    expect(fetchBootstrap).toHaveBeenCalledTimes(2);
    expect(updateUrlSpy).toHaveBeenCalledWith("ws://test?token=tok-2");
    unmount();
  });

  it("removes Apps/Skills from the sidebar and adds the command library entry", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });
    render(<App />);
    await loginViaForm();
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).queryByRole("button", { name: "Apps" })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: "Skills" })).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Commands" })).toBeInTheDocument();
  });

  it("hides RobotSidePanel on #/library whether mounted directly or navigated from #/engineer", async () => {
    const libraryRoutes = {
      "/api/settings": baseSettingsPayload(),
      "/api/robot/status": {
        ok: true,
        data: { robot_state: { mode: "idle" }, execution_mode: "dry_run_only" },
      },
      "/api/robot/library/commands": { ok: true, data: { items: [], total: 0 } },
      "/api/robot/library/flows": { ok: true, data: { items: [], total: 0 } },
    };

    // (b) Direct #/library mount on native surface.
    vi.mocked(fetchBootstrap).mockResolvedValue({
      token: "tok",
      ws_path: "/",
      expires_in: 300,
      runtime_surface: "native",
    });
    window.history.replaceState(null, "", "/#/library");
    mockFetchRoutes(libraryRoutes);
    const { unmount } = render(<App />);
    await loginViaForm("engineer");
    await waitFor(() =>
      expect(screen.getByTestId("engineer-workbench")).toBeInTheDocument(),
    );
    expect(screen.queryByText("末端位姿")).not.toBeInTheDocument();
    unmount();

    // (a) Mount at #/engineer (RobotSidePanel present), then navigate to #/library.
    window.history.replaceState(null, "", "/#/engineer");
    mockFetchRoutes(libraryRoutes);
    render(<App />);
    await loginViaForm("engineer");
    await waitFor(() => expect(screen.getByText("末端位姿")).toBeInTheDocument());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Commands" }));
    await waitFor(() =>
      expect(screen.getByTestId("engineer-workbench")).toBeInTheDocument(),
    );
    expect(screen.queryByText("末端位姿")).not.toBeInTheDocument();
    expect(window.location.hash).toBe("#/library");
  });
});
