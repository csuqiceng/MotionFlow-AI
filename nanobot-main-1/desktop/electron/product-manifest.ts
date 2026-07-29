import * as path from "node:path";
import * as fs from "node:fs";

export interface ProductManifestContext {
  appData: string;
  execPath: string;
  resourcesPath: string;
  appPath: string;
  isDev: boolean;
  argv: string[];
  devPython?: string;
  portableMarkerPresent?: boolean;
}

export interface RobotProductDefaults {
  backendMode: string;
  controllerHost: string;
  executionMode: string;
  firstTestMaxDelta: string;
  firstTestMaxPercent: string;
  vendorWrapperFile: string;
}

export interface ProductWizardData {
  controllerHost: string;
  backendMode: string;
  dllWrapper: string;
  dllDir: string;
}

export interface ProductManifest {
  context: ProductManifestContext;
  id: string;
  displayName: string;
  healthPath: string;
  robotDefaults: RobotProductDefaults;
  resolveDataDir(): string;
  resolveUiUrl(port: number): string;
  resolveConfigTemplatePath(): string;
  resolveRobotSeedDir(): string;
  resolveDefaultsDir(): string;
  resolveVendorDir(): string;
  resolveIconPath(): string;
  serverCommand(port: number, configPath: string): { exe: string; args: string[] };
  environmentForWizard(data: ProductWizardData): Record<string, string>;
  prepareRuntime(configPath: string, envPath: string): void;
  serverEnvironment(
    dataDir: string, port: number, persisted: Record<string, string>,
    initialSeed: boolean,
  ): NodeJS.ProcessEnv;
}

/** Current MotionFlow product wiring; the Electron shell consumes this contract. */
export function motionFlowManifest(context: ProductManifestContext): ProductManifest {
  const id = "motionflow-ai";
  return {
    context,
    id,
    displayName: "MotionFlow AI",
    healthPath: "/health",
    robotDefaults: {
      backendMode: "zmotion_readonly",
      controllerHost: "10.168.3.21",
      executionMode: "auto_after_safety_check",
      firstTestMaxDelta: "2000",
      firstTestMaxPercent: "100",
      vendorWrapperFile: "zauxdllPython.py",
    },
    resolveDataDir() {
      const portable = context.argv.includes("--portable") || context.portableMarkerPresent === true;
      return portable
        ? path.join(path.dirname(context.execPath), "data", "nanobot")
        : path.join(context.appData, id, "runtime");
    },
    resolveUiUrl(port) {
      return `http://127.0.0.1:${port}/`;
    },
    resolveConfigTemplatePath() {
      return context.isDev
        ? path.join(context.appPath, "electron", "config.default.template.json")
        : path.join(context.appPath, "electron", "default-config.json");
    },
    resolveRobotSeedDir() {
      return context.isDev
        ? path.join(context.appPath, "electron", "defaults", "robot_ai")
        : path.join(context.resourcesPath, "defaults", "robot_platform");
    },
    resolveDefaultsDir() {
      return context.isDev
        ? path.join(context.appPath, "electron", "defaults")
        : path.join(context.resourcesPath, "defaults");
    },
    resolveVendorDir() {
      return context.isDev
        ? path.join(context.appPath, "vendor", "zmotion")
        : path.join(context.resourcesPath, "vendor", "zmotion");
    },
    resolveIconPath() {
      return path.join(context.appPath, "electron", "assets", "robot-arm-app-icon.ico");
    },
    serverCommand(port, configPath) {
      const args = ["--port", String(port), "--config", configPath];
      if (context.isDev) {
        return {
          exe: context.devPython ?? path.join(context.appPath, ".build-venv", "Scripts", "python.exe"),
          args: ["-m", "robot_server.cli", ...args],
        };
      }
      return { exe: path.join(context.resourcesPath, "py-runtime", "robot_server.exe"), args };
    },
    environmentForWizard(data) {
      const env: Record<string, string> = {
        ROBOT_AI_BACKEND: data.backendMode || this.robotDefaults.backendMode,
        ROBOT_CONTROLLER_HOST: data.controllerHost || this.robotDefaults.controllerHost,
      };
      if (data.dllWrapper) env.ROBOT_ZMOTION_WRAPPER_PATH = data.dllWrapper;
      if (data.dllDir) env.ROBOT_ZMOTION_DLL_DIR = data.dllDir;
      return env;
    },
    prepareRuntime(configPath, envPath) {
      if (!fs.existsSync(configPath)) {
        const template = this.resolveConfigTemplatePath();
        if (fs.existsSync(template)) {
          fs.mkdirSync(path.dirname(configPath), { recursive: true });
          fs.copyFileSync(template, configPath);
        }
      }
      const robotSeedDir = this.resolveRobotSeedDir();
      const robotDataDir = path.join(path.dirname(configPath), "robot_platform");
      const legacyRobotDataDir = path.join(path.dirname(configPath), "robot_ai");
      if (!fs.existsSync(robotDataDir) && !fs.existsSync(legacyRobotDataDir)
          && fs.existsSync(robotSeedDir)) {
        fs.cpSync(robotSeedDir, robotDataDir, { recursive: true, errorOnExist: true });
      }
      syncPackagedLibraryDefaults(robotDataDir, robotSeedDir);
      if (!fs.existsSync(envPath)) {
        const vendorDir = this.resolveVendorDir();
        const env = {
          ROBOT_AI_BACKEND: this.robotDefaults.backendMode,
          ROBOT_CONTROLLER_HOST: this.robotDefaults.controllerHost,
          ROBOT_ZMOTION_WRAPPER_PATH: path.join(
            vendorDir, this.robotDefaults.vendorWrapperFile,
          ),
          ROBOT_ZMOTION_DLL_DIR: vendorDir,
          ROBOT_AI_FIRST_TEST_MAX_DELTA: this.robotDefaults.firstTestMaxDelta,
          ROBOT_AI_FIRST_TEST_MAX_PERCENT: this.robotDefaults.firstTestMaxPercent,
        };
        fs.mkdirSync(path.dirname(envPath), { recursive: true });
        fs.writeFileSync(envPath, JSON.stringify(env, null, 2), "utf8");
      }
      ensureExecutionConfig(configPath, this.robotDefaults.executionMode);
      ensureProductProfile(robotDataDir, this.robotDefaults.backendMode);
    },
    serverEnvironment(dataDir, port, persisted, initialSeed) {
      return {
        PYTHONUNBUFFERED: "1",
        PYTHONIOENCODING: "utf-8",
        ROBOT_AI_BACKEND: persisted.ROBOT_AI_BACKEND ?? this.robotDefaults.backendMode,
        ...persisted,
        NANOBOT_HOME: dataDir,
        ROBOT_PLATFORM_DATA_DIR: path.join(dataDir, "robot_platform"),
        NANOBOT_DEFAULTS_DIR: this.resolveDefaultsDir(),
        NANOBOT_INITIAL_SEED: initialSeed ? "1" : "0",
        ROBOT_SERVER_PORT: String(port),
      };
    },
  };
}

export function loadProductManifest(context: ProductManifestContext): ProductManifest {
  const productId = process.env.MOTIONFLOW_PRODUCT_ID ?? "motionflow-ai";
  const factories: Record<string, (value: ProductManifestContext) => ProductManifest> = {
    "motionflow-ai": motionFlowManifest,
  };
  const factory = factories[productId];
  if (!factory) throw new Error(`Unknown desktop product manifest: ${productId}`);
  return factory(context);
}

function syncPackagedLibraryDefaults(robotDataDir: string, robotSeedDir: string): void {
  const onlySeed = (filePath: string, collection: "commands" | "flows") => {
    try {
      const payload = JSON.parse(fs.readFileSync(filePath, "utf8")) as Record<string, unknown>;
      const entities = payload[collection];
      if (!entities || typeof entities !== "object" || Array.isArray(entities)) return false;
      const rows = Object.values(entities as Record<string, Record<string, unknown>>);
      return rows.length > 0 && rows.every((entity) => {
        const version = entity.versions && typeof entity.versions === "object"
          ? (entity.versions as Record<string, Record<string, unknown>>)[String(entity.published_version)]
          : undefined;
        return version?.source === "desktop-default";
      });
    } catch { return false; }
  };
  const flowsPath = path.join(robotDataDir, "flows.json");
  const commandsPath = path.join(robotDataDir, "commands.json");
  const configuredFlows = path.join(robotSeedDir, "flows.json");
  if (onlySeed(flowsPath, "flows") && fs.existsSync(configuredFlows)) {
    fs.copyFileSync(configuredFlows, flowsPath);
  }
  if (onlySeed(commandsPath, "commands")) fs.rmSync(commandsPath);
}

function ensureExecutionConfig(configPath: string, executionMode: string): void {
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8")) as Record<string, unknown>;
    const tools = config.tools && typeof config.tools === "object" && !Array.isArray(config.tools)
      ? config.tools as Record<string, unknown> : {};
    if ("execution_mode" in tools || "executionMode" in tools) return;
    tools.execution_mode = executionMode;
    config.tools = tools;
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), "utf8");
  } catch { /* typed server config reports malformed input */ }
}

function ensureProductProfile(robotDataDir: string, backendMode: string): void {
  const profilePath = path.join(robotDataDir, "product_profile.json");
  try {
    const profile = fs.existsSync(profilePath)
      ? JSON.parse(fs.readFileSync(profilePath, "utf8")) as Record<string, unknown> : {};
    if (profile.backend_mode === backendMode) return;
    profile.backend_mode = backendMode;
    fs.mkdirSync(robotDataDir, { recursive: true });
    fs.writeFileSync(profilePath, JSON.stringify(profile, null, 2), "utf8");
  } catch { /* preserve malformed profile as recovery evidence */ }
}
