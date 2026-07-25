import type {
  ConnectionStatus,
  InboundEvent,
  Outbound,
  OutboundCliAppMention,
  OutboundImageGeneration,
  OutboundMcpPresetMention,
  OutboundMedia,
  GoalStateWsPayload,
  WorkspaceScopePayload,
} from "./types";
import { createHostWebSocket } from "./runtime";

/** WebSocket readyState constants, referenced by value to stay portable
 * across runtimes that don't expose a global ``WebSocket`` (tests, SSR). */
const WS_OPEN = 1;
const WS_CLOSING = 2;
const HOST_SOCKET_URL_PREFIX = "nanobot-host://";

function createDefaultSocket(url: string): WebSocket {
  if (url.startsWith(HOST_SOCKET_URL_PREFIX)) {
    return createHostWebSocket(url);
  }
  return new WebSocket(url);
}

/** Inbound WebSocket ``console.log`` / parse-failure ``console.warn``.
 *
 * - **Dev** (non-production bundle): **on by default** — messages appear at default log level.
 * - **Production**: off unless ``localStorage.setItem('nanobot_debug_ws','1')`` (or ``true``).
 * - **Silence anywhere**: ``localStorage.setItem('nanobot_debug_ws','0')`` (or ``false`` / ``off``).
 * Values are read on every frame; no reload needed.
 */
function wsInboundDebugEnabled(): boolean {
  if (typeof globalThis === "undefined") return false;
  try {
    if (import.meta.env.MODE === "test") return false;
    const ls = (globalThis as unknown as { localStorage?: Storage }).localStorage;
    const raw = ls?.getItem("nanobot_debug_ws")?.trim().toLowerCase() ?? "";
    if (raw === "0" || raw === "false" || raw === "off" || raw === "no") {
      return false;
    }
    if (raw === "1" || raw === "true" || raw === "on" || raw === "yes") {
      return true;
    }
    return !import.meta.env.PROD;
  } catch {
    return !import.meta.env.PROD;
  }
}

/** Shorten streaming text fields so logging stays usable for huge deltas. */
function summarizeInboundWsPayload(ev: InboundEvent): unknown {
  const kind = (ev as { event?: string }).event;
  if (kind !== "delta" && kind !== "reasoning_delta") return ev;
  const row = { ...(ev as object) } as Record<string, unknown>;
  const text = typeof row.text === "string" ? row.text : "";
  const max = 240;
  if (text.length > max) {
    row.text = `${text.slice(0, max)}… (${text.length} chars)`;
  }
  return row;
}

type Unsubscribe = () => void;
type EventHandler = (ev: InboundEvent) => void;
type StatusHandler = (status: ConnectionStatus) => void;
type RuntimeModelHandler = (modelName: string | null, modelPreset?: string | null) => void;
type SessionUpdateScope = "metadata" | "thread" | string;
type SessionUpdateHandler = (
  chatId: string,
  scope?: SessionUpdateScope,
  workspaceScope?: WorkspaceScopePayload,
) => void;
type RunStatusHandler = (chatId: string, startedAt: number | null) => void;

/** Structured errors surfaced to the UI.
 *
 * Most entries are transport-level or protocol-level faults. Workspace scope
 * rejections are server application errors promoted here because they affect
 * controls outside the message stream and must be visible immediately.
 */
export type StreamError =
  /** Server rejected the inbound frame as too large (WS close code 1009).
   * Typically means the user attached images whose base64 size exceeded
   * ``maxMessageBytes`` on the server. */
  | { kind: "message_too_big" }
  | { kind: "workspace_scope_rejected"; reason?: string; chatId?: string };

type ErrorHandler = (error: StreamError) => void;

interface PendingNewChat {
  resolve: (chatId: string) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

interface PendingTranscription {
  resolve: (text: string) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

interface PendingVoiceStart {
  resolve: () => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

interface PendingVoiceFinal {
  resolve: (text: string) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export interface NanobotClientOptions {
  url: string;
  reconnect?: boolean;
  /** Called when a connection drops so the app can refresh its token. */
  onReauth?: () => Promise<string | null>;
  /** Inject a custom WebSocket factory (used by unit tests). */
  socketFactory?: (url: string) => WebSocket;
  /** Delay-cap for reconnect backoff (ms). */
  maxBackoffMs?: number;
  /** Slice ②: fired once when the server rejects our ``auth`` frame (closes
   * with code 1008 before ``auth_ok``). The client does NOT auto-reconnect in
   * this case — the app should bounce to the login screen (F3). */
  onAuthFailed?: () => void;
}

/**
 * Singleton WebSocket client that multiplexes chat streams.
 *
 * One socket carries many chat_ids: the server tags every outbound event with
 * ``chat_id``, and this class fans those events out to handlers registered
 * per chat. Reconnects are transparent and re-attach every known chat_id.
 */
export class NanobotClient {
  private socket: WebSocket | null = null;
  private statusHandlers = new Set<StatusHandler>();
  private runtimeModelHandlers = new Set<RuntimeModelHandler>();
  private sessionUpdateHandlers = new Set<SessionUpdateHandler>();
  private runStatusHandlers = new Set<RunStatusHandler>();
  private errorHandlers = new Set<ErrorHandler>();
  // chat_id -> handlers listening on it
  private chatHandlers = new Map<string, Set<EventHandler>>();
  /** Inbound frames received while no subscriber is registered (e.g. user switched away). */
  private pendingInboundByChat = new Map<string, InboundEvent[]>();
  private static readonly PENDING_INBOUND_MAX = 2000;
  // chat_ids we've attached to since connect; re-attached after reconnects
  private knownChats = new Set<string>();
  /** Wall-clock run strip: updated from ``goal_status`` even with no ``onChat`` subscriber. */
  private runStartedAtByChatId = new Map<string, number>();
  /** Latest ``goal_state`` snapshot per ``chat_id`` (multi-session isolation). */
  private goalStateByChatId = new Map<string, GoalStateWsPayload>();
  private pendingNewChat: PendingNewChat | null = null;
  private pendingTranscriptions = new Map<string, PendingTranscription>();
  private pendingVoiceStarts = new Map<string, PendingVoiceStart>();
  private pendingVoiceFinals = new Map<string, PendingVoiceFinal>();
  /** A realtime provider can emit its final frame just before the operator's
   * stop click registers its promise. Retain that one terminal frame briefly
   * instead of silently dropping it and timing out the UI. */
  private earlyVoiceFinals = new Map<string, string>();
  private earlyVoiceErrors = new Map<string, string>();
  // Frames queued while the socket is not yet OPEN
  private sendQueue: Outbound[] = [];
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly shouldReconnect: boolean;
  private readonly maxBackoffMs: number;
  private socketFactory: (url: string) => WebSocket;
  private currentUrl: string;
  private status_: ConnectionStatus = "idle";
  private readyChatId: string | null = null;
  // Set by ``close()`` so the onclose handler knows the drop was intentional
  // and must not schedule a reconnect or flip status back to "reconnecting".
  private intentionallyClosed = false;
  /** Slice ② user session token — sent as the first frame on every connection. */
  private authToken: string | null = null;
  /** True once the server has replied ``auth_ok`` this connection. While
   * false, all business frames are buffered in ``sendQueue``. */
  private authed = false;
  /** True between ``handleOpen`` and ``auth_ok`` (or an auth-failure close). */
  private authPending = false;
  private readonly onAuthFailed?: () => void;

  constructor(private options: NanobotClientOptions) {
    this.shouldReconnect = options.reconnect ?? true;
    this.maxBackoffMs = options.maxBackoffMs ?? 15_000;
    this.socketFactory = options.socketFactory ?? createDefaultSocket;
    this.currentUrl = options.url;
    this.onAuthFailed = options.onAuthFailed;
  }

  /** Slice ②: set/refresh the user session token. Sent as ``{type:"auth"}``
   * on the next connection (and every reconnect). */
  setAuthToken(token: string): void {
    this.authToken = token;
  }

  get status(): ConnectionStatus {
    return this.status_;
  }

  get defaultChatId(): string | null {
    return this.readyChatId;
  }

  /** Swap the URL (e.g. after fetching a fresh token) then reconnect. */
  updateUrl(url: string, socketFactory?: (url: string) => WebSocket): void {
    this.currentUrl = url;
    if (socketFactory) {
      this.socketFactory = socketFactory;
    }
  }

  onStatus(handler: StatusHandler): Unsubscribe {
    this.statusHandlers.add(handler);
    handler(this.status_);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  onRuntimeModelUpdate(handler: RuntimeModelHandler): Unsubscribe {
    this.runtimeModelHandlers.add(handler);
    return () => {
      this.runtimeModelHandlers.delete(handler);
    };
  }

  onSessionUpdate(handler: SessionUpdateHandler): Unsubscribe {
    this.sessionUpdateHandlers.add(handler);
    return () => {
      this.sessionUpdateHandlers.delete(handler);
    };
  }

  onRunStatus(handler: RunStatusHandler): Unsubscribe {
    this.runStatusHandlers.add(handler);
    for (const [chatId, startedAt] of this.runStartedAtByChatId) {
      handler(chatId, startedAt);
    }
    return () => {
      this.runStatusHandlers.delete(handler);
    };
  }

  /** Subscribe to transport-level faults (see :type:`StreamError`). */
  onError(handler: ErrorHandler): Unsubscribe {
    this.errorHandlers.add(handler);
    return () => {
      this.errorHandlers.delete(handler);
    };
  }

  /** Last ``goal_status`` ``started_at`` (unix sec) for *chatId*, if the turn is running. */
  getRunStartedAt(chatId: string): number | null {
    const v = this.runStartedAtByChatId.get(chatId);
    return v === undefined ? null : v;
  }

  /** Last ``goal_state`` payload for *chatId*, if any frame has arrived this connection. */
  getGoalState(chatId: string): GoalStateWsPayload | undefined {
    return this.goalStateByChatId.get(chatId);
  }

  private recordGoalStatusForRunStrip(chatId: string, ev: InboundEvent): void {
    if (ev.event === "turn_end") {
      if (this.runStartedAtByChatId.has(chatId)) {
        this.runStartedAtByChatId.delete(chatId);
        this.emitRunStatus(chatId, null);
      }
      return;
    }
    if (ev.event !== "goal_status") return;
    if (ev.status === "running" && typeof ev.started_at === "number") {
      const previous = this.runStartedAtByChatId.get(chatId);
      this.runStartedAtByChatId.set(chatId, ev.started_at);
      if (previous !== ev.started_at) this.emitRunStatus(chatId, ev.started_at);
    } else if (this.runStartedAtByChatId.has(chatId)) {
      this.runStartedAtByChatId.delete(chatId);
      this.emitRunStatus(chatId, null);
    }
  }

  private recordGoalStateSnapshot(chatId: string, ev: InboundEvent): void {
    if (ev.event === "goal_state") {
      this.goalStateByChatId.set(chatId, ev.goal_state);
      return;
    }
    if (ev.event === "turn_end" && ev.goal_state != null && typeof ev.goal_state === "object") {
      this.goalStateByChatId.set(chatId, ev.goal_state);
    }
  }

  /** Subscribe to events for a given chat_id. Auto-attaches on the next open. */
  onChat(chatId: string, handler: EventHandler): Unsubscribe {
    let handlers = this.chatHandlers.get(chatId);
    if (!handlers) {
      handlers = new Set();
      this.chatHandlers.set(chatId, handlers);
    }
    handlers.add(handler);
    const pending = this.pendingInboundByChat.get(chatId);
    if (pending !== undefined && pending.length > 0) {
      const flushed = pending.splice(0);
      this.pendingInboundByChat.delete(chatId);
      for (const ev of flushed) {
        handler(ev);
      }
    }
    this.attach(chatId);
    return () => {
      const current = this.chatHandlers.get(chatId);
      if (!current) return;
      current.delete(handler);
      if (current.size === 0) this.chatHandlers.delete(chatId);
    };
  }

  connect(): void {
    if (this.socket && this.socket.readyState < WS_CLOSING) return;
    this.intentionallyClosed = false;
    this.setStatus("connecting");
    const sock = this.socketFactory(this.currentUrl);
    this.socket = sock;
    sock.onopen = () => this.handleOpen();
    sock.onmessage = (ev) => this.handleMessage(ev);
    sock.onerror = () => this.setStatus("error");
    sock.onclose = (ev) => this.handleClose(ev);
  }

  close(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const sock = this.socket;
    this.socket = null;
    try {
      sock?.close();
    } catch {
      // ignore
    }
    this.setStatus("closed");
  }

  /** Ask the server to provision a new chat_id; resolves with the assigned id. */
  newChat(timeoutMs: number = 5_000, workspaceScope?: WorkspaceScopePayload | null): Promise<string> {
    if (this.pendingNewChat) {
      return Promise.reject(new Error("newChat already in flight"));
    }
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingNewChat = null;
        reject(new Error("newChat timed out"));
      }, timeoutMs);
      this.pendingNewChat = { resolve, reject, timer };
      this.queueSend({
        type: "new_chat",
        ...(workspaceScope ? { workspace_scope: workspaceScope } : {}),
      });
    });
  }

  transcribeAudio(
    dataUrl: string,
    options?: { durationMs?: number; timeoutMs?: number },
  ): Promise<string> {
    const requestId = crypto.randomUUID();
    const timeoutMs = options?.timeoutMs ?? 120_000;
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingTranscriptions.delete(requestId);
        reject(new Error("transcription timed out"));
      }, timeoutMs);
      this.pendingTranscriptions.set(requestId, { resolve, reject, timer });
      this.queueSend({
        type: "transcribe_audio",
        request_id: requestId,
        data_url: dataUrl,
        ...(options?.durationMs !== undefined ? { duration_ms: options.durationMs } : {}),
      });
    });
  }

  /** Start a realtime PCM transcription session for one push-to-talk turn. */
  startVoice(chatId: string, timeoutMs: number = 15_000): Promise<string> {
    const sessionId = crypto.randomUUID();
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingVoiceStarts.delete(sessionId);
        reject(new Error("voice_connection_timeout"));
      }, timeoutMs);
      this.pendingVoiceStarts.set(sessionId, {
        resolve: () => resolve(sessionId), reject, timer,
      });
      this.queueSend({ type: "voice_start", chat_id: chatId, voice_session_id: sessionId });
    });
  }

  sendVoiceAudio(chatId: string, sessionId: string, audio: string): void {
    this.queueSend({ type: "voice_audio", chat_id: chatId, voice_session_id: sessionId, audio });
  }

  /** Cancel the active agent turn without adding a user chat message. */
  cancel(chatId: string): void {
    this.queueSend({ type: "cancel", chat_id: chatId });
  }

  stopVoice(chatId: string, sessionId: string, timeoutMs: number = 30_000): Promise<string> {
    const earlyFinal = this.earlyVoiceFinals.get(sessionId);
    if (earlyFinal !== undefined) {
      this.earlyVoiceFinals.delete(sessionId);
      this.earlyVoiceErrors.delete(sessionId);
      // Still terminate the provider session; the result itself is already
      // available so the UI must not wait for a duplicate final frame.
      this.queueSend({ type: "voice_stop", chat_id: chatId, voice_session_id: sessionId });
      return Promise.resolve(earlyFinal);
    }
    const earlyError = this.earlyVoiceErrors.get(sessionId);
    if (earlyError !== undefined) {
      this.earlyVoiceErrors.delete(sessionId);
      return Promise.reject(new Error(earlyError));
    }
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingVoiceFinals.delete(sessionId);
        reject(new Error("voice_transcription_timeout"));
      }, timeoutMs);
      this.pendingVoiceFinals.set(sessionId, { resolve, reject, timer });
      this.queueSend({ type: "voice_stop", chat_id: chatId, voice_session_id: sessionId });
    });
  }

  cancelVoice(chatId: string, sessionId: string): void {
    this.rejectVoice(sessionId, "voice_cancelled");
    this.earlyVoiceFinals.delete(sessionId);
    this.earlyVoiceErrors.delete(sessionId);
    this.queueSend({ type: "voice_cancel", chat_id: chatId, voice_session_id: sessionId });
  }

  cancelSpeech(chatId: string): void {
    this.queueSend({ type: "tts_cancel", chat_id: chatId });
  }

  /** Ask the server to create a non-destructive fork before a user-message index. */
  forkChat(
    sourceChatId: string,
    beforeUserIndex: number,
    title?: string,
    timeoutMs: number = 5_000,
  ): Promise<string> {
    if (this.pendingNewChat) {
      return Promise.reject(new Error("newChat already in flight"));
    }
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingNewChat = null;
        reject(new Error("forkChat timed out"));
      }, timeoutMs);
      this.pendingNewChat = { resolve, reject, timer };
      this.queueSend({
        type: "fork_chat",
        source_chat_id: sourceChatId,
        before_user_index: beforeUserIndex,
        ...(title?.trim() ? { title: title.trim() } : {}),
      });
    });
  }

  attach(chatId: string): void {
    this.knownChats.add(chatId);
    if (this.socket?.readyState === WS_OPEN) {
      this.queueSend({ type: "attach", chat_id: chatId });
    }
  }

  sendMessage(
    chatId: string,
    content: string,
    media?: OutboundMedia[],
    options?: {
      imageGeneration?: OutboundImageGeneration;
      cliApps?: OutboundCliAppMention[];
      mcpPresets?: OutboundMcpPresetMention[];
      workspaceScope?: WorkspaceScopePayload | null;
      turnId?: string;
    },
  ): void {
    this.knownChats.add(chatId);
    const frame: Outbound = {
      type: "message",
      chat_id: chatId,
      content,
      ...(media && media.length > 0 ? { media } : {}),
      ...(options?.imageGeneration ? { image_generation: options.imageGeneration } : {}),
      ...(options?.cliApps?.length ? { cli_apps: options.cliApps } : {}),
      ...(options?.mcpPresets?.length ? { mcp_presets: options.mcpPresets } : {}),
      ...(options?.workspaceScope ? { workspace_scope: options.workspaceScope } : {}),
      ...(options?.turnId ? { turn_id: options.turnId } : {}),
      webui: true,
    };
    this.queueSend(frame);
  }

  setWorkspaceScope(chatId: string, workspaceScope: WorkspaceScopePayload): void {
    this.knownChats.add(chatId);
    this.queueSend({
      type: "set_workspace_scope",
      chat_id: chatId,
      workspace_scope: workspaceScope,
    });
  }

  // -- internals ---------------------------------------------------------

  private setStatus(status: ConnectionStatus): void {
    if (this.status_ === status) return;
    this.status_ = status;
    for (const handler of this.statusHandlers) handler(status);
  }

  private clearRunStatusesForReconnect(): void {
    if (this.runStartedAtByChatId.size === 0) return;
    const chatIds = [...this.runStartedAtByChatId.keys()];
    this.runStartedAtByChatId.clear();
    for (const chatId of chatIds) this.emitRunStatus(chatId, null);
  }

  private handleOpen(): void {
    this.setStatus("open");
    this.reconnectAttempts = 0;
    // Slice ②: send ``{type:"auth"}`` as the FIRST frame on every connection.
    // The server (B4) replies ``auth_ok`` or rejects + closes 1008. Business
    // frames (attach / new_chat / message) are deferred to ``handleMessage``'s
    // ``auth_ok`` branch so they never beat auth onto the wire.
    this.authed = false;
    this.authPending = true;
    this.rawSend({ type: "auth", user_token: this.authToken ?? "" });
  }

  private handleMessage(ev: MessageEvent): void {
    let parsed: InboundEvent;
    try {
      parsed = JSON.parse(typeof ev.data === "string" ? ev.data : "") as InboundEvent;
    } catch {
      if (wsInboundDebugEnabled()) {
        const raw = typeof ev.data === "string" ? ev.data : String(ev.data);
        console.warn(
          "[nanobot ws inbound] invalid JSON",
          raw.length > 400 ? `${raw.slice(0, 400)}… (${raw.length} chars)` : raw,
        );
      }
      return;
    }

    if (wsInboundDebugEnabled()) {
      console.log("[nanobot ws inbound]", summarizeInboundWsPayload(parsed));
    }

    if (parsed.event === "ready") {
      // B4: ``ready`` no longer carries ``chat_id`` — clients must obtain a
      // chat via ``new_chat`` after auth. Legacy servers may still send one;
      // we ignore it so ``defaultChatId`` only becomes non-null once the user
      // actually creates/attaches a chat.
      return;
    }

    if (parsed.event === "auth_ok") {
      // Slice ②: server accepted our first-frame auth. It's now safe to
      // re-attach every known chat and flush the business frames that were
      // buffered while we waited.
      this.authed = true;
      this.authPending = false;
      for (const chatId of this.knownChats) {
        this.rawSend({ type: "attach", chat_id: chatId });
      }
      const queued = this.sendQueue.splice(0);
      for (const frame of queued) {
        this.rawSend(frame);
      }
      return;
    }

    if (parsed.event === "attached") {
      this.knownChats.add(parsed.chat_id);
      if (this.pendingNewChat) {
        clearTimeout(this.pendingNewChat.timer);
        this.pendingNewChat.resolve(parsed.chat_id);
        this.pendingNewChat = null;
      }
      this.dispatch(parsed.chat_id, parsed);
      return;
    }

    if (parsed.event === "runtime_model_updated") {
      this.emitRuntimeModelUpdate(parsed.model_name || null, parsed.model_preset ?? null);
      return;
    }

    if (parsed.event === "transcription_result") {
      this.resolveTranscription(parsed.request_id, parsed.text);
      return;
    }

    if (parsed.event === "transcription_error") {
      this.rejectTranscription(parsed.request_id, parsed.detail || "error");
      return;
    }

    if (parsed.event === "cancelled") {
      return;
    }

    if (parsed.event === "voice_started") {
      const pending = this.pendingVoiceStarts.get(parsed.voice_session_id);
      if (pending) {
        clearTimeout(pending.timer);
        this.pendingVoiceStarts.delete(parsed.voice_session_id);
        pending.resolve();
      }
      return;
    }

    if (parsed.event === "voice_final") {
      const pending = this.pendingVoiceFinals.get(parsed.voice_session_id);
      if (pending) {
        clearTimeout(pending.timer);
        this.pendingVoiceFinals.delete(parsed.voice_session_id);
        pending.resolve(parsed.text);
      } else {
        this.rememberEarlyVoiceFinal(parsed.voice_session_id, parsed.text);
      }
      return;
    }

    if (parsed.event === "voice_error") {
      if (parsed.voice_session_id) {
        const detail = parsed.detail || "voice_error";
        if (!this.rejectVoice(parsed.voice_session_id, detail)) {
          this.rememberEarlyVoiceError(parsed.voice_session_id, detail);
        }
      }
      return;
    }

    if (parsed.event === "session_updated") {
      this.emitSessionUpdate(parsed.chat_id, parsed.scope, parsed.workspace_scope);
      return;
    }

    if (parsed.event === "error" && parsed.detail === "workspace_scope_rejected") {
      this.emitError({
        kind: "workspace_scope_rejected",
        reason: parsed.reason,
        chatId: parsed.chat_id,
      });
      if (this.pendingNewChat) {
        clearTimeout(this.pendingNewChat.timer);
        this.pendingNewChat.reject(new Error(`workspace_scope_rejected:${parsed.reason || ""}`));
        this.pendingNewChat = null;
      }
    }

    if (parsed.event === "error" && this.pendingNewChat) {
      clearTimeout(this.pendingNewChat.timer);
      const detail = typeof parsed.detail === "string" ? parsed.detail : "server error";
      const reason = typeof parsed.reason === "string" && parsed.reason ? `:${parsed.reason}` : "";
      this.pendingNewChat.reject(new Error(`${detail}${reason}`));
      this.pendingNewChat = null;
    }

    const chatId = (parsed as { chat_id?: string }).chat_id;
    if (chatId) {
      this.recordGoalStatusForRunStrip(chatId, parsed);
      this.recordGoalStateSnapshot(chatId, parsed);
      this.dispatch(chatId, parsed);
    }
  }

  private emitRuntimeModelUpdate(modelName: string | null, modelPreset?: string | null): void {
    for (const handler of this.runtimeModelHandlers) {
      handler(modelName, modelPreset);
    }
  }

  private emitSessionUpdate(
    chatId: string,
    scope?: SessionUpdateScope,
    workspaceScope?: WorkspaceScopePayload,
  ): void {
    for (const handler of this.sessionUpdateHandlers) {
      handler(chatId, scope, workspaceScope);
    }
  }

  private emitRunStatus(chatId: string, startedAt: number | null): void {
    for (const handler of this.runStatusHandlers) {
      handler(chatId, startedAt);
    }
  }

  private dispatch(chatId: string, ev: InboundEvent): void {
    const handlers = this.chatHandlers.get(chatId);
    if (handlers !== undefined && handlers.size > 0) {
      for (const h of handlers) {
        h(ev);
      }
      return;
    }
    let q = this.pendingInboundByChat.get(chatId);
    if (!q) {
      q = [];
      this.pendingInboundByChat.set(chatId, q);
    }
    q.push(ev);
    const over = q.length - NanobotClient.PENDING_INBOUND_MAX;
    if (over > 0) {
      q.splice(0, over);
    }
  }

  private handleClose(event?: { code?: number }): void {
    this.socket = null;
    if (this.pendingNewChat) {
      clearTimeout(this.pendingNewChat.timer);
      this.pendingNewChat.reject(new Error("socket closed"));
      this.pendingNewChat = null;
    }
    this.rejectAllTranscriptions("socket closed");
    this.rejectAllVoice("socket closed");
    // Surface structured reasons *before* reconnect logic so the UI can
    // display the error even while the client transparently reconnects.
    // Browsers populate ``CloseEvent.code`` with the wire-level close code;
    // 1009 = Message Too Big (server's max frame guard).
    if (event?.code === 1009) {
      this.emitError({ kind: "message_too_big" });
    }
    // Slice ②: a 1008 (policy) close while we're still pending auth means the
    // server rejected our ``auth`` frame. Fire ``onAuthFailed`` once and do NOT
    // schedule a reconnect — the app should bounce to login, not loop forever
    // against a token the server just refused. This must run BEFORE the
    // intentional/reconnect-capable check below.
    if (!this.authed && event?.code === 1008) {
      this.authPending = false;
      this.onAuthFailed?.();
      this.setStatus("closed");
      return;
    }
    if (this.intentionallyClosed || !this.shouldReconnect) {
      this.setStatus("closed");
      return;
    }
    this.scheduleReconnect();
  }

  private emitError(error: StreamError): void {
    // Isolate subscribers so a throwing handler cannot abort the surrounding
    // ``handleClose`` flow (which still owes us a reconnect decision + status
    // update). We deliberately swallow here: error reporting is best-effort
    // and must never be allowed to compound the failure it's reporting.
    for (const handler of this.errorHandlers) {
      try {
        handler(error);
      } catch {
        // best-effort: subscriber fault must not stall transport bookkeeping
      }
    }
  }

  private resolveTranscription(requestId: string, text: string): void {
    const pending = this.pendingTranscriptions.get(requestId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingTranscriptions.delete(requestId);
    pending.resolve(text);
  }

  private rejectTranscription(requestId: string | undefined, detail: string): void {
    if (!requestId) {
      this.rejectAllTranscriptions(detail);
      return;
    }
    const pending = this.pendingTranscriptions.get(requestId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingTranscriptions.delete(requestId);
    pending.reject(new Error(detail));
  }

  private rejectAllTranscriptions(detail: string): void {
    for (const [requestId, pending] of this.pendingTranscriptions) {
      clearTimeout(pending.timer);
      pending.reject(new Error(detail));
      this.pendingTranscriptions.delete(requestId);
    }
  }

  private rejectVoice(sessionId: string, detail: string): boolean {
    let rejected = false;
    const start = this.pendingVoiceStarts.get(sessionId);
    if (start) {
      clearTimeout(start.timer);
      this.pendingVoiceStarts.delete(sessionId);
      start.reject(new Error(detail));
      rejected = true;
    }
    const final = this.pendingVoiceFinals.get(sessionId);
    if (final) {
      clearTimeout(final.timer);
      this.pendingVoiceFinals.delete(sessionId);
      final.reject(new Error(detail));
      rejected = true;
    }
    return rejected;
  }

  private rejectAllVoice(detail: string): void {
    for (const sessionId of new Set([...this.pendingVoiceStarts.keys(), ...this.pendingVoiceFinals.keys()])) {
      this.rejectVoice(sessionId, detail);
    }
    this.earlyVoiceFinals.clear();
    this.earlyVoiceErrors.clear();
  }

  private rememberEarlyVoiceFinal(sessionId: string, text: string): void {
    this.earlyVoiceErrors.delete(sessionId);
    this.earlyVoiceFinals.set(sessionId, text);
    this.trimEarlyVoiceResults();
  }

  private rememberEarlyVoiceError(sessionId: string, detail: string): void {
    if (this.earlyVoiceFinals.has(sessionId)) return;
    this.earlyVoiceErrors.set(sessionId, detail);
    this.trimEarlyVoiceResults();
  }

  private trimEarlyVoiceResults(): void {
    const maxEntries = 32;
    while (this.earlyVoiceFinals.size > maxEntries) {
      const oldest = this.earlyVoiceFinals.keys().next().value;
      if (oldest === undefined) break;
      this.earlyVoiceFinals.delete(oldest);
    }
    while (this.earlyVoiceErrors.size > maxEntries) {
      const oldest = this.earlyVoiceErrors.keys().next().value;
      if (oldest === undefined) break;
      this.earlyVoiceErrors.delete(oldest);
    }
  }

  private scheduleReconnect(): void {
    this.clearRunStatusesForReconnect();
    this.setStatus("reconnecting");
    const attempt = this.reconnectAttempts++;
    // Exponential backoff: 0.5s, 1s, 2s, 4s, capped.
    const delay = Math.min(500 * 2 ** attempt, this.maxBackoffMs);
    this.reconnectTimer = setTimeout(async () => {
      this.reconnectTimer = null;
      if (this.options.onReauth) {
        try {
          const refreshed = await this.options.onReauth();
          if (refreshed) this.currentUrl = refreshed;
        } catch {
          // fall through to retry with current URL
        }
      }
      this.connect();
    }, delay);
  }

  private queueSend(frame: Outbound): void {
    // Buffer until the socket is OPEN AND the server has acknowledged our
    // first-frame auth (slice ②). Sending a business frame before ``auth_ok``
    // would trip the server's auth gate (close 1008 → ``auth_required``).
    if (this.socket?.readyState === WS_OPEN && this.authed && !this.authPending) {
      this.rawSend(frame);
    } else {
      this.sendQueue.push(frame);
    }
  }

  private rawSend(frame: Outbound): void {
    if (!this.socket) return;
    try {
      this.socket.send(JSON.stringify(frame));
    } catch {
      // Send failure will materialize as a close; queue the frame for retry.
      this.sendQueue.push(frame);
    }
  }
}
