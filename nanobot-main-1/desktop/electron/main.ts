import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import * as path from "node:path";
import * as fs from "node:fs";
import * as os from "node:os";

import { pickFreePort } from "./port";
import { waitForGateway } from "./health";
import { GatewaySupervisor } from "./gateway-supervisor";

const isDev = !!process.env.ELECTRON_DEV;
const APP_NAME = "nanobot-robot-ai";

// Force a stable, readable user-data dir: %APPDATA%\nanobot-robot-ai on Windows.
// Must run before app.whenReady so all getPath("userData") callers agree.
app.setPath("userData", path.join(app.getPath("appData"), APP_NAME));

let mainWindow: BrowserWindow | null = null;
let supervisor: GatewaySupervisor | null = null;
let quitting = false;
let wizardResolve: (() => void) | null = null;

/** Return the one writable Nanobot data root for this desktop launch. */
function resolveRuntimeDataDir(): string {
  const portable = process.argv.includes("--portable")
    || fs.existsSync(path.join(path.dirname(process.execPath), "portable"));
  return portable
    ? path.join(path.dirname(process.execPath), "data", "nanobot")
    : path.join(app.getPath("userData"), "runtime");
}

interface WizardData {
  provider: string;
  apiKey: string;
  apiBase: string;
  model: string;
  controllerHost: string;
  backendMode: string;
  dllWrapper: string;
  dllDir: string;
}

/** Dev mode: python interpreter that runs the live ``nanobot`` package. */
function resolvePython(): string {
  return (
    process.env.NANOBOT_DEV_PYTHON
    || path.join(app.getAppPath(), ".build-venv", "Scripts", "python.exe")
  );
}

/** Packaged mode: the PyInstaller-built gateway next to the app. */
function resolveGatewayExe(): string {
  return path.join(process.resourcesPath, "py-runtime", "nanobot_gateway.exe");
}

/** True if config.json already has a usable provider+model (skip the wizard).
 *
 * ``agents.defaults.provider`` may be a concrete name OR ``"auto"`` (nanobot
 * then auto-picks among configured providers), so the gate is simply "a model
 * is set AND at least one provider carries an API key".
 */
function hasProviderData(configPath: string): boolean {
  try {
    const cfg = JSON.parse(fs.readFileSync(configPath, "utf8")) as Record<string, any>;
    const model = cfg.agents?.defaults?.model;
    const providers = (cfg.providers ?? {}) as Record<string, any>;
    const anyKey = Object.values(providers).some(
      (p) => p && p.apiKey && p.apiKey !== "__ORGANIZATION_API_KEY__",
    );
    return Boolean(model && anyKey);
  } catch {
    return false;
  }
}

/** Write the wizard submission into config.json + desktop-env.json. */
function writeWizardConfig(configPath: string, envPath: string, data: WizardData): void {
  let cfg: Record<string, any> = {};
  try {
    cfg = JSON.parse(fs.readFileSync(configPath, "utf8")) as Record<string, any>;
  } catch {
    // first run — start from an empty doc
  }
  const providers = cfg.providers ?? {};
  providers[data.provider] = {
    apiType: "auto", // nanobot auto-detects the wire format
    apiKey: data.apiKey,
    ...(data.apiBase ? { apiBase: data.apiBase } : {}),
  };
  cfg.providers = providers;
  const agents = cfg.agents ?? {};
  const defaults = agents.defaults ?? {};
  defaults.provider = data.provider;
  defaults.model = data.model;
  agents.defaults = defaults;
  cfg.agents = agents;

  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf8");

  const env: Record<string, string> = {
    ROBOT_AI_BACKEND: data.backendMode || "simulation",
    ROBOT_CONTROLLER_HOST: data.controllerHost || "10.168.3.21",
  };
  if (data.dllWrapper) env.ROBOT_ZMOTION_WRAPPER_PATH = data.dllWrapper;
  if (data.dllDir) env.ROBOT_ZMOTION_DLL_DIR = data.dllDir;
  fs.writeFileSync(envPath, JSON.stringify(env, null, 2), "utf8");
}

/** Read ROBOT_* env overrides persisted by the wizard (applied on every launch). */
function loadDesktopEnv(envPath: string): Record<string, string> {
  try {
    return JSON.parse(fs.readFileSync(envPath, "utf8")) as Record<string, string>;
  } catch {
    return {};
  }
}

/**
 * First-run seeding for an "appliance" build: if no user config/env exists yet,
 * copy a pre-set config (provider + API key + model) from the bundle and generate
 * a desktop-env.json that points at the bundled ZMotion SDK. This makes the app
 * boot straight into a working zmotion_readonly setup — no wizard — on a fresh
 * machine. Safe no-op on later launches (files already exist).
 */
function seedFirstRunConfig(configPath: string, envPath: string): void {
  if (!fs.existsSync(configPath)) {
    const tmpl = isDev
      ? path.join(app.getAppPath(), "electron", "config.default.template.json")
      : path.join(app.getAppPath(), "electron", "default-config.json");
    if (fs.existsSync(tmpl)) {
      fs.mkdirSync(path.dirname(configPath), { recursive: true });
      fs.copyFileSync(tmpl, configPath);
    }
  }
  const robotSeedDir = isDev
    ? path.join(app.getAppPath(), "electron", "defaults", "robot_ai")
    : path.join(process.resourcesPath, "defaults", "robot_ai");
  const robotDataDir = path.join(path.dirname(configPath), "robot_ai");
  if (!fs.existsSync(robotDataDir) && fs.existsSync(robotSeedDir)) {
    fs.cpSync(robotSeedDir, robotDataDir, { recursive: true, errorOnExist: true });
  }
  if (!fs.existsSync(envPath)) {
    const vendorDir = isDev
      ? path.join(__dirname, "..", "..", "vendor", "zmotion")
      : path.join(process.resourcesPath, "vendor", "zmotion");
    const env = {
      ROBOT_AI_BACKEND: "zmotion_readonly",
      ROBOT_CONTROLLER_HOST: "10.168.3.21",
      ROBOT_ZMOTION_WRAPPER_PATH: path.join(vendorDir, "zauxdllPython.py"),
      ROBOT_ZMOTION_DLL_DIR: vendorDir,
      ROBOT_AI_FIRST_TEST_MAX_DELTA: "2000",
      ROBOT_AI_FIRST_TEST_MAX_PERCENT: "100",
    };
    fs.mkdirSync(path.dirname(envPath), { recursive: true });
    fs.writeFileSync(envPath, JSON.stringify(env, null, 2), "utf8");
  }
}

/**
 * Patch the runtime config so the gateway binds our chosen ports and uses
 * localhost-only bootstrap (no secret). See gateway-port-secret-architecture:
 * the gateway listens on TWO ports — channels.websocket.port (frontend/WS/REST)
 * and gateway.port (health only). We pick both at runtime to avoid collisions
 * with any dev gateway already on 8765. Existing fields are preserved.
 */

/** Show the first-run wizard window; resolves when the user submits (or closes). */
function openFirstRunWizard(): Promise<void> {
  return new Promise((resolve) => {
    wizardResolve = resolve;
    const win = new BrowserWindow({
      width: 640,
      height: 780,
      resizable: false,
      show: true,
      webPreferences: {
        preload: path.join(__dirname, "wizard-preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    win.on("closed", () => {
      // Closed without submitting — resolve so bootstrap can re-check and quit.
      if (wizardResolve) {
        const r = wizardResolve;
        wizardResolve = null;
        r();
      }
    });
    win.loadFile(path.join(__dirname, "..", "electron", "config-wizard", "wizard.html"));
  });
}

async function bootstrap(): Promise<void> {
  const dataDir = resolveRuntimeDataDir();
  const configPath = path.join(dataDir, "config.json");
  const envPath = path.join(dataDir, "desktop-env.json");
  const legacyHome = path.join(os.homedir(), ".nanobot");
  const deferFirstRunToGateway = !fs.existsSync(configPath) && fs.existsSync(legacyHome);
  const initialSeed = !deferFirstRunToGateway && !fs.existsSync(configPath);

  // Appliance mode: seed pre-set config + ZMotion env so the app boots straight
  // into a working setup (no wizard) on a fresh machine.
  if (!deferFirstRunToGateway) seedFirstRunConfig(configPath, envPath);

  if (!deferFirstRunToGateway && !hasProviderData(configPath)) {
    await openFirstRunWizard();
    if (!hasProviderData(configPath)) {
      app.quit(); // user closed the wizard without saving
      return;
    }
  }

  const channelPort = await pickFreePort();
  const healthPort = await pickFreePort();

  const robotEnv = loadDesktopEnv(envPath);
  const defaultsDir = isDev
    ? path.join(app.getAppPath(), "electron", "defaults")
    : path.join(process.resourcesPath, "defaults");
  // Forward EVERY key from desktop-env.json to the gateway subprocess, so the
  // wizard (or manual edits) can set any ROBOT_* / ROBOT_AI_FIRST_TEST_MAX_*
  // value without touching this file. ROBOT_AI_BACKEND keeps a safe default.
  const env: NodeJS.ProcessEnv = {
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
    ROBOT_AI_BACKEND: robotEnv.ROBOT_AI_BACKEND ?? "simulation",
    ...robotEnv,
    // This assignment must remain after desktop-env expansion: that file is
    // allowed to hold ROBOT_* settings, never a second runtime root.
    NANOBOT_HOME: dataDir,
    NANOBOT_DEFAULTS_DIR: defaultsDir,
    NANOBOT_INITIAL_SEED: initialSeed ? "1" : "0",
    // The gateway migrates/adopts data before applying these ephemeral ports.
    // Writing config.json here would turn a legacy migration into a partial config.
    NANOBOT_RUNTIME_CHANNEL_PORT: String(channelPort),
    NANOBOT_RUNTIME_GATEWAY_PORT: String(healthPort),
  };

  // Note: do NOT pass --port; the gateway reads both ports from config
  // (channels.websocket.port = channelPort, gateway.port = healthPort).
  const forwardArgs = ["--config", configPath];
  const gatewayLogFile = path.join(dataDir, "gateway.log");
  const logStream = fs.createWriteStream(gatewayLogFile, { flags: "a" });
  if (isDev) {
    supervisor = new GatewaySupervisor({
      exe: resolvePython(),
      args: ["-m", "nanobot", "gateway", "--foreground", "--verbose", ...forwardArgs],
      env,
      onOutput: (line: string) => logStream.write(line + "\n"),
    });
  } else {
    // The PyInstaller entry already injects `gateway --foreground --verbose`.
    supervisor = new GatewaySupervisor({ exe: resolveGatewayExe(), args: forwardArgs, env,
      onOutput: (line: string) => logStream.write(line + "\n"),
    });
  }

  supervisor.on("crashed", () => {
    if (quitting) return;
    dialog.showErrorBox(
      "Gateway stopped unexpectedly",
      supervisor!.recentOutput.slice(-50).join("\n") || "(no output)",
    );
  });
  supervisor.start();

  try {
    await waitForGateway(channelPort, { timeoutMs: 60_000 });
  } catch (err) {
    dialog.showErrorBox(
      "Gateway failed to start",
      `${String(err)}\n\n--- recent gateway output ---\n${
        supervisor.recentOutput.slice(-50).join("\n") || "(no output)"
      }`,
    );
    app.quit();
    return;
  }

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  await mainWindow.loadURL(`http://127.0.0.1:${channelPort}/`);
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  // Fail-safe: if ready-to-show never fires (slow front-end boot), force-show
  // after 8s so the user isn't left with an invisible window.
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      mainWindow.show();
      mainWindow.focus();
    }
  }, 8000);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// --- single instance: a second launch focuses the existing window ---
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(bootstrap).catch((err) => {
    dialog.showErrorBox("Startup failed", String(err?.stack || err));
    app.quit();
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("before-quit", async (event) => {
    // Tear down the gateway tree (taskkill /T /F on Windows) before exiting.
    // TODO(task4-hardening): Win32 Job Object (KILL_ON_JOB_CLOSE) + bounded
    // auto-restart on "crashed". stop() covers normal exits; the rest deferred.
    if (supervisor && !quitting) {
      quitting = true;
      event.preventDefault();
      await supervisor.stop();
      app.exit(0);
    }
  });
}

// --- IPC (module-level; no single-instance dependency) ---

// First-run wizard.
ipcMain.handle("desktop:submit-wizard-config", async (event, data: WizardData) => {
  try {
    const dataDir = resolveRuntimeDataDir();
    const configPath = path.join(dataDir, "config.json");
    const envPath = path.join(dataDir, "desktop-env.json");
    writeWizardConfig(configPath, envPath, data);
    BrowserWindow.fromWebContents(event.sender)?.close();
    if (wizardResolve) {
      const r = wizardResolve;
      wizardResolve = null;
      r();
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});
ipcMain.handle("desktop:wizard-pick-file", async () => {
  const r = await dialog.showOpenDialog({ properties: ["openFile"] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle("desktop:wizard-pick-folder", async () => {
  const r = await dialog.showOpenDialog({ properties: ["openDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});

// Runtime (exposed to the main webui via preload).
ipcMain.handle("desktop:open-config-dir", () => shell.openPath(resolveRuntimeDataDir()));
ipcMain.handle("desktop:open-logs", () =>
  shell.openPath(path.join(resolveRuntimeDataDir(), "logs")),
);
ipcMain.handle("desktop:get-app-info", () => ({
  version: app.getVersion(),
  dataDir: resolveRuntimeDataDir(),
}));
ipcMain.handle("desktop:restart-gateway", async () => {
  if (!supervisor) return;
  await supervisor.stop();
  supervisor.start();
});
