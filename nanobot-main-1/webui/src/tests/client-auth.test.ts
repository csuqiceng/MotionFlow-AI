import { describe, expect, it, vi } from "vitest";

import { NanobotClient } from "@/lib/nanobot-client";

/**
 * Minimal fake WebSocket implementing the subset NanobotClient touches.
 *
 * Mirrors the FakeSocket in ``nanobot-client.test.ts`` but parses outbound
 * frames into objects so auth-first-frame assertions read cleanly. Used by the
 * slice-② auth-gate tests: every connection must send ``{type:"auth"}`` before
 * any business frame, buffer until ``auth_ok``, and re-send auth on reconnect.
 */
class FakeSocket {
  sent: any[] = [];
  onopen: ((ev: any) => void) | null = null;
  onmessage: ((ev: any) => void) | null = null;
  onclose: ((ev: any) => void) | null = null;
  onerror: ((ev: any) => void) | null = null;
  readyState = 0; // 0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(): void {
    this.readyState = 3;
  }

  /** Simulate the TCP/WS handshake completing. */
  fireOpen(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  /** Push a server frame to the client's onmessage handler. */
  recv(obj: any): void {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
}

describe("NanobotClient auth first-frame", () => {
  it("on open, sends auth {user_token} BEFORE any new_chat/attach", () => {
    const sock = new FakeSocket();
    const client = new NanobotClient({
      url: "ws://x",
      socketFactory: () => sock as unknown as WebSocket,
      reconnect: false,
    });
    client.setAuthToken("user-tok");
    client.connect();
    sock.fireOpen();
    client.newChat(1000); // queued before auth_ok
    expect(sock.sent.map((f) => f.type)).toEqual(["auth"]); // only auth so far
    expect(sock.sent[0]).toEqual({ type: "auth", user_token: "user-tok" });
  });

  it("after auth_ok, flushes buffered business frame (new_chat proceeds)", async () => {
    const sock = new FakeSocket();
    const client = new NanobotClient({
      url: "ws://x",
      socketFactory: () => sock as unknown as WebSocket,
      reconnect: false,
    });
    client.setAuthToken("user-tok");
    client.connect();
    sock.fireOpen();
    const p = client.newChat(1000);
    sock.recv({ event: "auth_ok", role: "operator", user_id: "u1" });
    sock.recv({ event: "attached", chat_id: "c1" });
    await expect(p).resolves.toBe("c1");
    expect(sock.sent.map((f) => f.type)).toEqual(["auth", "new_chat"]);
  });

  it("auth_ok carries no chat_id; defaultChatId stays null until new_chat", () => {
    const sock = new FakeSocket();
    const client = new NanobotClient({
      url: "ws://x",
      socketFactory: () => sock as unknown as WebSocket,
      reconnect: false,
    });
    client.setAuthToken("t");
    client.connect();
    sock.fireOpen();
    sock.recv({ event: "ready", client_id: "c" });
    sock.recv({ event: "auth_ok", role: "engineer", user_id: "u" });
    expect(client.defaultChatId).toBeNull();
  });

  it("server auth_failed → onAuthFailed fires", () => {
    const sock = new FakeSocket();
    const onAuthFailed = vi.fn();
    const client = new NanobotClient({
      url: "ws://x",
      socketFactory: () => sock as unknown as WebSocket,
      reconnect: false,
      onAuthFailed,
    });
    client.setAuthToken("bad");
    client.connect();
    sock.fireOpen();
    sock.recv({ event: "error", detail: "auth_failed" });
    sock.readyState = 3;
    sock.onclose?.({ code: 1008 });
    expect(onAuthFailed).toHaveBeenCalledTimes(1);
  });

  it("reconnect re-sends auth (binding does not persist across connections)", () => {
    const sock1 = new FakeSocket();
    const client = new NanobotClient({
      url: "ws://x",
      socketFactory: () => sock1 as unknown as WebSocket,
      reconnect: false,
    });
    client.setAuthToken("t");
    client.connect();
    sock1.fireOpen();
    sock1.recv({ event: "auth_ok", role: "operator", user_id: "u" });
    // Simulate a reconnect: the old socket drops, then a fresh socket is
    // opened against a new URL. ``connect()`` is a no-op while the prior
    // socket is still OPEN, so we close sock1 first — mirroring a real drop.
    sock1.readyState = 3;
    const sock2 = new FakeSocket();
    client.updateUrl("ws://x2", () => sock2 as unknown as WebSocket);
    client.connect();
    sock2.fireOpen();
    expect(sock2.sent.map((f) => f.type)).toEqual(["auth"]); // first frame is auth again
  });
});
