$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$package = Get-Content -LiteralPath (Join-Path $desktopDir "package.json") -Raw | ConvertFrom-Json
$builder = Get-Content -LiteralPath (Join-Path $desktopDir "electron-builder.yml") -Raw

if ($package.author.name -ne "Nanobot Robot AI") {
    throw "package.json must define the Windows company/product author."
}
if ($package.scripts.verifyRelease -ne "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\verify-release.ps1") {
    throw "package.json must expose the release verifier."
}
if ($package.scripts.smokePackagedGateway -ne "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\smoke-packaged-gateway.ps1") {
    throw "package.json must expose the packaged Gateway smoke test."
}
if ($builder -notmatch [regex]::Escape("executableName: Nanobot Robot AI")) {
    throw "Windows executableName is missing."
}
if ($builder -notmatch [regex]::Escape("icon: ../images/nanobot_logo.png")) {
    throw "Windows product icon is missing."
}
if ($builder -notmatch "target:\s*\r?\n\s+- target: nsis\s*\r?\n\s+arch:\s*\r?\n\s+- x64") {
    throw "The Windows target must explicitly be NSIS x64."
}
if ($builder -match [regex]::Escape("signAndEditExecutable: false")) {
    throw "Executable resource editing must not be disabled."
}

Write-Host "release configuration checks passed."
