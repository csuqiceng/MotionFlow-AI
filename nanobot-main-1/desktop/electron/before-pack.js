"use strict";

// electron-builder hook. The repository contains only a placeholder template;
// the release pipeline must inject its revocable organization credential into
// the packaged input immediately before files are collected.
const fs = require("node:fs");
const path = require("node:path");

const PLACEHOLDER = "__ORGANIZATION_API_KEY__";

exports.default = async function beforePack(context) {
  const projectDir = context.projectDir;
  const electronDir = path.join(projectDir, "electron");
  const templatePath = path.join(electronDir, "config.default.template.json");
  const outputPath = path.join(electronDir, "default-config.json");
  const key = process.env.NANOBOT_ORGANIZATION_API_KEY;

  if (!key || key === PLACEHOLDER) {
    throw new Error(
      "NANOBOT_ORGANIZATION_API_KEY is required for a production desktop package.",
    );
  }
  const template = fs.readFileSync(templatePath, "utf8");
  if (!template.includes(PLACEHOLDER)) {
    throw new Error("The desktop config template does not contain the organization-key placeholder.");
  }
  fs.writeFileSync(outputPath, template.replaceAll(PLACEHOLDER, key), "utf8");
};
