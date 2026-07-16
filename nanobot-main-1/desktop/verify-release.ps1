[CmdletBinding()]
param(
    [string]$ReleaseDir = (Join-Path $PSScriptRoot "release-build4"),
    [switch]$SkipExecutableMetadata,
    [switch]$SkipAsarInspection
)

$ErrorActionPreference = "Stop"
$release = [IO.Path]::GetFullPath($ReleaseDir)
$package = Get-Content -LiteralPath (Join-Path $PSScriptRoot "package.json") -Raw |
    ConvertFrom-Json
$version = [string]$package.version
$installerName = "nanobot-robot-ai-Setup-$version.exe"
$installer = Join-Path $release $installerName
$unpacked = Join-Path $release "win-unpacked"

$required = @(
    "Nanobot Robot AI.exe",
    "resources\app.asar",
    "resources\py-runtime\nanobot_gateway.exe",
    "resources\py-runtime\_internal\python311.dll",
    "resources\py-runtime\_internal\_socket.pyd",
    "resources\py-runtime\_internal\_ssl.pyd",
    "resources\py-runtime\_internal\_asyncio.pyd",
    "resources\vendor\zmotion\zauxdll.dll",
    "resources\vendor\zmotion\zmotion.dll",
    "resources\vendor\zmotion\zauxdllPython.py",
    "resources\defaults\robot_ai\positions.json",
    "resources\defaults\robot_ai\commands.json",
    "resources\defaults\robot_ai\flows.json",
    "resources\defaults\robot_ai\knowledge.json"
)

$missing = @()
foreach ($relative in $required) {
    $path = Join-Path $unpacked $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $missing += $relative
    }
}
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    $missing += $installerName
}
if ($missing.Count -gt 0) {
    throw ("Release is incomplete. Missing:`n - " + ($missing -join "`n - "))
}

if ((Get-Item -LiteralPath $installer).Length -eq 0) {
    throw "Installer is empty: $installer"
}

foreach ($jsonName in @("positions.json", "commands.json", "flows.json", "knowledge.json")) {
    $jsonPath = Join-Path $unpacked "resources\defaults\robot_ai\$jsonName"
    try {
        Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json | Out-Null
    }
    catch {
        throw "Invalid packaged JSON file $jsonName`: $($_.Exception.Message)"
    }
}

if (-not $SkipAsarInspection) {
    $asar = Join-Path $PSScriptRoot "node_modules\.bin\asar.cmd"
    if (-not (Test-Path -LiteralPath $asar -PathType Leaf)) {
        throw "asar.cmd is required for release inspection."
    }
    $entries = @(& $asar list (Join-Path $unpacked "resources\app.asar"))
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect app.asar."
    }
    foreach ($entry in @("\build\main.js", "\package.json", "\electron\default-config.json")) {
        if ($entries -notcontains $entry) {
            throw "app.asar is missing $entry"
        }
    }
}

if (-not $SkipExecutableMetadata) {
    $exe = Join-Path $unpacked "Nanobot Robot AI.exe"
    $info = (Get-Item -LiteralPath $exe).VersionInfo
    if ($info.ProductName -ne "Nanobot Robot AI") {
        throw "Unexpected ProductName: $($info.ProductName)"
    }
    if ($info.ProductVersion -ne $version) {
        throw "Unexpected ProductVersion: $($info.ProductVersion)"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $exe
    Write-Host "Executable signature: $($signature.Status)"
}

$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$hashPath = "$installer.sha256"
[IO.File]::WriteAllText(
    $hashPath,
    "$hash *$installerName`r`n",
    [Text.ASCIIEncoding]::new()
)

Write-Host "Release verification passed."
Write-Host "Installer: $installer"
Write-Host "SHA-256: $hashPath"
