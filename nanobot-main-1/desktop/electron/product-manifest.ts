import * as path from "node:path";

export interface ProductManifestContext {
  appData: string;
  execPath: string;
  resourcesPath: string;
  appPath: string;
  isDev: boolean;
  argv: string[];
  devPython?: string;
}

export interface ProductManifest {
  context: ProductManifestContext;
  id: string;
  displayName: string;
  healthPath: string;
  resolveDataDir(): string;
  resolveUiUrl(port: number): string;
  resolveConfigTemplatePath(): string;
  resolveRobotSeedDir(): string;
  resolveDefaultsDir(): string;
  resolveVendorDir(): string;
  serverCommand(port: number, configPath: string): { exe: string; args: string[] };
}

/** Current MotionFlow product wiring; the Electron shell consumes this contract. */
export function motionFlowManifest(context: ProductManifestContext): ProductManifest {
  const id = "motionflow-ai";
  return {
    context,
    id,
    displayName: "MotionFlow AI",
    healthPath: "/health",
    resolveDataDir() {
      const portable = context.argv.includes("--portable");
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
  };
}
