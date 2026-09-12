$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$scriptPath = Join-Path $desktopDir "smoke-packaged-robot-server.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) { throw "Missing packaged robot-server smoke script." }

$source = Get-Content -LiteralPath $scriptPath -Raw
foreach ($required in @(
    "robot_server.exe", "NANOBOT_HOME", "NANOBOT_DEFAULTS_DIR", "ROBOT_PLATFORM_DATA_DIR", "ROBOT_AI_BACKEND",
    "/health", "/api/library/commands", "data.items", "<title>", 'id="root"', "nanobot web UI", "taskkill", "contains spaces", "robot_platform", "PSScriptRoot is initialized",
    "configArgument", '"{0}"'
)) {
    if ($source -notmatch [regex]::Escape($required)) { throw "Smoke script is missing required behavior: $required" }
}
Write-Host "packaged robot-server smoke-script checks passed."
