param(
    [string]$ConfigPath,
    [string]$DatabasePath
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $RepoRoot "config.yaml"
}
if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    $DatabasePath = Join-Path $RepoRoot "data\gal_radar.db"
}

if ([string]::IsNullOrWhiteSpace($env:TELEGRAM_BOT_TOKEN)) {
    $env:TELEGRAM_BOT_TOKEN = [Environment]::GetEnvironmentVariable(
        "TELEGRAM_BOT_TOKEN",
        "User"
    )
}
if ([string]::IsNullOrWhiteSpace($env:TELEGRAM_CHAT_ID)) {
    $env:TELEGRAM_CHAT_ID = [Environment]::GetEnvironmentVariable(
        "TELEGRAM_CHAT_ID",
        "User"
    )
}

$Uv = Get-Command uv -ErrorAction Stop

Push-Location $RepoRoot
try {
    & $Uv.Source run python -m gal_radar.main digest `
        --config $ConfigPath `
        --database $DatabasePath
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $ExitCode
