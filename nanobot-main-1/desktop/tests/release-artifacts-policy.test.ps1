$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$gitRoot = (& git -C $desktopDir rev-parse --show-toplevel).Trim()
if (-not $gitRoot) {
    throw "Unable to locate the Git repository root."
}

$desktopRelative = (& git -C $desktopDir rev-parse --show-prefix).Trim().TrimEnd("/")
$releasePath = "$desktopRelative/release-build4"
$electronShimPath = "$desktopRelative/electron.exe"

$ignoredProbe = "$releasePath/policy-probe.bin"
& git -C $gitRoot check-ignore --quiet -- $ignoredProbe
if ($LASTEXITCODE -ne 0) {
    throw "$releasePath must be ignored."
}

$trackedReleaseFiles = @(& git -C $gitRoot ls-files -- $releasePath)
if ($trackedReleaseFiles.Count -gt 0) {
    throw "$releasePath still contains $($trackedReleaseFiles.Count) tracked files."
}

$trackedElectronShim = @(& git -C $gitRoot ls-files -- $electronShimPath)
if ($trackedElectronShim.Count -gt 0) {
    throw "$electronShimPath must not be tracked."
}

if (Test-Path -LiteralPath (Join-Path $desktopDir "electron.exe")) {
    throw "Unexpected desktop/electron.exe shim still exists."
}

Write-Host "release artifact policy checks passed."
