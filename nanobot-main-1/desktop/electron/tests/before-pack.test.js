"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { default: beforePack } = require("../before-pack.js");

const PLACEHOLDER = "__ORGANIZATION_API_KEY__";
const TEST_KEY = "controlled-test-key-never-log";

function templateWith(providers) {
  return JSON.stringify({ providers, tools: { enabled_tools: ["cron"] } });
}

async function run() {
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), "nanobot-before-pack-"));
  const electronDir = path.join(projectDir, "electron");
  const templatePath = path.join(electronDir, "config.default.template.json");
  const outputPath = path.join(electronDir, "default-config.json");
  const previousKey = process.env.NANOBOT_ORGANIZATION_API_KEY;
  const captured = [];
  const originalConsole = { log: console.log, warn: console.warn, error: console.error };

  const invoke = () => beforePack({ packager: { projectDir } });
  const write = (providers) => {
    fs.rmSync(outputPath, { force: true });
    fs.writeFileSync(templatePath, templateWith(providers), "utf8");
  };

  try {
    fs.mkdirSync(electronDir, { recursive: true });
    console.log = console.warn = console.error = (...args) => captured.push(args.map(String).join(" "));

    write({ dashscope: { apiKey: PLACEHOLDER }, empty: { apiKey: null } });
    process.env.NANOBOT_ORGANIZATION_API_KEY = TEST_KEY;
    await invoke();
    const generated = JSON.parse(fs.readFileSync(outputPath, "utf8"));
    assert.equal(generated.providers.dashscope.apiKey, TEST_KEY);
    assert.equal(generated.providers.empty.apiKey, null);

    delete process.env.NANOBOT_ORGANIZATION_API_KEY;
    fs.rmSync(outputPath);
    await assert.rejects(invoke(), /credential is unavailable/);
    assert.equal(fs.existsSync(outputPath), false);

    process.env.NANOBOT_ORGANIZATION_API_KEY = TEST_KEY;
    write({
      dashscope: { apiKey: PLACEHOLDER },
      mixed: { apiKey: TEST_KEY },
    });
    await assert.rejects(invoke(), (error) => {
      captured.push(error instanceof Error ? error.message : String(error));
      return /unexpected provider credential/.test(String(error));
    });

    write({
      dashscope: { apiKey: PLACEHOLDER },
      second: { apiKey: PLACEHOLDER },
    });
    await assert.rejects(invoke(), /unexpected provider credential|exactly one/);

    write({
      dashscope: { apiKey: PLACEHOLDER },
      nested: { credentials: { token: 123 } },
    });
    await assert.rejects(invoke(), /unexpected provider credential/);

    write({ dashscope: { apiKey: `prefix-${PLACEHOLDER}` } });
    await assert.rejects(invoke(), /complete field/);

    fs.rmSync(templatePath);
    fs.rmSync(outputPath, { force: true });
    await assert.rejects(invoke(), /template is missing/);
    assert.equal(fs.existsSync(outputPath), false);

    assert.equal(captured.join("\n").includes(TEST_KEY), false);
  } finally {
    console.log = originalConsole.log;
    console.warn = originalConsole.warn;
    console.error = originalConsole.error;
    if (previousKey === undefined) {
      delete process.env.NANOBOT_ORGANIZATION_API_KEY;
    } else {
      process.env.NANOBOT_ORGANIZATION_API_KEY = previousKey;
    }
    fs.rmSync(projectDir, { recursive: true, force: true });
  }
  console.log("before-pack controlled injection tests passed.");
}

run().catch((error) => {
  console.error(error instanceof Error ? error.message : "before-pack test failed");
  process.exitCode = 1;
});
