"use strict";

// Electron-builder hook. The repository contains exactly one placeholder; a
// dedicated revocable appliance credential is injected into one exact JSON
// field by the controlled release environment.
const fs = require("node:fs");
const path = require("node:path");

const PLACEHOLDER = "__ORGANIZATION_API_KEY__";
const KEY_ENV = "NANOBOT_ORGANIZATION_API_KEY";
const TARGET_PROVIDER = "dashscope";
const CREDENTIAL_FIELD = /(?:api[_-]?key|authorization|credential|password|secret|token)$/i;

function parseTemplate(template) {
  let config;
  try {
    config = JSON.parse(template);
  } catch {
    throw new Error("Default config template is not valid JSON.");
  }
  if (!config || typeof config !== "object" || Array.isArray(config)
      || !config.providers || typeof config.providers !== "object"
      || Array.isArray(config.providers)) {
    throw new Error("Default config template must contain a providers object.");
  }
  return config;
}

function inspectProviderCredentials(config, phase) {
  let placeholderCount = 0;
  let populatedCredentialCount = 0;
  const visit = (value, fieldPath) => {
    if (typeof value === "string" && value.includes(PLACEHOLDER)) {
      if (value !== PLACEHOLDER) {
        throw new Error(`Provider placeholder must occupy the complete field at ${fieldPath}.`);
      }
      placeholderCount += 1;
      return;
    }
    if (!value || typeof value !== "object") return;
    for (const [key, nested] of Object.entries(value)) {
      const pathLabel = fieldPath ? `${fieldPath}.${key}` : key;
      if (CREDENTIAL_FIELD.test(key)) {
        const isTarget = pathLabel === `providers.${TARGET_PROVIDER}.apiKey`;
        if (nested !== null && nested !== "" && nested !== PLACEHOLDER) {
          populatedCredentialCount += 1;
        }
        if (!isTarget && nested !== null && nested !== "") {
          throw new Error(
            `Refusing unexpected provider credential at ${pathLabel}.`,
          );
        }
      }
      visit(nested, pathLabel);
    }
  };
  visit(config.providers, "providers");
  const target = config.providers[TARGET_PROVIDER];
  if (!target || typeof target !== "object" || Array.isArray(target)) {
    throw new Error("Default config template is missing the controlled provider.");
  }
  if (phase === "template") {
    if (target.apiKey !== PLACEHOLDER || placeholderCount !== 1 || populatedCredentialCount !== 0) {
      throw new Error("Default config must contain exactly one credential placeholder at the controlled provider field.");
    }
  } else if (
    typeof target.apiKey !== "string"
    || target.apiKey.length === 0
    || target.apiKey === PLACEHOLDER
    || placeholderCount !== 0
    || populatedCredentialCount !== 1
  ) {
    throw new Error("Generated config must contain exactly one injected provider credential.");
  }
}

function validateProviderCredentials(template, phase = "template") {
  const config = parseTemplate(template);
  inspectProviderCredentials(config, phase);
  return config;
}

exports.validateProviderCredentials = validateProviderCredentials;

exports.default = async function beforePack(context) {
  const projectDir = context.packager.projectDir;
  const electronDir = path.join(projectDir, "electron");
  const templatePath = path.join(electronDir, "config.default.template.json");
  const outputPath = path.join(electronDir, "default-config.json");

  if (!fs.existsSync(templatePath)) {
    throw new Error("Required default config template is missing.");
  }

  const template = fs.readFileSync(templatePath, "utf8");
  const config = validateProviderCredentials(template, "template");
  const key = process.env[KEY_ENV];
  if (typeof key !== "string" || key.trim().length === 0 || key === PLACEHOLDER) {
    throw new Error("Controlled package credential is unavailable.");
  }
  config.providers[TARGET_PROVIDER].apiKey = key;
  const generated = JSON.stringify(config, null, 2) + "\n";
  validateProviderCredentials(generated, "generated");
  fs.writeFileSync(outputPath, generated, "utf8");
  validateProviderCredentials(fs.readFileSync(outputPath, "utf8"), "generated");
};
