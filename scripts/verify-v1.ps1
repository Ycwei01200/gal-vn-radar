$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Failures = New-Object System.Collections.Generic.List[string]

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host "== $Name =="
    try {
        & $Action
        if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
        Write-Host "PASS: $Name"
    }
    catch {
        $Failures.Add("$Name`: $($_.Exception.Message)")
        Write-Host "FAIL: $Name - $($_.Exception.Message)"
    }
}

Push-Location $RepoRoot
try {
    Invoke-Check "pytest" { & uv run --locked pytest }
    Invoke-Check "ruff" { & uv run --locked ruff check . }
    Invoke-Check "dependency audit" { & uv audit --locked }
    Invoke-Check "git diff --check" { & git diff --check }
    Invoke-Check "status" {
        & uv run --locked python -m gal_radar.main status `
            --config "$RepoRoot\config.yaml" `
            --database "$RepoRoot\data\gal_radar.db"
    }
    Invoke-Check "doctor" {
        & uv run --locked python -m gal_radar.main doctor `
            --config "$RepoRoot\config.yaml" `
            --database "$RepoRoot\data\gal_radar.db"
    }
    Invoke-Check "Telegram command dry-run" {
        & uv run --locked python -m gal_radar.main test-telegram --dry-run
    }
    Invoke-Check "fetch runner dry-run" {
        & "$RepoRoot\scripts\run-fetch.ps1" -DryRun
    }
    Invoke-Check "digest runner dry-run" {
        & "$RepoRoot\scripts\run-digest.ps1" -DryRun
    }
    Invoke-Check "scheduled tasks" {
        $Tasks = @(
            Get-ScheduledTask -TaskName "GalVNRadar-Fetch" -ErrorAction Stop,
            Get-ScheduledTask -TaskName "GalVNRadar-Digest" -ErrorAction Stop
        )
        foreach ($Task in $Tasks) {
            if ($Task.State -eq "Disabled") {
                throw "$($Task.TaskName) is disabled"
            }
            Write-Host "$($Task.TaskName): $($Task.State)"
        }
    }

    $LogPath = Join-Path $RepoRoot "logs\gal-radar.log"
    if (Test-Path $LogPath) {
        Write-Host "Recent log lines:"
        Get-Content $LogPath -Tail 10
    }
    else {
        $Failures.Add("runtime log missing: $LogPath")
        Write-Host "FAIL: runtime log missing"
    }
}
finally {
    Pop-Location
}

if ($Failures.Count -gt 0) {
    Write-Host ""
    Write-Host "v1 verification FAILED"
    foreach ($Failure in $Failures) {
        Write-Host "- $Failure"
    }
    exit 1
}

Write-Host ""
Write-Host "v1 verification PASSED"
exit 0
