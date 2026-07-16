$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$scriptPath = Join-Path $desktopDir "smoke-packaged-gateway.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Missing packaged Gateway smoke script."
}

$source = Get-Content -LiteralPath $scriptPath -Raw
foreach ($required in @(
    "nanobot_gateway.exe",
    "NANOBOT_HOME",
    "NANOBOT_DEFAULTS_DIR",
    "ROBOT_AI_BACKEND",
    "/webui/bootstrap",
    "taskkill",
    "contains spaces"
)) {
    if ($source -notmatch [regex]::Escape($required)) {
        throw "Smoke script is missing required behavior: $required"
    }
}

Write-Host "packaged Gateway smoke-script checks passed."
