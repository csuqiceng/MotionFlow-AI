[CmdletBinding()]
param(
    [string]$ReleaseDir = (Join-Path $PSScriptRoot "release-build4"),
    [int]$ChannelPort = 0,
    [int]$GatewayPort = 0
)

$ErrorActionPreference = "Stop"

function Get-FreeTcpPort {
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

if ($ChannelPort -eq 0) {
    $ChannelPort = Get-FreeTcpPort
}
if ($GatewayPort -eq 0) {
    do {
        $GatewayPort = Get-FreeTcpPort
    } while ($GatewayPort -eq $ChannelPort)
}
if ($ChannelPort -eq $GatewayPort) {
    throw "ChannelPort and GatewayPort must be different."
}

$source = Join-Path ([IO.Path]::GetFullPath($ReleaseDir)) "win-unpacked"
$scratch = Join-Path $env:TEMP (
    "nanobot packaged smoke contains spaces " + [guid]::NewGuid().ToString("N")
)
$appCopy = Join-Path $scratch "Nanobot App"
$runtime = Join-Path $scratch "runtime"
$process = $null
$previousEnvironment = @{}

try {
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Packaged application directory is missing: $source"
    }

    Copy-Item -LiteralPath $source -Destination $appCopy -Recurse
    New-Item -ItemType Directory -Path (Join-Path $runtime "robot_ai") -Force | Out-Null

    $asar = Join-Path $PSScriptRoot "node_modules\.bin\asar.cmd"
    if (-not (Test-Path -LiteralPath $asar -PathType Leaf)) {
        throw "asar.cmd is required for the packaged Gateway smoke test."
    }

    Push-Location $runtime
    try {
        & $asar extract-file (Join-Path $appCopy "resources\app.asar") `
            "electron/default-config.json"
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to extract the packaged default configuration."
        }
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
        (New-Object Text.UTF8Encoding($false))
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

    $gatewayExe = Join-Path $appCopy "resources\py-runtime\nanobot_gateway.exe"
    if (-not (Test-Path -LiteralPath $gatewayExe -PathType Leaf)) {
        throw "Packaged Gateway executable is missing: $gatewayExe"
    }

    foreach ($entry in $environment.GetEnumerator()) {
        $previousEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable(
            $entry.Key,
            [EnvironmentVariableTarget]::Process
        )
        [Environment]::SetEnvironmentVariable(
            $entry.Key,
            $entry.Value,
            [EnvironmentVariableTarget]::Process
        )
    }

    # Some CI/sandbox launchers inject both Path and PATH. .NET's
    # ProcessStartInfo treats them as duplicate keys, so normalize the process
    # environment before Start-Process builds its child environment block.
    $pathValue = [Environment]::GetEnvironmentVariable(
        "PATH",
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "Path",
        $null,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "PATH",
        $pathValue,
        [EnvironmentVariableTarget]::Process
    )

    $stdoutLog = Join-Path $scratch "gateway.stdout.log"
    $stderrLog = Join-Path $scratch "gateway.stderr.log"
    $process = Start-Process `
        -FilePath $gatewayExe `
        -ArgumentList @("--config", "`"$configPath`"") `
        -WorkingDirectory $appCopy `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    if ($null -eq $process) {
        throw "Unable to start the packaged Gateway."
    }

    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    do {
        Start-Sleep -Milliseconds 250
        if ($process.HasExited) {
            break
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$ChannelPort/webui/bootstrap" `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
            }
        }
        catch {
            if (
                $null -ne $_.Exception.Response -and
                [int]$_.Exception.Response.StatusCode -eq 401
            ) {
                $ready = $true
            }
        }
    } while (-not $ready -and (Get-Date) -lt $deadline)

    if (-not $ready) {
        if (-not $process.HasExited) {
            $process.Kill()
            $process.WaitForExit()
        }
        $stderr = Get-Content -LiteralPath $stderrLog -Raw -ErrorAction SilentlyContinue
        $stdout = Get-Content -LiteralPath $stdoutLog -Raw -ErrorAction SilentlyContinue
        throw "Packaged Gateway smoke test failed.`nSTDERR:`n$stderr`nSTDOUT:`n$stdout"
    }

    Write-Host "Packaged Gateway smoke test passed."
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        try {
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
        catch {
            # Restricted test environments can deny taskkill /T even when the
            # current process owns the Gateway. Fall back to the process API.
        }
        if (-not $process.HasExited) {
            $process.Kill()
        }
        $process.WaitForExit()
    }
    foreach ($entry in $previousEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable(
            $entry.Key,
            $entry.Value,
            [EnvironmentVariableTarget]::Process
        )
    }
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
}
