import * as http from "node:http";

export interface WaitForGatewayOptions {
  timeoutMs?: number;
  stepMs?: number;
  host?: string;
}

/**
 * Poll the gateway's ``/webui/bootstrap`` endpoint until it is ready.
 *
 * Status mapping:
 *  - 200: ready, no bootstrap secret configured (the default — same-origin
 *    localhost satisfies the localhost-only gate, see ws_http.py).
 *  - 401: the user configured a bootstrap secret; the server is still up.
 *
 * Resolves on the first acceptable status; rejects on timeout so the caller
 * can surface the captured stderr.
 */
export async function waitForGateway(
  port: number,
  opts: WaitForGatewayOptions = {},
): Promise<void> {
  const host = opts.host ?? "127.0.0.1";
  const timeoutMs = opts.timeoutMs ?? 60_000;
  const stepMs = opts.stepMs ?? 250;
  const deadline = Date.now() + timeoutMs;

  for (;;) {
    try {
      const status = await probeBootstrap(host, port);
      if (status === 200 || status === 401) return;
    } catch {
      // gateway not up yet — keep polling
    }
    if (Date.now() >= deadline) {
      throw new Error(`gateway did not become ready within ${timeoutMs}ms`);
    }
    await sleep(stepMs);
  }
}

function probeBootstrap(host: string, port: number): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = http.get(
      { host, port, path: "/webui/bootstrap", timeout: 2000 },
      (res) => {
        res.resume();
        resolve(res.statusCode ?? 0);
      },
    );
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("probe timeout"));
    });
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
