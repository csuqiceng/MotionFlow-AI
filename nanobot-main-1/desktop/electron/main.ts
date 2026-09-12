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
import { loadProductManifest } from "./product-manifest";
import {
  hasExactOrigin,
  mayOpenInSystemBrowser,
  trustedLoopbackOrigin,
} from "./trusted-origin-policy";

const isDev = !!process.env.ELECTRON_DEV;
const productManifest = loadProductManifest({
  appData: app.getPath("appData"),
  execPath: process.execPath,
  resourcesPath: process.resourcesPath,
  appPath: app.getAppPath(),
  isDev,
  argv: process.argv,
  devPython: process.env.NANOBOT_DEV_PYTHON,
  portableMarkerPresent: fs.existsSync(path.join(path.dirname(process.execPath), "portable")),
});
const APP_ICON_PATH = productManifest.resolveIconPath();

// Must run before app.whenReady so all getPath("userData") callers agree.
app.setPath("userData", path.join(app.getPath("appData"), productManifest.id));

let mainWindow: BrowserWindow | null = null;
let supervisor: RobotServerSupervisor | null = null;
let quitting = false;
let wizardResolve: (() => void) | null = null;
let trustedRobotUiOrigin: string | null = null;

/**
 * The embedded WebUI is served by the robot server on a loopback URL.  The
 * desktop application is the trusted host for that page, so microphone access
 * can be granted without presenting Chromium's browser-style permission UI.
 *
 * Do not broaden this allow-list: remote pages and camera requests must never
 * inherit this appliance permission.
 */
function configureLocalMicrophonePermission(): void {
  const isTrustedContents = (contents: Electron.WebContents | null): boolean => (
    contents !== null
    && mainWindow !== null
    && contents === mainWindow.webContents
    && !contents.isDestroyed()
    && hasExactOrigin(contents.getURL(), trustedRobotUiOrigin)
  );

  session.defaultSession.setPermissionCheckHandler((contents, permission, requestingOrigin, details) => (
    permission === "media"
    && details.mediaType === "audio"
    && hasExactOrigin(requestingOrigin, trustedRobotUiOrigin)
    && isTrustedContents(contents)
  ));
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    const mediaTypes = "mediaTypes" in details ? details.mediaTypes : undefined;
    callback(
      permission === "media"
      && mediaTypes?.includes("audio") === true
      && !mediaTypes.includes("video")
      && hasExactOrigin(details.requestingUrl, trustedRobotUiOrigin)
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
  return productManifest.resolveDataDir();
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

  const env = productManifest.environmentForWizard(data);
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
 * a desktop-env.json from ProductManifest defaults. This makes the app
 * boot straight into a working product setup — no wizard — on a fresh
 * machine. Safe no-op on later launches (files already exist).
 */
function seedFirstRunConfig(configPath: string, envPath: string): void {
  productManifest.prepareRuntime(configPath, envPath);
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

  // Appliance mode: seed the manifest-selected product defaults so the app boots straight
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

  const env = productManifest.serverEnvironment(
    dataDir, serverPort, loadDesktopEnv(envPath), initialSeed,
  );

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
      `${productManifest.displayName} server stopped unexpectedly`,
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

  const robotUiUrl = productManifest.resolveUiUrl(serverPort);
  trustedRobotUiOrigin = trustedLoopbackOrigin(robotUiUrl);
  if (trustedRobotUiOrigin === null) {
    throw new Error("ProductManifest UI URL must use an explicit loopback HTTP origin.");
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
      sandbox: true,
    },
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (hasExactOrigin(url, trustedRobotUiOrigin)) return;
    event.preventDefault();
    if (mayOpenInSystemBrowser(url)) {
      void shell.openExternal(url).catch(() => undefined);
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!hasExactOrigin(url, trustedRobotUiOrigin) && mayOpenInSystemBrowser(url)) {
      void shell.openExternal(url).catch(() => undefined);
    }
    return { action: "deny" };
  });
  await mainWindow.loadURL(robotUiUrl);
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
    trustedRobotUiOrigin = null;
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
