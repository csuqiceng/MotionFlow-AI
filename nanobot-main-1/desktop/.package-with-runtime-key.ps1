$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent $PSCommandPath
$configPath = Join-Path $env:APPDATA "motionflow-ai\runtime\config.json"
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Verified packaged runtime config is unavailable."
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$apiKey = [string]$config.providers.dashscope.apiKey
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "Deployment API key is unavailable."
}

$secureKey = ConvertTo-SecureString $apiKey -AsPlainText -Force
try {
    & (Join-Path $desktopDir "package-win.ps1") -ApiKey $secureKey
    if ($LASTEXITCODE -ne 0) {
        throw "package-win.ps1 failed with exit code $LASTEXITCODE."
    }
}
finally {
    $apiKey = $null
    $secureKey = $null
}
