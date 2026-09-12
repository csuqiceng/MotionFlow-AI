import { describe, expect, it, vi } from "vitest";

import { createTransportClient } from "@/transport/client";
import { parseInboundEvent } from "@/transport/events";

describe("transport client", () => {
  it("uses the configured base URL and injected fetch implementation", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = createTransportClient({
      baseUrl: "http://127.0.0.1:18790/",
      fetchImpl,
    });

    await client.fetchWithTimeout("/api/health", { headers: { Authorization: "Bearer token" } });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:18790/api/health",
      expect.objectContaining({ headers: { Authorization: "Bearer token" } }),
    );
  });

  it("delegates WebSocket creation to the configured factory", () => {
    const socket = {} as WebSocket;
    const webSocketFactory = vi.fn(() => socket);
    const client = createTransportClient({ webSocketFactory });

    expect(client.openWebSocket("ws://127.0.0.1:18790/ws/agent")).toBe(socket);
    expect(webSocketFactory).toHaveBeenCalledWith("ws://127.0.0.1:18790/ws/agent");
  });

  it("rejects malformed WebSocket frames while preserving forward-compatible events", () => {
    expect(parseInboundEvent("not json")).toBeNull();
    expect(parseInboundEvent({ nope: true })).toBeNull();
    expect(parseInboundEvent('{"event":"future_event","feature":"new"}')).toMatchObject({
      event: "future_event",
      feature: "new",
    });
  });
});
