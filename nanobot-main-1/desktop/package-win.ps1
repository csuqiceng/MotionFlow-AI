[CmdletBinding()]
param(
    [SecureString]$ApiKey
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

function ConvertTo-PlainText {
    param([Parameter(Mandatory)][SecureString]$Value)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

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

$desktopDir = Split-Path -Parent $PSCommandPath
$pyinstallerDir = Join-Path $desktopDir "pyinstaller"
$buildPython = Join-Path $desktopDir ".build-venv\Scripts\python.exe"
$generatedConfig = Join-Path $desktopDir "electron\default-config.json"
$releaseDir = Join-Path $desktopDir "release2"
$locationPushed = $false
$plainTextApiKey = $null
$hadPreviousApiKey = Test-Path Env:NANOBOT_ORGANIZATION_API_KEY
$previousApiKey = $env:NANOBOT_ORGANIZATION_API_KEY

try {
    foreach ($requiredPath in @(
        $buildPython,
        (Join-Path $pyinstallerDir "robot_server.spec"),
        (Join-Path $desktopDir "..\robot_server\webui\index.html"),
        (Join-Path $desktopDir "..\vendor\zmotion\zauxdll.dll"),
        (Join-Path $desktopDir "..\vendor\zmotion\zmotion.dll"),
        (Join-Path $desktopDir "..\vendor\zmotion\zauxdllPython.py"),
        (Join-Path $desktopDir "electron\assets\robot-arm-app-icon.ico"),
        (Join-Path $desktopDir "tools\rcedit-x64.exe"),
        (Join-Path $desktopDir "electron\config.default.template.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\positions.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\commands.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\flows.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\knowledge.json"),
        (Join-Path $desktopDir "verify-release.ps1"),
        (Join-Path $desktopDir "smoke-packaged-robot-server.ps1")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Required packaging resource is missing: $requiredPath"
        }
    }

    $npmCommand = Get-Command "npm.cmd" -ErrorAction Stop

    if ($null -eq $ApiKey) {
        $ApiKey = Read-Host "Enter the organization API key to embed" -AsSecureString
    }

    $plainTextApiKey = ConvertTo-PlainText -Value $ApiKey
    if ([string]::IsNullOrWhiteSpace($plainTextApiKey)) {
        throw "An API key is required."
    }

    Remove-Item -LiteralPath $generatedConfig -Force -ErrorAction SilentlyContinue
    Reset-BuildOutput -Path (Join-Path $pyinstallerDir "build-robot-server") -AllowedRoot $desktopDir
    Reset-BuildOutput -Path (Join-Path $pyinstallerDir "dist-robot-server") -AllowedRoot $desktopDir
    Reset-BuildOutput -Path $releaseDir -AllowedRoot $desktopDir

    $env:NANOBOT_ORGANIZATION_API_KEY = $plainTextApiKey

    # PyInstaller copies robot_server/webui verbatim.  Rebuild it first so the
    # installer can never silently contain stale WebUI assets.
    Write-Host "Building bundled WebUI..."
    Push-Location (Join-Path $desktopDir "..\webui")
    try {
        & $npmCommand.Source run build
        if ($LASTEXITCODE -ne 0) {
            throw "WebUI build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    Push-Location $desktopDir
    $locationPushed = $true

    Write-Host "Rebuilding the bundled robot server..."
    Push-Location $pyinstallerDir
    try {
        & $buildPython -m PyInstaller robot_server.spec --noconfirm --clean --distpath dist-robot-server --workpath build-robot-server
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller robot-server build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "Building Electron application..."
    & $npmCommand.Source run build
    if ($LASTEXITCODE -ne 0) {
        throw "npm run build failed with exit code $LASTEXITCODE."
    }

    Write-Host "Creating Windows installer..."
    & $npmCommand.Source run dist
    if ($LASTEXITCODE -ne 0) {
        throw "npm run dist failed with exit code $LASTEXITCODE."
    }

    Write-Host "Verifying Windows release..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $desktopDir "verify-release.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Release verification failed with exit code $LASTEXITCODE."
    }

    Write-Host "Running packaged robot-server smoke test..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $desktopDir "smoke-packaged-robot-server.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged robot-server smoke test failed with exit code $LASTEXITCODE."
    }

    $installer = Get-ChildItem -LiteralPath $releaseDir `
        -Filter "motionflow-ai-Setup-*.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $installer) {
        throw "The installer was not found in release2."
    }

    $hashFile = "$($installer.FullName).sha256"
    if (-not (Test-Path -LiteralPath $hashFile -PathType Leaf)) {
        throw "Installer SHA-256 file was not generated."
    }

    $actualHash = Get-Sha256 -Path $installer.FullName
    $recordedHash = ((Get-Content -LiteralPath $hashFile -Raw).Trim() -split "\s+")[0].ToLowerInvariant()
    if ($recordedHash -ne $actualHash) {
        throw "Installer SHA-256 file does not match the generated installer."
    }

    Write-Host "Package created and verified:"
    Write-Host "  $($installer.FullName)"
    Write-Host "  $hashFile"
}
finally {
    if ($locationPushed) {
        Pop-Location
    }

    Remove-Item -LiteralPath $generatedConfig -Force -ErrorAction SilentlyContinue

    if ($hadPreviousApiKey) {
        $env:NANOBOT_ORGANIZATION_API_KEY = $previousApiKey
    }
    else {
        Remove-Item Env:NANOBOT_ORGANIZATION_API_KEY -ErrorAction SilentlyContinue
    }

    $plainTextApiKey = $null
    $ApiKey = $null
}
