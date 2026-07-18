[CmdletBinding()]
param(
    [SecureString]$ApiKey
)

$ErrorActionPreference = "Stop"

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
$releaseDir = Join-Path $desktopDir "release-build4"
$locationPushed = $false
$plainTextApiKey = $null
$hadPreviousApiKey = Test-Path Env:NANOBOT_ORGANIZATION_API_KEY
$previousApiKey = $env:NANOBOT_ORGANIZATION_API_KEY

try {
    foreach ($requiredPath in @(
        $buildPython,
        (Join-Path $pyinstallerDir "nanobot.spec"),
        (Join-Path $desktopDir "..\nanobot\web\dist\index.html"),
        (Join-Path $desktopDir "..\vendor\zmotion\zauxdll.dll"),
        (Join-Path $desktopDir "..\vendor\zmotion\zmotion.dll"),
        (Join-Path $desktopDir "..\vendor\zmotion\zauxdllPython.py"),
        (Join-Path $desktopDir "electron\assets\nanobot-app-icon.ico"),
        (Join-Path $desktopDir "tools\rcedit-x64.exe"),
        (Join-Path $desktopDir "electron\config.default.template.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\positions.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\commands.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\flows.json"),
        (Join-Path $desktopDir "electron\defaults\robot_ai\knowledge.json"),
        (Join-Path $desktopDir "verify-release.ps1"),
        (Join-Path $desktopDir "smoke-packaged-gateway.ps1")
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
    Reset-BuildOutput -Path (Join-Path $pyinstallerDir "build") -AllowedRoot $desktopDir
    Reset-BuildOutput -Path (Join-Path $pyinstallerDir "dist") -AllowedRoot $desktopDir
    Reset-BuildOutput -Path $releaseDir -AllowedRoot $desktopDir

    $env:NANOBOT_ORGANIZATION_API_KEY = $plainTextApiKey

    Push-Location $desktopDir
    $locationPushed = $true

    Write-Host "Rebuilding the bundled Python gateway..."
    Push-Location $pyinstallerDir
    try {
        & $buildPython -m PyInstaller nanobot.spec --noconfirm --clean --distpath dist --workpath build
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller gateway build failed with exit code $LASTEXITCODE."
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

    Write-Host "Running packaged Gateway smoke test..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $desktopDir "smoke-packaged-gateway.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged Gateway smoke test failed with exit code $LASTEXITCODE."
    }

    $installer = Get-ChildItem -LiteralPath $releaseDir `
        -Filter "nanobot-robot-ai-Setup-*.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $installer) {
        throw "The installer was not found in release-build4."
    }

    $hashFile = "$($installer.FullName).sha256"
    if (-not (Test-Path -LiteralPath $hashFile -PathType Leaf)) {
        throw "Installer SHA-256 file was not generated."
    }

    $actualHash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
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
