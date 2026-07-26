export type WebSocketFactory = (url: string) => WebSocket;

function defaultWebSocketFactory(url: string): WebSocket {
  return new WebSocket(url);
}

export function createWebSocket(
  url: string,
  factory: WebSocketFactory = defaultWebSocketFactory,
): WebSocket {
  return factory(url);
}
