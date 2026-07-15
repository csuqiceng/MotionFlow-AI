"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const mainSource = fs.readFileSync(path.join(__dirname, "..", "main.ts"), "utf8");

assert.match(
  mainSource,
  /supervisor = new GatewaySupervisor\(\{ exe: resolveGatewayExe\(\), args: forwardArgs, env \}\);/,
  "The packaged PyInstaller launcher already injects gateway --foreground --verbose.",
);

console.log("packaged gateway launch argument test passed.");
