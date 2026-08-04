$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$specPath = Join-Path $desktopDir "pyinstaller\robot_server.spec"

if (-not (Test-Path -LiteralPath $specPath -PathType Leaf)) {
    throw "The release pipeline requires a versioned PyInstaller robot-server spec: $specPath"
}

$source = Get-Content -LiteralPath $specPath -Raw
foreach ($required in @(
    "robot_server_launcher.py",
    "robot_server",
    "webui",
    "seed_query_table.json",
    "seed_positions.json",
    'str(REPO_ROOT / "robot_platform" / "simulation" / "models")',
    "robot_platform.backends.pybullet_plugin",
    '"pybullet"',
    "robot_platform.backends.zmotion_plugin",
    "robot_platform.backends.zmotion_adapter",
    "nanobot.channels",
    "nanobot.gateway",
    "nanobot.pairing"
)) {
    if ($source -notmatch [regex]::Escape($required)) {
        throw "PyInstaller spec is missing required packaging rule: $required"
    }
}

$launcherPath = Join-Path $desktopDir "pyinstaller\robot_server_launcher.py"
$launcher = Get-Content -LiteralPath $launcherPath -Raw
if ($launcher -notmatch [regex]::Escape("sys.path.insert(0")) {
    throw "The PyInstaller launcher must prioritize the checked-out repository over editable build-environment paths."
}
if ($launcher -notmatch [regex]::Escape("--verify-pybullet-runtime")) {
    throw "The PyInstaller launcher must provide the packaged PyBullet DIRECT runtime self-check."
}

Write-Host "PyInstaller robot-server spec checks passed."
