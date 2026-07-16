# Windows Release Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible Windows 10/11 x64 NSIS installer that contains the complete Electron, Python, Robot AI, default-data, and ZMotion runtime, and reject incomplete packages before they are distributed.

**Architecture:** Keep the existing Electron + PyInstaller onedir + electron-builder/NSIS architecture. Treat every build directory as disposable, validate both the intermediate `win-unpacked` tree and final Setup executable, run the packaged Gateway from an isolated path, and expose only Setup plus its SHA-256 file as release artifacts.

**Tech Stack:** PowerShell 5.1+, TypeScript, Electron 33, electron-builder 24, PyInstaller 6, Python 3.11, Node.js/npm, NSIS.

---

## File Structure

- `desktop/.gitignore`: ignore all local Electron/PyInstaller release output.
- `desktop/package.json`: define product author metadata and packaging scripts.
- `desktop/electron-builder.yml`: define x64 NSIS output, product metadata, icon, and executable resource editing.
- `desktop/package-win.ps1`: orchestrate clean build, verification, smoke test, and final release reporting.
- `desktop/tests/release-artifacts-policy.test.ps1`: ensure generated releases are not tracked by Git.
- `desktop/tests/release-config.test.ps1`: verify the declarative Windows release configuration.
- `desktop/tests/verify-release.test.ps1`: exercise release-layout validation and SHA-256 generation with fixtures.
- `desktop/verify-release.ps1`: validate the final release tree and installer.
- `desktop/smoke-packaged-gateway.ps1`: run the packaged Gateway from a moved directory with isolated data.
- `desktop/tests/smoke-packaged-gateway-script.test.ps1`: verify the smoke-test contract without requiring a built package.
- `desktop/README.md`: document the supported platform, one-command build, release files, SmartScreen behavior, and clean-machine test checklist.
- `desktop/release-build4/`: generated output removed from the Git index and retained only locally.

### Task 1: Stop Versioning Generated Release Trees

**Files:**
- Modify: `desktop/.gitignore`
- Create: `desktop/tests/release-artifacts-policy.test.ps1`
- Remove from Git index only: `desktop/release-build4/**`
- Remove local stray file: `desktop/electron.exe`

- [ ] **Step 1: Write the failing release-artifact policy test**

Create `desktop/tests/release-artifacts-policy.test.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$repoRoot = Split-Path -Parent $desktopDir
$probe = Join-Path $desktopDir "release-build4\policy-probe.bin"

$ignored = & git -C $repoRoot check-ignore $probe
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ignored)) {
    throw "desktop/release-build4 must be ignored."
}

$tracked = @(& git -C $repoRoot ls-files -- "desktop/release-build4")
if ($tracked.Count -ne 0) {
    throw "desktop/release-build4 still has $($tracked.Count) tracked paths."
}

$strayElectron = Join-Path $desktopDir "electron.exe"
if (Test-Path -LiteralPath $strayElectron) {
    throw "The stray desktop/electron.exe path marker must not exist."
}

Write-Host "release artifact policy checks passed."
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/release-artifacts-policy.test.ps1
```

Expected: FAIL because `release-build4` is still tracked and is not ignored.

- [ ] **Step 3: Add generated output to the desktop ignore policy**

Append to `desktop/.gitignore`:

```gitignore
# Final Electron/NSIS packages are local release artifacts.
release-build4/

# Accidental path-marker file; the real Electron binary lives in node_modules.
electron.exe
```

- [ ] **Step 4: Remove generated release files from the Git index without deleting the working package**

Run from the repository root:

```powershell
git rm -r --cached --ignore-unmatch desktop/release-build4
```

Delete only the known 32-byte stray file:

```powershell
Remove-Item -LiteralPath desktop/electron.exe
```

Before deletion, verify:

```powershell
(Resolve-Path desktop/electron.exe).Path -eq (Join-Path (Resolve-Path desktop).Path "electron.exe")
```

Expected: `True`.

- [ ] **Step 5: Run the policy test and verify it passes**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/release-artifacts-policy.test.ps1
```

Expected: `release artifact policy checks passed.`

- [ ] **Step 6: Commit the artifact policy**

```powershell
git add desktop/.gitignore desktop/tests/release-artifacts-policy.test.ps1
git add -u desktop/release-build4 desktop/electron.exe
git commit -m "build: stop tracking generated desktop releases"
```

### Task 2: Define Correct Windows Product Metadata and x64 Target

**Files:**
- Modify: `desktop/package.json`
- Modify: `desktop/electron-builder.yml`
- Create: `desktop/tests/release-config.test.ps1`
- Reuse: `images/nanobot_logo.png`

- [ ] **Step 1: Write the failing release configuration test**

Create `desktop/tests/release-config.test.ps1`:

```powershell
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
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/release-config.test.ps1
```

Expected: FAIL because author metadata, verifier script, explicit x64 target, icon, and executable resource editing are not configured.

- [ ] **Step 3: Add package metadata and release scripts**

Update `desktop/package.json` so its relevant fields are:

```json
{
  "name": "nanobot-robot-ai-desktop",
  "private": true,
  "version": "0.1.0",
  "productName": "Nanobot Robot AI",
  "author": {
    "name": "Nanobot Robot AI"
  },
  "description": "Electron shell for nanobot Robot AI (bundles a PyInstaller-built gateway)",
  "main": "build/main.js",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "dev": "npm run build && set ELECTRON_DEV=1&& .\\node_modules\\electron\\dist\\electron.exe .",
    "start": "electron .",
    "dist": "electron-builder --config electron-builder.yml --win nsis --x64",
    "verifyRelease": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\verify-release.ps1",
    "smokePackagedGateway": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\smoke-packaged-gateway.ps1"
  }
}
```

Keep the existing `devDependencies` unchanged.

- [ ] **Step 4: Configure electron-builder metadata and target**

Replace the `win` block in `desktop/electron-builder.yml` with:

```yaml
win:
  executableName: Nanobot Robot AI
  icon: ../images/nanobot_logo.png
  legalTrademarks: Nanobot Robot AI
  target:
    - target: nsis
      arch:
        - x64
  artifactName: nanobot-robot-ai-Setup-${version}.${ext}
```

Add at top level:

```yaml
copyright: Copyright © 2026 Nanobot Robot AI
```

Remove `signAndEditExecutable: false`. With no certificate configured, the internal package remains unsigned, but electron-builder can edit the EXE resources. Code signing credentials will later be injected through the supported CI environment variables.

- [ ] **Step 5: Run the release configuration test**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/release-config.test.ps1
```

Expected: `release configuration checks passed.`

- [ ] **Step 6: Compile TypeScript and commit**

```powershell
Set-Location desktop
npm.cmd run build
Set-Location ..
git add desktop/package.json desktop/electron-builder.yml desktop/tests/release-config.test.ps1
git commit -m "build: define Windows x64 release metadata"
```

### Task 3: Add a Release Layout and Installer Validator

**Files:**
- Create: `desktop/verify-release.ps1`
- Create: `desktop/tests/verify-release.test.ps1`

- [ ] **Step 1: Write the failing verifier test**

Create `desktop/tests/verify-release.test.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$verifier = Join-Path $desktopDir "verify-release.ps1"
$fixture = Join-Path $env:TEMP ("nanobot-release-fixture-" + [guid]::NewGuid().ToString("N"))
$release = Join-Path $fixture "release-build4"
$unpacked = Join-Path $release "win-unpacked"
$resources = Join-Path $unpacked "resources"
$runtime = Join-Path $resources "py-runtime"

try {
    New-Item -ItemType Directory -Path (Join-Path $runtime "_internal") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $resources "vendor\zmotion") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $resources "defaults\robot_ai") -Force | Out-Null

    $required = @(
        "win-unpacked\Nanobot Robot AI.exe",
        "win-unpacked\resources\app.asar",
        "win-unpacked\resources\py-runtime\nanobot_gateway.exe",
        "win-unpacked\resources\py-runtime\_internal\python311.dll",
        "win-unpacked\resources\py-runtime\_internal\_socket.pyd",
        "win-unpacked\resources\py-runtime\_internal\_ssl.pyd",
        "win-unpacked\resources\py-runtime\_internal\_asyncio.pyd",
        "win-unpacked\resources\vendor\zmotion\zauxdll.dll",
        "win-unpacked\resources\vendor\zmotion\zmotion.dll",
        "win-unpacked\resources\vendor\zmotion\zauxdllPython.py",
        "win-unpacked\resources\defaults\robot_ai\positions.json",
        "win-unpacked\resources\defaults\robot_ai\commands.json",
        "win-unpacked\resources\defaults\robot_ai\flows.json",
        "win-unpacked\resources\defaults\robot_ai\knowledge.json",
        "nanobot-robot-ai-Setup-0.1.0.exe"
    )
    foreach ($relative in $required) {
        $path = Join-Path $release $relative
        New-Item -ItemType Directory -Path (Split-Path $path) -Force | Out-Null
        [IO.File]::WriteAllBytes($path, [byte[]](1, 2, 3))
    }

    Remove-Item -LiteralPath (Join-Path $runtime "_internal\_socket.pyd")
    $missingSocketRejected = $false
    try {
        & $verifier -ReleaseDir $release -SkipExecutableMetadata -SkipAsarInspection
    }
    catch {
        $missingSocketRejected = $_.Exception.Message -match "_socket\.pyd"
    }
    if (-not $missingSocketRejected) {
        throw "Verifier must fail when _socket.pyd is missing."
    }

    [IO.File]::WriteAllBytes(
        (Join-Path $runtime "_internal\_socket.pyd"),
        [byte[]](1, 2, 3)
    )
    & $verifier -ReleaseDir $release -SkipExecutableMetadata -SkipAsarInspection

    $hashFile = Join-Path $release "nanobot-robot-ai-Setup-0.1.0.exe.sha256"
    if (-not (Test-Path -LiteralPath $hashFile)) {
        throw "Verifier did not create the SHA-256 file."
    }
    if ((Get-Content -LiteralPath $hashFile -Raw) -notmatch "^[0-9A-Fa-f]{64}\s+\*nanobot-robot-ai-Setup-0\.1\.0\.exe") {
        throw "SHA-256 file format is invalid."
    }

    Write-Host "release verifier tests passed."
}
finally {
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
```

- [ ] **Step 2: Run the verifier test and confirm the missing script failure**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/verify-release.test.ps1
```

Expected: FAIL because `desktop/verify-release.ps1` does not exist.

- [ ] **Step 3: Implement the release verifier**

Create `desktop/verify-release.ps1`:

```powershell
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
    Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json | Out-Null
}

if (-not $SkipAsarInspection) {
    $asar = Join-Path $PSScriptRoot "node_modules\.bin\asar.cmd"
    if (-not (Test-Path -LiteralPath $asar)) {
        throw "asar.cmd is required for release inspection."
    }
    $entries = @(& $asar list (Join-Path $unpacked "resources\app.asar"))
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
Set-Content -LiteralPath $hashPath -Encoding ascii -NoNewline `
    -Value "$hash *$installerName`n"

Write-Host "Release verification passed."
Write-Host "Installer: $installer"
Write-Host "SHA-256: $hashPath"
```

- [ ] **Step 4: Run the verifier tests**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/verify-release.test.ps1
```

Expected: `release verifier tests passed.`

- [ ] **Step 5: Commit the verifier**

```powershell
git add desktop/verify-release.ps1 desktop/tests/verify-release.test.ps1
git commit -m "build: validate Windows release contents"
```

### Task 4: Add an Isolated Packaged-Gateway Smoke Test

**Files:**
- Create: `desktop/smoke-packaged-gateway.ps1`
- Create: `desktop/tests/smoke-packaged-gateway-script.test.ps1`

- [ ] **Step 1: Write the failing smoke-script contract test**

Create `desktop/tests/smoke-packaged-gateway-script.test.ps1`:

```powershell
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
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/smoke-packaged-gateway-script.test.ps1
```

Expected: FAIL because the smoke script does not exist.

- [ ] **Step 3: Implement isolated Gateway smoke execution**

Create `desktop/smoke-packaged-gateway.ps1` with these behaviors:

```powershell
[CmdletBinding()]
param(
    [string]$ReleaseDir = (Join-Path $PSScriptRoot "release-build4"),
    [int]$ChannelPort = 0,
    [int]$GatewayPort = 0
)

$ErrorActionPreference = "Stop"

function Get-FreeTcpPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

if ($ChannelPort -eq 0) { $ChannelPort = Get-FreeTcpPort }
if ($GatewayPort -eq 0) { $GatewayPort = Get-FreeTcpPort }
if ($ChannelPort -eq $GatewayPort) { $GatewayPort = Get-FreeTcpPort }

$source = Join-Path ([IO.Path]::GetFullPath($ReleaseDir)) "win-unpacked"
$scratch = Join-Path $env:TEMP ("nanobot packaged smoke contains spaces " + [guid]::NewGuid().ToString("N"))
$appCopy = Join-Path $scratch "Nanobot App"
$runtime = Join-Path $scratch "runtime"
$process = $null

try {
    Copy-Item -LiteralPath $source -Destination $appCopy -Recurse
    New-Item -ItemType Directory -Path (Join-Path $runtime "robot_ai") -Force | Out-Null

    $asar = Join-Path $PSScriptRoot "node_modules\.bin\asar.cmd"
    Push-Location $runtime
    try {
        & $asar extract-file (Join-Path $appCopy "resources\app.asar") `
            "electron/default-config.json"
        Move-Item -LiteralPath "default-config.json" -Destination "config.json"
    }
    finally {
        Pop-Location
    }

    Copy-Item -Path (Join-Path $appCopy "resources\defaults\robot_ai\*") `
        -Destination (Join-Path $runtime "robot_ai") -Recurse -Force

    $configPath = Join-Path $runtime "config.json"
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $config.agents.defaults.workspace = ""
    $configJson = $config | ConvertTo-Json -Depth 100
    [IO.File]::WriteAllText(
        $configPath,
        $configJson + "`n",
        [Text.UTF8Encoding]::new($false)
    )

    $environment = @{
        NANOBOT_HOME = $runtime
        NANOBOT_DEFAULTS_DIR = (Join-Path $appCopy "resources\defaults")
        NANOBOT_INITIAL_SEED = "1"
        NANOBOT_RUNTIME_CHANNEL_PORT = [string]$ChannelPort
        NANOBOT_RUNTIME_GATEWAY_PORT = [string]$GatewayPort
        ROBOT_AI_BACKEND = "simulation"
        PYTHONIOENCODING = "utf-8"
        PYTHONUNBUFFERED = "1"
    }

    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = Join-Path $appCopy "resources\py-runtime\nanobot_gateway.exe"
    $start.Arguments = "--config `"$configPath`""
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($entry in $environment.GetEnumerator()) {
        $start.EnvironmentVariables[$entry.Key] = $entry.Value
    }

    $process = [Diagnostics.Process]::Start($start)
    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    do {
        Start-Sleep -Milliseconds 250
        if ($process.HasExited) { break }
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$ChannelPort/webui/bootstrap" `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
            }
        }
        catch {
            if ($null -ne $_.Exception.Response -and
                [int]$_.Exception.Response.StatusCode -eq 401) {
                $ready = $true
            }
        }
    } while (-not $ready -and (Get-Date) -lt $deadline)

    if (-not $ready) {
        if (-not $process.HasExited) { $process.Kill() }
        $stderr = $process.StandardError.ReadToEnd()
        $stdout = $process.StandardOutput.ReadToEnd()
        throw "Packaged Gateway smoke test failed.`nSTDERR:`n$stderr`nSTDOUT:`n$stdout"
    }

    Write-Host "Packaged Gateway smoke test passed."
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
    }
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
}
```

- [ ] **Step 4: Run the smoke-script contract test**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/smoke-packaged-gateway-script.test.ps1
```

Expected: `packaged Gateway smoke-script checks passed.`

- [ ] **Step 5: Commit the smoke test**

```powershell
git add desktop/smoke-packaged-gateway.ps1 desktop/tests/smoke-packaged-gateway-script.test.ps1
git commit -m "test: smoke test packaged Gateway portability"
```

### Task 5: Make the One-Click Build Deterministic and Fail Closed

**Files:**
- Modify: `desktop/package-win.ps1`
- Modify: `desktop/tests/package-win-script.test.ps1`
- Modify: `desktop/package-win.bat`

- [ ] **Step 1: Extend the packaging-script test**

In `desktop/tests/package-win-script.test.ps1`, replace the expected-behavior list with:

```powershell
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
```

Replace the old `signAndEditExecutable: false` assertion with:

```powershell
if ($builderConfig -match [regex]::Escape("signAndEditExecutable: false")) {
    throw "electron-builder must edit Windows executable resources."
}
```

Add:

```powershell
if ($content -notmatch [regex]::Escape("Reset-BuildOutput")) {
    throw "Packaging must clean generated output before rebuilding."
}
```

- [ ] **Step 2: Run the packaging test and verify it fails**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/package-win-script.test.ps1
```

Expected: FAIL because clean output, verifier, smoke test, and hash verification are not yet integrated.

- [ ] **Step 3: Add safe generated-output cleanup**

Add this function to `desktop/package-win.ps1`:

```powershell
function Reset-BuildOutput {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$AllowedRoot
    )

    $root = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd("\") + "\"
    $target = [IO.Path]::GetFullPath($Path)
    if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean output outside desktop: $target"
    }
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
```

Before the PyInstaller invocation, call:

```powershell
Reset-BuildOutput -Path (Join-Path $pyinstallerDir "build") -AllowedRoot $desktopDir
Reset-BuildOutput -Path (Join-Path $pyinstallerDir "dist") -AllowedRoot $desktopDir
Reset-BuildOutput -Path (Join-Path $desktopDir "release-build4") -AllowedRoot $desktopDir
```

- [ ] **Step 4: Strengthen preflight resource checks**

The required path list must contain:

```powershell
foreach ($requiredPath in @(
    $buildPython,
    (Join-Path $pyinstallerDir "nanobot.spec"),
    (Join-Path $desktopDir "..\nanobot\web\dist\index.html"),
    (Join-Path $desktopDir "..\vendor\zmotion\zauxdll.dll"),
    (Join-Path $desktopDir "..\vendor\zmotion\zmotion.dll"),
    (Join-Path $desktopDir "..\vendor\zmotion\zauxdllPython.py"),
    (Join-Path $desktopDir "electron\config.default.template.json"),
    (Join-Path $desktopDir "electron\defaults\robot_ai\positions.json"),
    (Join-Path $desktopDir "electron\defaults\robot_ai\commands.json"),
    (Join-Path $desktopDir "electron\defaults\robot_ai\flows.json"),
    (Join-Path $desktopDir "electron\defaults\robot_ai\knowledge.json"),
    (Join-Path $desktopDir "verify-release.ps1"),
    (Join-Path $desktopDir "smoke-packaged-gateway.ps1")
)) {
```

Remove the obsolete preflight requirement for an already-built `nanobot_gateway.exe`.

- [ ] **Step 5: Integrate verification and smoke execution**

After `npm run dist` succeeds, invoke:

```powershell
Write-Host "Verifying Windows release..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $desktopDir "verify-release.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Release verification failed with exit code $LASTEXITCODE."
}

Write-Host "Running packaged Gateway smoke test..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $desktopDir "smoke-packaged-gateway.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Gateway smoke test failed with exit code $LASTEXITCODE."
}
```

After finding `$installer`, also require:

```powershell
$hashFile = "$($installer.FullName).sha256"
if (-not (Test-Path -LiteralPath $hashFile)) {
    throw "Installer SHA-256 file was not generated."
}
```

Print success only after all checks:

```powershell
Write-Host "Package created and verified:"
Write-Host "  $($installer.FullName)"
Write-Host "  $hashFile"
```

- [ ] **Step 6: Update the BAT success message**

Change `desktop/package-win.bat` to:

```bat
echo.
echo The verified Setup.exe and SHA-256 file are in release-build4.
```

- [ ] **Step 7: Run packaging script tests**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/package-win-script.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/release-config.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/release-artifacts-policy.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/verify-release.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/tests/smoke-packaged-gateway-script.test.ps1
```

Expected: all five scripts pass.

- [ ] **Step 8: Commit deterministic packaging**

```powershell
git add desktop/package-win.ps1 desktop/package-win.bat desktop/tests/package-win-script.test.ps1
git commit -m "build: fail closed on incomplete Windows packages"
```

### Task 6: Update Distribution Documentation

**Files:**
- Modify: `desktop/README.md`

- [ ] **Step 1: Replace the corrupted release documentation**

Rewrite `desktop/README.md` as valid UTF-8 Chinese documentation containing:

```markdown
# Nanobot Robot AI Windows 桌面版

## 支持范围

- Windows 10/11 x64
- 目标电脑不需要安装 Python 或 Node.js
- Windows 7/8/8.1、32 位 Windows 和 ARM64 不在当前正式支持范围

## 一键打包

双击 `package-win.bat`，或运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\package-win.ps1
```

打包程序会安全读取组织 API Key，重新构建 Python Gateway 和 Electron，
生成安装包，检查关键 DLL/PYD，执行隔离路径 Gateway 烟雾测试，并生成 SHA-256。

## 正式交付文件

只向其他电脑提供：

```text
desktop/release-build4/nanobot-robot-ai-Setup-<version>.exe
desktop/release-build4/nanobot-robot-ai-Setup-<version>.exe.sha256
```

不要单独复制 `win-unpacked/Nanobot Robot AI.exe`。`win-unpacked` 仅供本机诊断。

## 未签名内部包

没有配置 Windows 代码签名证书时，安装包属于未签名内部测试包。
SmartScreen 可能显示“未知发布者”，企业电脑也可能直接阻止运行。
正式对外分发前应配置 OV、EV 或 Azure Trusted Signing。

## 干净电脑验收

每次正式发布至少在 Windows 10 x64 和 Windows 11 x64 的干净虚拟机中验证：

1. 未安装 Python 和 Node.js；
2. 安装 Setup；
3. 首次启动并打开登录页；
4. 使用默认账户登录；
5. 命令库、流程库和控制器状态页面可打开；
6. 关闭应用后 `nanobot_gateway.exe` 不残留；
7. 升级安装不覆盖用户运行数据；
8. 卸载成功。
```

- [ ] **Step 2: Check Markdown encoding and required content**

Run:

```powershell
$text = Get-Content -LiteralPath desktop/README.md -Raw -Encoding utf8
foreach ($required in @("Windows 10/11 x64", "Setup-<version>.exe", "SHA-256", "SmartScreen")) {
    if ($text -notmatch [regex]::Escape($required)) { throw "README missing $required" }
}
```

Expected: no error.

- [ ] **Step 3: Commit documentation**

```powershell
git add desktop/README.md
git commit -m "docs: document verified Windows installer delivery"
```

### Task 7: Build and Verify the Real Installer

**Files:**
- Generated only: `desktop/release-build4/**`

- [ ] **Step 1: Run all fast tests before packaging**

```powershell
Set-Location desktop
npm.cmd run build
node electron/tests/before-pack.test.js
node electron/tests/packaged-gateway-launch.test.js
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/release-artifacts-policy.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/release-config.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/verify-release.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/smoke-packaged-gateway-script.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/package-win-script.test.ps1
```

Expected: TypeScript build exits 0 and all script tests pass.

- [ ] **Step 2: Run the real one-click package command**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\package-win.ps1
```

Enter the existing revocable organization API Key in the secure prompt. Do not print or save it in logs.

Expected:

```text
Release verification passed.
Packaged Gateway smoke test passed.
Package created and verified:
  ...\nanobot-robot-ai-Setup-0.1.0.exe
  ...\nanobot-robot-ai-Setup-0.1.0.exe.sha256
```

- [ ] **Step 3: Independently re-run release verification**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\verify-release.ps1
```

Expected: `Release verification passed.`

- [ ] **Step 4: Inspect the final executable and installer**

```powershell
$exe = ".\release-build4\win-unpacked\Nanobot Robot AI.exe"
$installer = ".\release-build4\nanobot-robot-ai-Setup-0.1.0.exe"
(Get-Item $exe).VersionInfo | Select-Object ProductName,ProductVersion,CompanyName,FileDescription
Get-AuthenticodeSignature $exe | Select-Object Status,StatusMessage
Get-FileHash $installer -Algorithm SHA256
Get-Content "$installer.sha256"
```

Expected:

- `ProductName` is `Nanobot Robot AI`;
- `ProductVersion` is `0.1.0`;
- signature is either a valid configured signature or explicitly `NotSigned`;
- calculated SHA-256 matches the `.sha256` file.

- [ ] **Step 5: Verify Git remains clean except for intentional source changes**

```powershell
Set-Location ..
git status --short
git ls-files desktop/release-build4
```

Expected: no generated release paths appear in status, and `git ls-files` prints nothing.

- [ ] **Step 6: Run clean-machine acceptance**

On Windows 10 x64 and Windows 11 x64 virtual machines with no Python or Node.js:

```text
Install Setup -> launch -> login -> open command/flow library -> exit -> uninstall
```

Record the OS version, installer SHA-256, login result, Gateway process cleanup result, and uninstall result. Do not mark the package externally releasable until both machine records pass.

- [ ] **Step 7: Confirm generated output is still excluded**

Run:

```powershell
git status --short --ignored desktop/release-build4
git ls-files desktop/release-build4
```

Expected: the release directory is reported only as ignored, and `git ls-files` prints nothing. Do not commit `desktop/release-build4`.
