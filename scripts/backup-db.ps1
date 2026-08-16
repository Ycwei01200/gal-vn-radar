$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    & uv run python -m gal_radar.main backup --database "$RepoRoot\data\gal_radar.db" --output "$RepoRoot\backups"
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
