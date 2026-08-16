$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    & uv run python -m gal_radar.main digest --config "$RepoRoot\config.yaml" --database "$RepoRoot\data\gal_radar.db"
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
