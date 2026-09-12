# Full desktop build pipeline: venv -> python deps -> PyInstaller -> Electron -> NSIS installer.
# Run from anywhere on Windows (Python 3.11+ and Node 18+ on PATH).
#
#   pwsh ./desktop/build-desktop.ps1
#
# Output: desktop/release/motionflow-ai-Setup-<version>.exe
$ErrorActionPreference = "Stop"

$RepoRoot   = (Resolve-Path "$PSScriptRoot/..").Path
$Desktop    = Join-Path $RepoRoot "desktop"
$Venv       = Join-Path $Desktop ".build-venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

# 1. Create/refresh the build venv and install python deps (editable so the
#    spec's `datas` resolve against the live repo, incl. nanobot/web/dist).
if (-not (Test-Path $VenvPython)) {
    Write-Host "==> creating build venv"
    python -m venv $Venv
}
& $VenvPython -m pip install -U pip
& $VenvPython -m pip install -e "$RepoRoot[api,pdf]" "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "python dependency install failed" }

# 2. PyInstaller onedir -> desktop/pyinstaller/dist-robot-server/py-runtime/
Write-Host "==> PyInstaller"
Push-Location (Join-Path $Desktop "pyinstaller")
& $VenvPython -m PyInstaller robot_server.spec --noconfirm --clean --distpath dist-robot-server --workpath build-robot-server
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

# 3. Electron app: install deps and compile TypeScript.
Write-Host "==> Electron build"
Push-Location $Desktop
npm install
npm run build
# 4. electron-builder -> desktop/release/*.exe
npm run dist
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }

Write-Host ""
Write-Host "Done. Installer:" (Resolve-Path (Join-Path $Desktop "release\motionflow-ai-Setup-*.exe"))
