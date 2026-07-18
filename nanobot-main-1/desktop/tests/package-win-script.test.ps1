$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$scriptPath = Join-Path $desktopDir "package-win.ps1"
$launcherPath = Join-Path $desktopDir "package-win.bat"

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Missing package script: $scriptPath"
}

if (-not (Test-Path -LiteralPath $launcherPath)) {
    throw "Missing package launcher: $launcherPath"
}

$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
) | Out-Null

if ($parseErrors.Count -gt 0) {
    throw "PowerShell syntax error: $($parseErrors[0].Message)"
}

$content = Get-Content -LiteralPath $scriptPath -Raw
foreach ($expected in @(
    "Read-Host",
    "-AsSecureString",
    "NANOBOT_ORGANIZATION_API_KEY",
    "PyInstaller",
    "npm.cmd",
    "run build",
    "run dist",
    "default-config.json",
    "verify-release.ps1",
    "smoke-packaged-gateway.ps1",
    "Get-FileHash",
    "release-build4"
)) {
    if ($content -notmatch [regex]::Escape($expected)) {
        throw "Missing expected behavior: $expected"
    }
}

$launcher = Get-Content -LiteralPath $launcherPath -Raw
if ($launcher -notmatch [regex]::Escape("package-win.ps1")) {
    throw "Launcher does not invoke package-win.ps1"
}

$builderConfig = Get-Content -LiteralPath (Join-Path $desktopDir "electron-builder.yml") -Raw
if ($builderConfig -notmatch [regex]::Escape("signAndEditExecutable: false")) {
    throw "electron-builder must delegate Windows resource editing to after-pack.js."
}
if ($builderConfig -notmatch [regex]::Escape("afterPack: electron/after-pack.js")) {
    throw "electron-builder must invoke the local Windows resource-editing hook."
}

if ($content -notmatch [regex]::Escape("Reset-BuildOutput")) {
    throw "Packaging must clean generated output before rebuilding."
}

Write-Host "package-win script checks passed."
