$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Version = ""
$Notes = ""
$Channel = "user"
$CdnBaseUrl = "https://www.twsaimahui.com/startrace/user"
$PrivateKey = "keys\update_private.pem"
$SshHost = "root@207.56.3.82"
$SshPort = "29618"
$RemoteDir = "/www/wwwroot/www.twsaimahui.com/startrace/user"

function Read-BatchValue {
    param(
        [string]$Path,
        [string]$Name
    )
    if (-not (Test-Path $Path)) {
        return ""
    }
    $pattern = '^\s*set\s+"' + [regex]::Escape($Name) + '=(.*)"\s*$'
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match $pattern) {
            return $Matches[1]
        }
    }
    return ""
}

if (Test-Path "release_user_config.ps1") {
    . ".\release_user_config.ps1"
} elseif (Test-Path "release_user_config.bat") {
    $Version = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_VERSION"
    $Notes = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_NOTES"
    $Channel = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_CHANNEL"
    $CdnBaseUrl = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_CDN_BASE_URL"
    $PrivateKey = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_PRIVATE_KEY"
    $SshHost = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_SSH_HOST"
    $SshPort = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_SSH_PORT"
    $RemoteDir = Read-BatchValue "release_user_config.bat" "STARTRACE_RELEASE_REMOTE_DIR"
} elseif (Test-Path "release_user_config.ps1.example") {
    . ".\release_user_config.ps1.example"
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    throw "Version is missing. Set `$Version in release_user_config.ps1 or STARTRACE_RELEASE_VERSION in release_user_config.bat."
}
if ([string]::IsNullOrWhiteSpace($Notes)) {
    throw "Notes is missing. Set `$Notes in release_user_config.ps1 or STARTRACE_RELEASE_NOTES in release_user_config.bat."
}
if ([string]::IsNullOrWhiteSpace($Channel)) { $Channel = "user" }
if ([string]::IsNullOrWhiteSpace($CdnBaseUrl)) { $CdnBaseUrl = "https://www.twsaimahui.com/startrace/user" }
if ([string]::IsNullOrWhiteSpace($PrivateKey)) { $PrivateKey = "keys\update_private.pem" }
if ([string]::IsNullOrWhiteSpace($SshHost)) { $SshHost = "root@207.56.3.82" }
if ([string]::IsNullOrWhiteSpace($SshPort)) { $SshPort = "29618" }
if ([string]::IsNullOrWhiteSpace($RemoteDir)) { $RemoteDir = "/www/wwwroot/www.twsaimahui.com/startrace/user" }

$env:STARTRACE_VERSION = $Version
$env:STARTRACE_BUILD_ID = "startrace_{0:yyyyMMddHHmmss}" -f (Get-Date)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

Write-Host "[1/5] Building StarTrace user edition $Version..."
& ".venv\Scripts\python.exe" "tools\build.py" "--clean"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Artifact = "dist\StarTrace-$Version.exe"
if (-not (Test-Path $Artifact)) {
    throw "Artifact not found: $Artifact"
}

Write-Host "[2/5] Generating latest.json..."
& ".venv\Scripts\python.exe" "tools\release_manifest.py" `
    "--artifact" "dist\StarTrace-$Version.exe" `
    "--channel" $Channel `
    "--version" $Version `
    "--base-url" $CdnBaseUrl `
    "--private-key" $PrivateKey `
    "--notes" $Notes `
    "--output" "dist\latest.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path "dist\latest.json")) {
    throw "Manifest not found: dist\latest.json"
}

Write-Host "[3/5] Ensuring remote directory exists..."
& ssh "-p" $SshPort $SshHost "mkdir -p $RemoteDir"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/5] Uploading exe..."
& scp "-P" $SshPort "dist\StarTrace-$Version.exe" "${SshHost}:$RemoteDir/StarTrace-$Version.exe"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[5/5] Uploading latest.json..."
& scp "-P" $SshPort "dist\latest.json" "${SshHost}:$RemoteDir/latest.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Release completed:"
Write-Host "  https://www.twsaimahui.com/startrace/user/StarTrace-$Version.exe"
Write-Host "  https://www.twsaimahui.com/startrace/user/latest.json"
