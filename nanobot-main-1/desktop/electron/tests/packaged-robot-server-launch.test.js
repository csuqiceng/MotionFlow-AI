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
console.log("packaged robot-server launch argument test passed.");
