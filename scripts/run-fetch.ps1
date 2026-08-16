param(
    [string]$ConfigPath,
    [string]$DatabasePath,
    [switch]$DryRun
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
$args = @(
    "run",
    "--locked",
    "python",
    "-m",
    "gal_radar.main",
    "fetch",
    "--config",
    $ConfigPath,
    "--database",
    $DatabasePath
)
if ($DryRun) {
    $args += "--dry-run"
}

Push-Location $RepoRoot
try {
    & $Uv.Source @args
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $ExitCode
