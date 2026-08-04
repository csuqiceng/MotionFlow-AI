# Full desktop build pipeline: venv -> python deps -> PyInstaller -> Electron -> NSIS installer.
# Run from anywhere on Windows (Python 3.11/3.12 and Node 18+ on PATH).
#
#   pwsh ./desktop/build-desktop.ps1
#
# Output: desktop/release/motionflow-ai-Setup-<version>.exe
$ErrorActionPreference = "Stop"

$RepoRoot   = (Resolve-Path "$PSScriptRoot/..").Path
$Desktop    = Join-Path $RepoRoot "desktop"
$Venv       = Join-Path $Desktop ".build-venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$ProjectPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

# PyBullet has a native extension. Keep the packaging interpreter aligned
# with the Python 3.11/3.12 runtime validated for this product rather than
# silently taking a newer system Python that cannot load the built wheel.
$BootstrapPython = if ($env:ROBOT_BUILD_PYTHON) { $env:ROBOT_BUILD_PYTHON } else { $ProjectPython }
if (-not (Test-Path -LiteralPath $BootstrapPython -PathType Leaf)) {
    throw "A verified Python 3.11/3.12 interpreter is required. Set ROBOT_BUILD_PYTHON or create $ProjectPython."
}
& $BootstrapPython -c "import sys; assert sys.version_info[:2] in ((3, 11), (3, 12)), sys.version"
if ($LASTEXITCODE -ne 0) {
    throw "PyBullet desktop packaging supports only Python 3.11 or 3.12."
}

# 1. Create/refresh the build venv and install python deps (editable so the
#    spec's `datas` resolve against the live repo, incl. nanobot/web/dist).
if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython -c "import sys; assert sys.version_info[:2] in ((3, 11), (3, 12)), sys.version"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "==> replacing incompatible build venv"
        Remove-Item -LiteralPath $Venv -Recurse -Force
    }
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "==> creating build venv"
    & $BootstrapPython -m venv $Venv
}
& $VenvPython -m pip install -U pip
& $VenvPython -m pip install -e "$RepoRoot[api,pdf,simulation]" "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "python dependency install failed" }
& $VenvPython -c "import pybullet; print('PyBullet API', pybullet.getAPIVersion())"
if ($LASTEXITCODE -ne 0) { throw "PyBullet native runtime verification failed" }

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
