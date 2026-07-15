"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { default: beforePack } = require("../before-pack.js");

async function run() {
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), "nanobot-before-pack-"));
  const electronDir = path.join(projectDir, "electron");
  const templatePath = path.join(electronDir, "config.default.template.json");
  const outputPath = path.join(electronDir, "default-config.json");
  const previousKey = process.env.NANOBOT_ORGANIZATION_API_KEY;

  try {
    fs.mkdirSync(electronDir, { recursive: true });
    fs.writeFileSync(templatePath, '{"apiKey":"__ORGANIZATION_API_KEY__"}', "utf8");
    process.env.NANOBOT_ORGANIZATION_API_KEY = "test-embedded-key";

    await beforePack({ packager: { projectDir } });

    assert.equal(fs.readFileSync(outputPath, "utf8"), '{"apiKey":"test-embedded-key"}');
    console.log("before-pack hook test passed.");
  } finally {
    if (previousKey === undefined) {
      delete process.env.NANOBOT_ORGANIZATION_API_KEY;
    } else {
      process.env.NANOBOT_ORGANIZATION_API_KEY = previousKey;
    }
    fs.rmSync(projectDir, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
