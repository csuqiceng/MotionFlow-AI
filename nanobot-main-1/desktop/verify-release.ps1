[CmdletBinding()]
param(
    [string]$ReleaseDir,
    [switch]$SkipExecutableMetadata,
    [switch]$SkipAsarInspection
)

$ErrorActionPreference = "Stop"

function Get-Sha256 {
    param([Parameter(Mandatory)][string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($hasher.ComputeHash($stream) | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $hasher.Dispose()
        $stream.Dispose()
    }
}

if ([string]::IsNullOrWhiteSpace($ReleaseDir)) {
    $ReleaseDir = Join-Path $PSScriptRoot "release2"
}
$release = [IO.Path]::GetFullPath($ReleaseDir)
$package = Get-Content -LiteralPath (Join-Path $PSScriptRoot "package.json") -Raw |
    ConvertFrom-Json
$version = [string]$package.version
$installerName = "motionflow-ai-Setup-$version.exe"
$installer = Join-Path $release $installerName
$unpacked = Join-Path $release "win-unpacked"

$required = @(
    "MotionFlow AI.exe",
    "resources\app.asar",
    "resources\py-runtime\robot_server.exe",
    "resources\py-runtime\_internal\_socket.pyd",
    "resources\py-runtime\_internal\_ssl.pyd",
    "resources\py-runtime\_internal\_asyncio.pyd",
    "resources\vendor\zmotion\zauxdll.dll",
    "resources\vendor\zmotion\zmotion.dll",
    "resources\vendor\zmotion\zauxdllPython.py",
    "resources\defaults\robot_platform\positions.json",
    "resources\defaults\robot_platform\commands.json",
    "resources\defaults\robot_platform\flows.json",
    "resources\defaults\robot_platform\knowledge.json"
)

$missing = @()
foreach ($relative in $required) {
    $path = Join-Path $unpacked $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $missing += $relative
    }
}
$pythonRuntime = Get-ChildItem -LiteralPath (Join-Path $unpacked "resources\py-runtime\_internal") `
    -Filter "python*.dll" -File -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $pythonRuntime) {
    $missing += "resources\py-runtime\_internal\python*.dll"
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
    $jsonPath = Join-Path $unpacked "resources\defaults\robot_platform\$jsonName"
    try {
        [IO.File]::ReadAllText(
            $jsonPath,
            [Text.UTF8Encoding]::new($false)
        ) | ConvertFrom-Json | Out-Null
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
    $exe = Join-Path $unpacked "MotionFlow AI.exe"
    $info = (Get-Item -LiteralPath $exe).VersionInfo
    if ($info.ProductName -ne "MotionFlow AI") {
        throw "Unexpected ProductName: $($info.ProductName)"
    }
    if ($info.ProductVersion -ne $version) {
        throw "Unexpected ProductVersion: $($info.ProductVersion)"
    }
    # Local developer machines can lack the optional PowerShell Security
    # module.  This build is not code-signed, so retain metadata validation
    # and report signature status when available without rejecting a valid
    # local artefact solely because inspection is unavailable.
    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $exe -ErrorAction Stop
        Write-Host "Executable signature: $($signature.Status)"
    }
    catch {
        Write-Warning "Executable signature inspection unavailable: $($_.Exception.Message)"
    }
}

$hash = Get-Sha256 -Path $installer
$hashPath = "$installer.sha256"
[IO.File]::WriteAllText(
    $hashPath,
    "$hash *$installerName`r`n",
    [Text.ASCIIEncoding]::new()
)

Write-Host "Release verification passed."
Write-Host "Installer: $installer"
Write-Host "SHA-256: $hashPath"
