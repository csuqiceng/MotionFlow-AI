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

$desktopDir = Split-Path -Parent $PSCommandPath
$pyinstallerDir = Join-Path $desktopDir "pyinstaller"
$buildPython = Join-Path $desktopDir ".build-venv\Scripts\python.exe"
$generatedConfig = Join-Path $desktopDir "electron\default-config.json"
$locationPushed = $false
$plainTextApiKey = $null
$hadPreviousApiKey = Test-Path Env:NANOBOT_ORGANIZATION_API_KEY
$previousApiKey = $env:NANOBOT_ORGANIZATION_API_KEY

try {
    if ($null -eq $ApiKey) {
        $ApiKey = Read-Host "Enter the organization API key to embed" -AsSecureString
    }

    $plainTextApiKey = ConvertTo-PlainText -Value $ApiKey
    if ([string]::IsNullOrWhiteSpace($plainTextApiKey)) {
        throw "An API key is required."
    }

    foreach ($requiredPath in @(
        $buildPython,
        (Join-Path $desktopDir "pyinstaller\dist\py-runtime\nanobot_gateway.exe"),
        (Join-Path $pyinstallerDir "nanobot.spec"),
        (Join-Path $desktopDir "..\vendor\zmotion"),
        (Join-Path $desktopDir "electron\config.default.template.json")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Required packaging resource is missing: $requiredPath"
        }
    }

    $npmCommand = Get-Command "npm.cmd" -ErrorAction Stop
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

    $installer = Get-ChildItem -LiteralPath (Join-Path $desktopDir "release-build4") `
        -Filter "nanobot-robot-ai-Setup-*.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $installer) {
        throw "The installer was not found in release-build4."
    }

    Write-Host "Package created: $($installer.FullName)"
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
