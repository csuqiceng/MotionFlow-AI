"use strict";

// electron-builder hook. The repository contains only a placeholder template;
// the release pipeline must inject its revocable organization credential into
// the packaged input immediately before files are collected.
const fs = require("node:fs");
const path = require("node:path");

const PLACEHOLDER = "__ORGANIZATION_API_KEY__";

exports.default = async function beforePack(context) {
  const projectDir = context.packager.projectDir;
  const electronDir = path.join(projectDir, "electron");
  const templatePath = path.join(electronDir, "config.default.template.json");
  const outputPath = path.join(electronDir, "default-config.json");

  if (!fs.existsSync(templatePath)) {
    // No template — skip (dev builds may not have it).
    return;
  }

  const template = fs.readFileSync(templatePath, "utf8");
  if (!template.includes(PLACEHOLDER)) {
    throw new Error(
      "Refusing to package a default config without the organization API key placeholder.",
    );
  }
  // Never materialize build-environment credentials into an installer. The
  // per-user first-run wizard writes secrets only to the runtime data root.
  fs.writeFileSync(outputPath, template, "utf8");
};
