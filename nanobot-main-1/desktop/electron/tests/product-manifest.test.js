const assert = require("node:assert/strict");
const path = require("node:path");

const { motionFlowManifest } = require("../../build/product-manifest.js");

const appData = path.join("C:", "Users", "operator", "AppData", "Roaming");
const packaged = motionFlowManifest({
  appData,
  execPath: path.join("C:", "Program Files", "MotionFlow AI", "MotionFlow AI.exe"),
  resourcesPath: path.join("C:", "Program Files", "MotionFlow AI", "resources"),
  appPath: path.join("C:", "Program Files", "MotionFlow AI", "resources", "app.asar"),
  isDev: false,
  argv: [],
});

assert.equal(packaged.id, "motionflow-ai");
assert.equal(packaged.displayName, "MotionFlow AI");
assert.equal(packaged.healthPath, "/health");
assert.equal(packaged.resolveDataDir(), path.join(appData, "motionflow-ai", "runtime"));
assert.equal(packaged.resolveUiUrl(18790), "http://127.0.0.1:18790/");
assert.equal(
  packaged.resolveConfigTemplatePath(),
  path.join("C:", "Program Files", "MotionFlow AI", "resources", "app.asar", "electron", "default-config.json"),
);
assert.equal(
  packaged.resolveRobotSeedDir(),
  path.join("C:", "Program Files", "MotionFlow AI", "resources", "defaults", "robot_platform"),
);
assert.equal(
  packaged.resolveDefaultsDir(),
  path.join("C:", "Program Files", "MotionFlow AI", "resources", "defaults"),
);
assert.equal(
  packaged.resolveVendorDir(),
  path.join("C:", "Program Files", "MotionFlow AI", "resources", "vendor", "zmotion"),
);
assert.deepEqual(packaged.serverCommand(18790, path.join(appData, "motionflow-ai", "runtime", "config.json")), {
  exe: path.join("C:", "Program Files", "MotionFlow AI", "resources", "py-runtime", "robot_server.exe"),
  args: ["--port", "18790", "--config", path.join(appData, "motionflow-ai", "runtime", "config.json")],
});

const portable = motionFlowManifest({ ...packaged.context, argv: ["--portable"] });
assert.equal(portable.resolveDataDir(), path.join("C:", "Program Files", "MotionFlow AI", "data", "nanobot"));

const dev = motionFlowManifest({
  ...packaged.context,
  appPath: path.join("D:", "src", "motionflow"),
  isDev: true,
});
assert.equal(dev.resolveConfigTemplatePath(), path.join("D:", "src", "motionflow", "electron", "config.default.template.json"));
assert.equal(dev.resolveRobotSeedDir(), path.join("D:", "src", "motionflow", "electron", "defaults", "robot_ai"));
assert.equal(dev.resolveDefaultsDir(), path.join("D:", "src", "motionflow", "electron", "defaults"));
assert.equal(dev.resolveVendorDir(), path.join("D:", "src", "motionflow", "vendor", "zmotion"));

console.log("product manifest tests passed");
