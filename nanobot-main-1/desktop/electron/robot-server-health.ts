import * as http from "node:http";

export interface WaitForRobotServerOptions {
  timeoutMs?: number;
  stepMs?: number;
  host?: string;
  healthPath?: string;
}

/** Poll the single robot-server health endpoint until it is ready. */
export async function waitForRobotServer(port: number, opts: WaitForRobotServerOptions = {}): Promise<void> {
  const host = opts.host ?? "127.0.0.1";
  const healthPath = opts.healthPath ?? "/health";
  const deadline = Date.now() + (opts.timeoutMs ?? 60_000);
  const stepMs = opts.stepMs ?? 250;
  for (;;) {
    try {
      const status = await new Promise<number>((resolve, reject) => {
        const request = http.get({ host, port, path: healthPath, timeout: 2000 }, (response) => { response.resume(); resolve(response.statusCode ?? 0); });
        request.on("error", reject); request.on("timeout", () => { request.destroy(); reject(new Error("probe timeout")); });
      });
      if (status === 200) return;
    } catch { /* service is still starting */ }
    if (Date.now() >= deadline) throw new Error(`robot server did not become ready within ${opts.timeoutMs ?? 60_000}ms`);
    await new Promise((resolve) => setTimeout(resolve, stepMs));
  }
}
