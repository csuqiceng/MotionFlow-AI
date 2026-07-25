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
  const key = process.env.NANOBOT_ORGANIZATION_API_KEY;
  if (!template.includes(PLACEHOLDER)) {
    // Temporary appliance mode: the template already contains an embedded
    // credential, so package it as-is without requiring a build environment.
    fs.writeFileSync(outputPath, template, "utf8");
  } else if (!key || key === PLACEHOLDER) {
    // Dev / local build: use a placeholder API key so the first-run wizard
    // still triggers (hasProviderData returns false for placeholder values).
    fs.writeFileSync(outputPath, template, "utf8");
    console.warn(
      "WARNING: NANOBOT_ORGANIZATION_API_KEY not set — packaged config uses placeholder. " +
      "The first-run wizard will appear on launch.",
    );
  } else {
    fs.writeFileSync(outputPath, template.replaceAll(PLACEHOLDER, key), "utf8");
  }
};
