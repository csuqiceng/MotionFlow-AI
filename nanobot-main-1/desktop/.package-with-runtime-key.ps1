$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent $PSCommandPath
$apiKey = [string]$env:NANOBOT_ORGANIZATION_API_KEY
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "NANOBOT_ORGANIZATION_API_KEY is required in the controlled build environment."
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
