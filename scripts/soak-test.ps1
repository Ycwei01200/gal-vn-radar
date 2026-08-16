param(
    [int]$Iterations = 10,
    [int]$IntervalSeconds = 60,
    [switch]$DryRun
)
if ($Iterations -lt 1) { throw "Iterations must be >= 1" }
if ($IntervalSeconds -lt 0) { throw "IntervalSeconds must be >= 0" }

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    for ($i = 1; $i -le $Iterations; $i++) {
        Write-Host "[$(Get-Date -Format o)] fetch $i/$Iterations"
        $args = @("run", "python", "-m", "gal_radar.main", "fetch", "--config", "$RepoRoot\config.yaml", "--database", "$RepoRoot\data\gal_radar.db")
        if ($DryRun) { $args += "--dry-run" }
        & uv @args
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($i -lt $Iterations) { Start-Sleep -Seconds $IntervalSeconds }
    }
    exit 0
}
finally {
    Pop-Location
}
