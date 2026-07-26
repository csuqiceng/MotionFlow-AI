"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const mainSource = fs.readFileSync(path.join(__dirname, "..", "main.ts"), "utf8");

assert.match(
  mainSource,
  /const serverCommand = productManifest\.serverCommand\(serverPort, configPath\);/,
  "The packaged launcher must obtain its command from the ProductManifest.",
);
assert.match(
  mainSource,
  /args: serverCommand\.args,/,
  "The packaged launcher must pass the manifest's selected single-port arguments.",
);
assert.match(
  mainSource,
  /waitForRobotServer\(serverPort, \{ timeoutMs: 60_000, healthPath: productManifest\.healthPath \}\)/,
  "The product health probe must consume the manifest health-path contract.",
);
assert.match(
  mainSource,
  /mainWindow\.loadURL\(productManifest\.resolveUiUrl\(serverPort\)\)/,
  "The product window must consume the manifest UI-source contract.",
);
assert.match(
  fs.readFileSync(path.join(__dirname, "..", "product-manifest.ts"), "utf8"),
  /path\.join\(context\.resourcesPath, "py-runtime", "robot_server\.exe"\)/,
  "The packaged ProductManifest must invoke robot_server.exe from resources/py-runtime.",
);
assert.doesNotMatch(mainSource, /NANOBOT_RUNTIME_CHANNEL_PORT|NANOBOT_RUNTIME_GATEWAY_PORT/);
assert.match(mainSource, /Menu\.setApplicationMenu\(null\)/);
assert.doesNotMatch(mainSource, /Menu\.buildFromTemplate/);
assert.doesNotMatch(mainSource, /desktop:menu-action/);
assert.match(mainSource, /robot-arm-app-icon\.ico/);
assert.match(mainSource, /icon: APP_ICON_PATH/);
console.log("packaged robot-server launch argument test passed.");
