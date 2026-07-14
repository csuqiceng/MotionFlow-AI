import { afterEach, describe, expect, it, vi } from "vitest";

import { deriveWsUrl, fetchBootstrap, fetchLoginPreflight } from "@/lib/bootstrap";

describe("bootstrap helpers", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("prefers the server-provided websocket URL over the current dev host", () => {
    expect(deriveWsUrl("/", "tok en", "ws://127.0.0.1:8765/")).toBe(
      "ws://127.0.0.1:8765/?token=tok%20en",
    );
  });

  it("overrides the server-provided websocket URL when on dev server port 5173", () => {
    vi.stubGlobal("window", {
      location: {
        port: "5173",
        hostname: "192.168.1.100",
        protocol: "http:",
      },
    });
    expect(deriveWsUrl("/", "tok", "ws://127.0.0.1:8765/")).toBe(
      "ws://192.168.1.100:8765/?token=tok",
    );
  });

  it("preserves the host socket bridge URL", () => {
    expect(deriveWsUrl("/", "tok en", "nanobot-host://engine/")).toBe(
      "nanobot-host://engine/?token=tok%20en",
    );
  });

  it("falls back to the current window host for legacy bootstrap payloads", () => {
    expect(deriveWsUrl("/", "tok")).toBe(
      "ws://localhost:3000/?token=tok",
    );
  });

  it("times out when the bootstrap endpoint never responds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    const pending = expect(fetchBootstrap("", "", 25)).rejects.toThrow(
      "Request timed out after 25ms",
    );
    await vi.advanceTimersByTimeAsync(25);

    await pending;
  });

  it("allows the AI preflight response window", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    const pending = expect(fetchLoginPreflight("10.168.3.21", "ws-tok")).rejects.toThrow(
      "Request timed out after 15000ms",
    );
    await vi.advanceTimersByTimeAsync(15_000);

    await pending;
  });
});

import { beforeEach } from "vitest";
import { fetchLogin, fetchLogout } from "@/lib/bootstrap";

describe("fetchLogin / fetchLogout", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  it("fetchLogin: GET /api/auth/login with Bearer wsToken + X-Nanobot-Robot-Body", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, data: {
        user_token: "utok", expires_in: 28800,
        user: { user_id: "u1", username: "op", role: "operator" } } }), { status: 200 }),
    );
    const res = await fetchLogin({ username: "op", password: "pw", role: "operator" }, "ws-tok");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Bearer ws-tok",
          "X-Nanobot-Robot-Body": JSON.stringify({ username: "op", password: "pw", role: "operator" }),
        }),
      }),
    );
    expect(res.data.user_token).toBe("utok");
    expect(res.data.user.role).toBe("operator");
  });

  it("fetchLogin: non-2xx throws", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { code: "invalid_credentials" } }), { status: 401 }),
    );
    await expect(fetchLogin({ username: "x", password: "y", role: "engineer" }, "ws"))
      .rejects.toThrow(/401|invalid|login/i);
  });

  it("fetchLogout: GET /api/auth/logout with both tokens", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await fetchLogout("ws-tok", "user-tok");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Bearer ws-tok",
          "X-Nanobot-User-Token": "user-tok",
        }),
      }),
    );
  });
});
