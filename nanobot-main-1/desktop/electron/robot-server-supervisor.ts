import { EventEmitter } from "node:events";
import { spawn, type ChildProcess, type SpawnOptions } from "node:child_process";

export interface RobotServerSupervisorOptions {
  exe: string;
  args: string[];
  env?: NodeJS.ProcessEnv;
  cwd?: string;
  onOutput?: (line: string) => void;
}

/** Own the single robot-server process and terminate its complete process tree. */
export class RobotServerSupervisor extends EventEmitter {
  private proc: ChildProcess | null = null;
  private stopping = false;
  private readonly lines: string[] = [];
  private readonly maxLines = 200;

  constructor(private readonly opts: RobotServerSupervisorOptions) { super(); }

  start(): void {
    this.stopping = false;
    const spawnOpts: SpawnOptions = { env: { ...process.env, ...this.opts.env }, cwd: this.opts.cwd, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] };
    this.proc = spawn(this.opts.exe, this.opts.args, spawnOpts);
    const record = (chunk: Buffer): void => {
      for (const line of chunk.toString("utf8").split(/\r?\n/)) {
        if (!line) continue;
        this.lines.push(line);
        if (this.lines.length > this.maxLines) this.lines.shift();
        this.opts.onOutput?.(line);
      }
    };
    this.proc.stderr?.on("data", record);
    this.proc.stdout?.on("data", record);
    this.proc.on("exit", (code, signal) => {
      const wasStopping = this.stopping;
      this.proc = null;
      this.emit("exit", code, signal);
      if (!wasStopping) this.emit("crashed", code, signal);
    });
    this.proc.on("error", (err) => { this.lines.push(`spawn error: ${err.message}`); this.emit("crashed", -1, undefined); });
  }

  get recentOutput(): string[] { return [...this.lines]; }

  async stop(timeoutMs = 2000): Promise<void> {
    this.stopping = true;
    const proc = this.proc;
    if (!proc || proc.exitCode !== null) return;
    if (process.platform === "win32" && proc.pid) {
      await new Promise<void>((resolve) => {
        const killer = spawn("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
        killer.on("exit", () => resolve()); killer.on("error", () => resolve());
      });
      return;
    }
    proc.kill("SIGTERM");
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => { try { proc.kill("SIGKILL"); } finally { resolve(); } }, timeoutMs);
      proc.once("exit", () => { clearTimeout(timer); resolve(); });
    });
  }
}
