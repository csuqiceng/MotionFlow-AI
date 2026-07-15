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
    "default-config.json"
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
    throw "electron-builder must not download winCodeSign for an unsigned build"
}

Write-Host "package-win script checks passed."
