import type { BootstrapResponse } from "./types";
import { fetchWithTimeout } from "./http";

/**
 * Fetch a short-lived token + the WebSocket path from the gateway's
 * ``/webui/bootstrap`` endpoint.
 */
export async function fetchBootstrap(
  baseUrl: string = "",
  secret: string = "",
  timeoutMs?: number,
): Promise<BootstrapResponse> {
  const headers: Record<string, string> = {};
  if (secret) {
    headers["X-Nanobot-Auth"] = secret;
  }
  const res = await fetchWithTimeout(`${baseUrl}/webui/bootstrap`, {
    method: "GET",
    credentials: "same-origin",
    headers,
  }, timeoutMs);
  if (!res.ok) {
    throw new Error(`bootstrap failed: HTTP ${res.status}`);
  }
  const body = (await res.json()) as BootstrapResponse;
  if (!body.token || !body.ws_path) {
    throw new Error("bootstrap response missing token or ws_path");
  }
  return body;
}

/** Derive a WebSocket URL from the current window location and the server-provided path.
 *
 * Keeps the path segment exactly as the server registered it: the root ``/``
 * stays ``/`` and non-root paths are not given an extra trailing slash. This
 * matters because some WS servers dispatch handshakes based on the literal
 * path, not a normalised form.
 */
export function deriveWsUrl(
  wsPath: string,
  token: string,
  wsUrl?: string | null,
): string {
  const query = `?token=${encodeURIComponent(token)}`;
  const path = wsPath && wsPath.startsWith("/") ? wsPath : `/${wsPath || ""}`;
  if (typeof window !== "undefined" && window.location.port === "5173") {
    const host = window.location.hostname.includes(":")
      ? `[${window.location.hostname}]`
      : window.location.hostname;
    return `ws://${host}:8765${path}${query}`;
  }
  if (wsUrl && /^(wss?|nanobot-host):\/\//i.test(wsUrl)) {
    const join = wsUrl.includes("?") ? "&" : "?";
    return `${wsUrl}${join}token=${encodeURIComponent(token)}`;
  }
  if (typeof window === "undefined") {
    return `ws://127.0.0.1:8765${path}${query}`;
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${scheme}://${host}${path}${query}`;
}

/** Successful login response from ``/api/auth/login``. */
export interface LoginResponse {
  ok: boolean;
  data: {
    user_token: string;
    expires_in: number;
    user: { user_id: string; username: string; role: "operator" | "engineer" };
  };
}

export type LoginPreflightService = {
  state: "healthy" | "unhealthy";
  latency_ms: number;
  reason?: string;
};

export interface LoginPreflightResponse {
  ok: boolean;
  data: {
    controller: LoginPreflightService;
    voice: LoginPreflightService;
    ai: LoginPreflightService;
  };
}

export async function fetchLoginPreflight(
  controllerHost: string,
  wsToken: string,
  baseUrl: string = "",
): Promise<LoginPreflightResponse> {
  const res = await fetchWithTimeout(`${baseUrl}/api/login/preflight`, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Authorization: `Bearer ${wsToken}`,
      "X-Nanobot-Robot-Body": JSON.stringify({ controller_host: controllerHost }),
    },
  }, 15_000);
  if (!res.ok) throw new Error(`login preflight failed: HTTP ${res.status}`);
  return res.json() as Promise<LoginPreflightResponse>;
}

/**
 * Authenticate a user against the gateway's ``/api/auth/login`` endpoint.
 *
 * The gateway's websocket-based HTTP transport is GET-only from the browser,
 * so the credentials are carried in the ``X-Nanobot-Robot-Body`` header —
 * matching the codebase convention used by the robot API routes.
 */
export async function fetchLogin(
  creds: { username: string; password: string; role: "operator" | "engineer" },
  wsToken: string,
  baseUrl: string = "",
  timeoutMs?: number,
): Promise<LoginResponse> {
  const res = await fetchWithTimeout(`${baseUrl}/api/auth/login`, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Authorization: `Bearer ${wsToken}`,
      "X-Nanobot-Robot-Body": JSON.stringify(creds),
    },
  }, timeoutMs);
  if (!res.ok) throw new Error(`login failed: HTTP ${res.status}`);
  const body = await res.json();
  if (!body?.data?.user_token) throw new Error("login response missing user_token");
  return body as LoginResponse;
}

/** Log out by invalidating the user token at ``/api/auth/logout``. */
export async function fetchLogout(wsToken: string, userToken: string, baseUrl: string = ""): Promise<void> {
  const res = await fetchWithTimeout(`${baseUrl}/api/auth/logout`, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Authorization: `Bearer ${wsToken}`,
      "X-Nanobot-User-Token": userToken,
    },
  });
  if (!res.ok) throw new Error(`logout failed: HTTP ${res.status}`);
}
