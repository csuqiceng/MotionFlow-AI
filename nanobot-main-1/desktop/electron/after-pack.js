"use strict";

const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const fs = require("node:fs");
const path = require("node:path");

const execFileAsync = promisify(execFile);
const RESOURCE_EDIT_MAX_ATTEMPTS = 4;

function waitForResourceEditor(delayMs) {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

async function editWindowsExecutable(context) {
  if (process.platform !== "win32") {
    return;
  }

  const projectDir = context.packager.projectDir;
  const appInfo = context.packager.appInfo;
  const resourceEditor = path.join(projectDir, "tools", "rcedit-x64.exe");
  const iconPath = path.join(projectDir, "electron", "assets", "nanobot-app-icon.ico");
  const executable = path.join(context.appOutDir, `${appInfo.productFilename}.exe`);

  for (const requiredPath of [resourceEditor, iconPath, executable]) {
    if (!fs.existsSync(requiredPath)) {
      throw new Error(`Required Windows packaging resource is missing: ${requiredPath}`);
    }
  }

  const version = appInfo.version;
  const args = [
    executable,
    "--set-version-string", "FileDescription", appInfo.productName,
    "--set-version-string", "ProductName", appInfo.productName,
    "--set-version-string", "ProductVersion", version,
    "--set-version-string", "FileVersion", version,
    "--set-version-string", "LegalCopyright", appInfo.copyright || "",
    "--set-version-string", "CompanyName", appInfo.companyName || appInfo.productName,
    "--set-version-string", "LegalTrademarks", "MotionFlow AI",
    "--set-file-version", version,
    "--set-product-version", version,
    "--set-icon", iconPath,
  ];

  // Windows Defender and the shell can briefly retain the freshly copied
  // Electron executable.  rcedit then reports "Unable to commit changes"
  // despite both the executable and icon being valid.  Retry only this
  // transient resource write; the final failure is still surfaced verbatim.
  let lastError;
  for (let attempt = 1; attempt <= RESOURCE_EDIT_MAX_ATTEMPTS; attempt += 1) {
    try {
      await execFileAsync(resourceEditor, args, { windowsHide: true });
      return;
    } catch (error) {
      lastError = error;
      if (attempt < RESOURCE_EDIT_MAX_ATTEMPTS) {
        await waitForResourceEditor(attempt * 750);
      }
    }
  }
  throw lastError;
}

exports.default = editWindowsExecutable;
