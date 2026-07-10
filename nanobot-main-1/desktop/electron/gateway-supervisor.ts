import { EventEmitter } from "node:events";
import { spawn, type ChildProcess, type SpawnOptions } from "node:child_process";

export interface SupervisorOptions {
  exe: string;
  args: string[];
  env?: NodeJS.ProcessEnv;
  cwd?: string;
  /** Called for each line of stderr (and stdout) output, for logging. */
  onOutput?: (line: string) => void;
}

/**
 * Owns the gateway child process: spawns it, captures output for diagnostics,
 * and tears down the whole process tree on stop.
 *
 * On Windows there is no meaningful SIGTERM, so stop() uses ``taskkill /T /F``
 * which also kills grandchildren (e.g. MCP server subprocesses spawned by the
 * gateway). The Job-Object belt-and-braces (kill-on-close if Electron itself
 * dies) is layered on in task 4.
 *
 * Events:
 *  - ``exit``(code, signal): process ended for any reason.
 *  - ``crashed``(code, signal): process ended on its own (stop() was NOT the
 *    cause) — drive the restart policy from this in main.
 */
export class GatewaySupervisor extends EventEmitter {
  private proc: ChildProcess | null = null;
  private stopping = false;
  private readonly lines: string[] = [];
  private readonly maxLines = 200;

  constructor(private readonly opts: SupervisorOptions) {
    super();
  }

  start(): void {
    this.stopping = false;
    const spawnOpts: SpawnOptions = {
      env: { ...process.env, ...this.opts.env },
      cwd: this.opts.cwd,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    };
    this.proc = spawn(this.opts.exe, this.opts.args, spawnOpts);

    const swallow = (chunk: Buffer): void => {
      for (const line of chunk.toString("utf8").split(/\r?\n/)) {
        if (!line) continue;
        this.lines.push(line);
        if (this.lines.length > this.maxLines) this.lines.shift();
        this.opts.onOutput?.(line);
      }
    };
    this.proc.stderr?.on("data", swallow);
    this.proc.stdout?.on("data", swallow);

    this.proc.on("exit", (code, signal) => {
      const wasStopping = this.stopping;
      this.proc = null;
      this.emit("exit", code, signal);
      if (!wasStopping) this.emit("crashed", code, signal);
    });
    this.proc.on("error", (err) => {
      this.lines.push(`spawn error: ${err.message}`);
      this.emit("crashed", -1, undefined);
    });
  }

  get pid(): number | undefined {
    return this.proc?.pid;
  }

  get recentOutput(): string[] {
    return [...this.lines];
  }

  async stop(timeoutMs = 2000): Promise<void> {
    this.stopping = true;
    const proc = this.proc;
    if (!proc || proc.exitCode !== null) return;
    if (process.platform === "win32" && proc.pid) {
      try {
        await runTaskkill(proc.pid);
      } catch {
        // best effort; process may already be gone
      }
    } else {
      proc.kill("SIGTERM");
      await waitForExit(proc, timeoutMs).catch(() => {
        try {
          proc.kill("SIGKILL");
        } catch {
          /* ignore */
        }
      });
    }
  }
}

function runTaskkill(pid: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const p = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    p.on("exit", () => resolve());
    p.on("error", reject);
  });
}

function waitForExit(proc: ChildProcess, ms: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), ms);
    proc.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}
