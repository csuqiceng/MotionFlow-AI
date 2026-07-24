[CmdletBinding()]
param(
    [string]$ReleaseDir,
    [int]$ServerPort = 0
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ReleaseDir)) {
    # Parameter defaults are evaluated before $PSScriptRoot is initialized
    # when this script is invoked by another PowerShell host.
    $ReleaseDir = Join-Path $PSScriptRoot "release2"
}
function Get-FreeTcpPort {
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    try { $listener.Start(); return ([Net.IPEndPoint]$listener.LocalEndpoint).Port }
    finally { $listener.Stop() }
}
if ($ServerPort -eq 0) { $ServerPort = Get-FreeTcpPort }

$source = Join-Path ([IO.Path]::GetFullPath($ReleaseDir)) "win-unpacked"
$scratch = Join-Path $env:TEMP ("robot-server packaged smoke contains spaces " + [guid]::NewGuid().ToString("N"))
$appCopy = Join-Path $scratch "Robot Server App"
$runtime = Join-Path $scratch "runtime"
$process = $null
try {
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "Packaged application directory is missing: $source" }
    Copy-Item -LiteralPath $source -Destination $appCopy -Recurse
    New-Item -ItemType Directory -Path (Join-Path $runtime "robot_platform") -Force | Out-Null
    $asar = Join-Path $PSScriptRoot "node_modules\.bin\asar.cmd"
    if (-not (Test-Path -LiteralPath $asar -PathType Leaf)) { throw "asar.cmd is required for smoke test." }
    Push-Location $runtime
    try {
        & $asar extract-file (Join-Path $appCopy "resources\app.asar") "electron/default-config.json"
        if ($LASTEXITCODE -ne 0) { throw "Unable to extract packaged default configuration." }
        Move-Item -LiteralPath "default-config.json" -Destination "config.json"
    } finally { Pop-Location }
    Copy-Item -Path (Join-Path $appCopy "resources\defaults\robot_platform\*") -Destination (Join-Path $runtime "robot_platform") -Recurse -Force
    $serverExe = Join-Path $appCopy "resources\py-runtime\robot_server.exe"
    if (-not (Test-Path -LiteralPath $serverExe -PathType Leaf)) { throw "Packaged robot-server executable is missing: $serverExe" }
    $env:NANOBOT_HOME = $runtime; $env:NANOBOT_DEFAULTS_DIR = (Join-Path $appCopy "resources\defaults"); $env:NANOBOT_INITIAL_SEED = "1"; $env:ROBOT_AI_BACKEND = "simulation"
    $stdoutLog = Join-Path $scratch "robot-server.stdout.log"; $stderrLog = Join-Path $scratch "robot-server.stderr.log"
    # Start-Process joins its argument array into one command line.  Preserve
    # quotes around this deliberately space-containing smoke-test path so the
    # bundled executable receives one --config value on Windows.
    $configArgument = '"{0}"' -f (Join-Path $runtime "config.json")
    $process = Start-Process -FilePath $serverExe -ArgumentList @("--port", [string]$ServerPort, "--config", $configArgument) -WorkingDirectory $appCopy -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
    $deadline = (Get-Date).AddSeconds(60); $ready = $false
    do {
        Start-Sleep -Milliseconds 250
        if ($process.HasExited) { break }
        try { $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$ServerPort/health" -TimeoutSec 2; $ready = $response.StatusCode -eq 200 } catch { }
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) { throw "Packaged robot-server smoke test failed. STDERR: $((Get-Content $stderrLog -Raw -ErrorAction SilentlyContinue))" }
    $page = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$ServerPort/" -TimeoutSec 5
    if ($page.Content -notmatch '<title>[^<]+</title>' -or $page.Content -notmatch 'id="root"') {
        throw "Robot single-page UI was not served."
    }
    if ($page.Content -match "nanobot web UI") {
        throw "Packaged entry page still contains the retired Nanobot description."
    }
    Write-Host "Packaged robot-server smoke test passed."
}
finally {
    if ($null -ne $process -and -not $process.HasExited) { & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null; if (-not $process.HasExited) { $process.Kill() }; $process.WaitForExit() }
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
}
