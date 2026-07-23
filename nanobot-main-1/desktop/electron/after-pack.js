"use strict";

const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const fs = require("node:fs");
const path = require("node:path");

const execFileAsync = promisify(execFile);

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

  await execFileAsync(resourceEditor, args, { windowsHide: true });
}

exports.default = editWindowsExecutable;
