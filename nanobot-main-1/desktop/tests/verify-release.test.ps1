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
        "nanobot-robot-ai-Setup-0.1.0.exe"
    )
    foreach ($relative in $required) {
        $path = Join-Path $release $relative
        New-Item -ItemType Directory -Path (Split-Path $path) -Force | Out-Null
        [IO.File]::WriteAllBytes($path, [byte[]](1, 2, 3))
    }

    foreach ($jsonName in @("positions.json", "commands.json", "flows.json", "knowledge.json")) {
        $jsonPath = Join-Path $resources "defaults\robot_ai\$jsonName"
        $jsonPayload = if ($jsonName -eq "commands.json") {
            $nonAsciiDescription = [string][char]0x5b89 + [char]0x5168 + [char]0x3002
            '{"description":"' + $nonAsciiDescription + '"}'
        }
        else {
            "{}"
        }
        [IO.File]::WriteAllText(
            $jsonPath,
            $jsonPayload,
            [Text.UTF8Encoding]::new($false)
        )
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

    $defaultVerifier = Join-Path $fixture "verify-release.ps1"
    Copy-Item -LiteralPath $verifier -Destination $defaultVerifier
    Copy-Item -LiteralPath (Join-Path $desktopDir "package.json") `
        -Destination (Join-Path $fixture "package.json")
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File $defaultVerifier -SkipExecutableMetadata -SkipAsarInspection
    if ($LASTEXITCODE -ne 0) {
        throw "Verifier must support invocation without -ReleaseDir."
    }

    Write-Host "release verifier tests passed."
}
finally {
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
