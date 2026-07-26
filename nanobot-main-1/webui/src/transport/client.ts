import {
  DEFAULT_HTTP_TIMEOUT_MS,
  fetchWithTimeout,
  resolveHttpUrl,
  type FetchImplementation,
} from "./http";
import { createWebSocket, type WebSocketFactory } from "./websocket";

export interface TransportClientOptions {
  baseUrl?: string;
  fetchImpl?: FetchImplementation;
  webSocketFactory?: WebSocketFactory;
}

export interface TransportClient {
  fetchWithTimeout(input: RequestInfo | URL, init?: RequestInit, timeoutMs?: number): Promise<Response>;
  openWebSocket(url: string): WebSocket;
}

export function createTransportClient(options: TransportClientOptions = {}): TransportClient {
  const baseUrl = options.baseUrl ?? "";
  return {
    fetchWithTimeout(input, init = {}, timeoutMs = DEFAULT_HTTP_TIMEOUT_MS) {
      return fetchWithTimeout(resolveHttpUrl(input, baseUrl), init, timeoutMs, options.fetchImpl);
    },
    openWebSocket(url) {
      return createWebSocket(url, options.webSocketFactory);
    },
  };
}
