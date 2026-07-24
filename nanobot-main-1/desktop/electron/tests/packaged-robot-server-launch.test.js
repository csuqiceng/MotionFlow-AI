"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const mainSource = fs.readFileSync(path.join(__dirname, "..", "main.ts"), "utf8");

assert.match(
  mainSource,
  /supervisor = new RobotServerSupervisor\(\{ exe: resolveRobotServerExe\(\), args: serverArgs, env,/,
  "The packaged launcher must invoke robot_server.exe with the selected single port.",
);
assert.doesNotMatch(mainSource, /NANOBOT_RUNTIME_CHANNEL_PORT|NANOBOT_RUNTIME_GATEWAY_PORT/);
assert.match(mainSource, /Menu\.setApplicationMenu\(null\)/);
assert.doesNotMatch(mainSource, /Menu\.buildFromTemplate/);
assert.doesNotMatch(mainSource, /desktop:menu-action/);
assert.match(mainSource, /robot-arm-app-icon\.ico/);
assert.match(mainSource, /icon: APP_ICON_PATH/);
console.log("packaged robot-server launch argument test passed.");
