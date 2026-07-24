$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$package = Get-Content -LiteralPath (Join-Path $desktopDir "package.json") -Raw | ConvertFrom-Json
$builder = Get-Content -LiteralPath (Join-Path $desktopDir "electron-builder.yml") -Raw

if ($package.author.name -ne "MotionFlow AI") {
    throw "package.json must define the Windows company/product author."
}
if ($package.scripts.verifyRelease -ne "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\verify-release.ps1") {
    throw "package.json must expose the release verifier."
}
if ($package.scripts.smokePackagedRobotServer -ne "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\smoke-packaged-robot-server.ps1") {
    throw "package.json must expose the packaged robot-server smoke test."
}
if ($builder -notmatch [regex]::Escape("executableName: MotionFlow AI")) {
    throw "Windows executableName is missing."
}
if ($builder -notmatch [regex]::Escape("icon: electron/assets/nanobot-app-icon.ico")) {
    throw "Windows product icon is missing."
}
$iconMatch = [regex]::Match($builder, "(?m)^\s*icon:\s*(.+?)\s*$")
if (-not $iconMatch.Success) {
    throw "Windows product icon path is missing."
}
$iconRelative = $iconMatch.Groups[1].Value.Trim().Trim('"', "'")
$iconPath = [IO.Path]::GetFullPath((Join-Path $desktopDir $iconRelative))
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Windows product icon does not exist: $iconPath"
}
Add-Type -AssemblyName System.Drawing
$icon = [Drawing.Image]::FromFile($iconPath)
try {
    if ($icon.Width -lt 256 -or $icon.Height -lt 256) {
        throw "Windows product icon must be at least 256x256; got $($icon.Width)x$($icon.Height)."
    }
    if ($icon.Width -ne $icon.Height) {
        throw "Windows product icon must be square; got $($icon.Width)x$($icon.Height)."
    }
}
finally {
    $icon.Dispose()
}
if ($builder -notmatch "target:\s*\r?\n\s+- target: nsis\s*\r?\n\s+arch:\s*\r?\n\s+- x64") {
    throw "The Windows target must explicitly be NSIS x64."
}
if ($builder -notmatch [regex]::Escape("afterPack: electron/after-pack.js")) {
    throw "Windows resource editing must use the local after-pack hook."
}
if ($builder -notmatch [regex]::Escape("signAndEditExecutable: false")) {
    throw "electron-builder resource editing must be disabled in favor of the local after-pack hook."
}
if ($builder -notmatch [regex]::Escape("to: defaults/robot_platform")) {
    throw "Packaged robot defaults must use the canonical robot_platform path."
}

$afterPack = Join-Path $desktopDir "electron\\after-pack.js"
if (-not (Test-Path -LiteralPath $afterPack -PathType Leaf)) {
    throw "Missing local Windows resource-editing hook."
}
$afterPackSource = Get-Content -LiteralPath $afterPack -Raw
foreach ($required in @(
    "rcedit-x64.exe",
    "--set-icon",
    "ProductName",
    "ProductVersion",
    "RESOURCE_EDIT_MAX_ATTEMPTS",
    "waitForResourceEditor"
)) {
    if ($afterPackSource -notmatch [regex]::Escape($required)) {
        throw "after-pack hook is missing required resource update: $required"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $desktopDir "tools\\rcedit-x64.exe") -PathType Leaf)) {
    throw "Missing bundled Windows resource editor."
}

Write-Host "release configuration checks passed."
