import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  session,
  shell,
} from "electron";
import * as path from "node:path";
import * as fs from "node:fs";

import { pickFreePort } from "./port";
import { waitForRobotServer } from "./robot-server-health";
import { RobotServerSupervisor } from "./robot-server-supervisor";
import { motionFlowManifest } from "./product-manifest";

const isDev = !!process.env.ELECTRON_DEV;
const APP_NAME = "motionflow-ai";
// Kept inside the packaged application so the first-run wizard and the main
// control window use the same mechanical-arm icon as the installed .exe.
const APP_ICON_PATH = path.join(__dirname, "..", "electron", "assets", "robot-arm-app-icon.ico");

// Force a stable, readable user-data dir: %APPDATA%\motionflow-ai on Windows.
// Must run before app.whenReady so all getPath("userData") callers agree.
app.setPath("userData", path.join(app.getPath("appData"), APP_NAME));

const productManifest = motionFlowManifest({
  appData: app.getPath("appData"),
  execPath: process.execPath,
  resourcesPath: process.resourcesPath,
  appPath: app.getAppPath(),
  isDev,
  argv: process.argv,
  devPython: process.env.NANOBOT_DEV_PYTHON,
});

let mainWindow: BrowserWindow | null = null;
let supervisor: RobotServerSupervisor | null = null;
let quitting = false;
let wizardResolve: (() => void) | null = null;

/**
 * The embedded WebUI is served by the robot server on a loopback URL.  The
 * desktop application is the trusted host for that page, so microphone access
 * can be granted without presenting Chromium's browser-style permission UI.
 *
 * Do not broaden this allow-list: remote pages and camera requests must never
 * inherit this appliance permission.
 */
function isLocalRobotUiUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:"
      && (url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "::1");
  } catch {
    return false;
  }
}

function configureLocalMicrophonePermission(): void {
  const isTrustedContents = (contents: Electron.WebContents | null): boolean => (
    contents !== null && !contents.isDestroyed() && isLocalRobotUiUrl(contents.getURL())
  );

  session.defaultSession.setPermissionCheckHandler((contents, permission, requestingOrigin, details) => (
    permission === "media"
    && details.mediaType === "audio"
    && isLocalRobotUiUrl(requestingOrigin)
    && isTrustedContents(contents)
  ));
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    const mediaTypes = "mediaTypes" in details ? details.mediaTypes : undefined;
    callback(
      permission === "media"
      && mediaTypes?.includes("audio") === true
      && !mediaTypes.includes("video")
      && isLocalRobotUiUrl(details.requestingUrl)
      && isTrustedContents(contents),
    );
  });
}

async function restartRobotServer(): Promise<void> {
  if (!supervisor) {
    throw new Error("机器人服务尚未启动。");
  }
  await supervisor.stop();
  supervisor.start();
}

/** Return the one writable Nanobot data root for this desktop launch. */
function resolveRuntimeDataDir(): string {
  const portableMarker = fs.existsSync(path.join(path.dirname(process.execPath), "portable"));
  return portableMarker && !process.argv.includes("--portable")
    ? path.join(path.dirname(process.execPath), "data", "nanobot")
    : productManifest.resolveDataDir();
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

/** Packaged mode: the PyInstaller-built robot server next to the app. */
function resolveRobotServerExe(): string {
  return path.join(process.resourcesPath, "py-runtime", "robot_server.exe");
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
    const tmpl = productManifest.resolveConfigTemplatePath();
    if (fs.existsSync(tmpl)) {
      fs.mkdirSync(path.dirname(configPath), { recursive: true });
      fs.copyFileSync(tmpl, configPath);
    }
  }
  const robotSeedDir = productManifest.resolveRobotSeedDir();
  const robotDataDir = path.join(path.dirname(configPath), "robot_platform");
  const legacyRobotDataDir = path.join(path.dirname(configPath), "robot_ai");
  // Do not seed defaults over a pre-existing legacy runtime.  Python's
  // platform migration then copies that data into the canonical directory.
  if (!fs.existsSync(robotDataDir) && !fs.existsSync(legacyRobotDataDir) && fs.existsSync(robotSeedDir)) {
    fs.cpSync(robotSeedDir, robotDataDir, { recursive: true, errorOnExist: true });
  }
  if (!fs.existsSync(envPath)) {
    const vendorDir = productManifest.resolveVendorDir();
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

/** Show the first-run wizard window; resolves when the user submits (or closes). */
function openFirstRunWizard(): Promise<void> {
  return new Promise((resolve) => {
    wizardResolve = resolve;
    const win = new BrowserWindow({
      width: 640,
      height: 780,
      resizable: false,
      show: true,
      icon: APP_ICON_PATH,
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
  const initialSeed = !fs.existsSync(configPath);

  // Appliance mode: seed pre-set config + ZMotion env so the app boots straight
  // into a working setup (no wizard) on a fresh machine.
  seedFirstRunConfig(configPath, envPath);

  if (!hasProviderData(configPath)) {
    await openFirstRunWizard();
    if (!hasProviderData(configPath)) {
      app.quit(); // user closed the wizard without saving
      return;
    }
  }

  const serverPort = await pickFreePort();

  const robotEnv = loadDesktopEnv(envPath);
  const defaultsDir = productManifest.resolveDefaultsDir();
  // Forward EVERY key from desktop-env.json to the robot server subprocess, so the
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
    // The robot library has its own canonical data-root setting.  Keep this
    // after desktop-env expansion too, so a persisted deployment config cannot
    // redirect commands and flows outside the application's runtime directory.
    ROBOT_PLATFORM_DATA_DIR: path.join(dataDir, "robot_platform"),
    NANOBOT_DEFAULTS_DIR: defaultsDir,
    NANOBOT_INITIAL_SEED: initialSeed ? "1" : "0",
    ROBOT_SERVER_PORT: String(serverPort),
  };

  const serverLogFile = path.join(dataDir, "robot-server.log");
  const logStream = fs.createWriteStream(serverLogFile, { flags: "a" });
  const serverCommand = productManifest.serverCommand(serverPort, configPath);
  supervisor = new RobotServerSupervisor({
    exe: serverCommand.exe,
    args: serverCommand.args,
    env,
    onOutput: (line: string) => logStream.write(line + "\n"),
  });

  supervisor.on("crashed", () => {
    if (quitting) return;
    dialog.showErrorBox(
      "Robot server stopped unexpectedly",
      supervisor!.recentOutput.slice(-50).join("\n") || "(no output)",
    );
  });
  supervisor.start();

  try {
    await waitForRobotServer(serverPort, { timeoutMs: 60_000, healthPath: productManifest.healthPath });
  } catch (err) {
    dialog.showErrorBox(
      "Robot server failed to start",
      `${String(err)}\n\n--- recent robot server output ---\n${
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
    icon: APP_ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  await mainWindow.loadURL(productManifest.resolveUiUrl(serverPort));
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

  app.whenReady().then(() => {
    // The product uses its own in-app navigation. Keep the native title bar
    // uncluttered instead of exposing Electron's application menu.
    Menu.setApplicationMenu(null);
    configureLocalMicrophonePermission();
    return bootstrap();
  }).catch((err) => {
    dialog.showErrorBox("Startup failed", String(err?.stack || err));
    app.quit();
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("before-quit", async (event) => {
    // Tear down the robot-server tree (taskkill /T /F on Windows) before exiting.
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
ipcMain.handle("desktop:restart-robot-server", async () => {
  await restartRobotServer();
});
