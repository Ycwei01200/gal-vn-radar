param(
    [string]$TaskPrefix = "GalVNRadar",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$FetchScript = Join-Path $PSScriptRoot "run-fetch.ps1"
$DigestScript = Join-Path $PSScriptRoot "run-digest.ps1"

$FetchTaskName = "$TaskPrefix-Fetch"
$DigestTaskName = "$TaskPrefix-Digest"

$existing = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.TaskName -in @($FetchTaskName, $DigestTaskName)
}
if ($existing -and -not $Force) {
    $names = ($existing.TaskName -join ", ")
    throw "Scheduled task(s) already exist: $names. Re-run with -Force to replace them."
}
if ($Force) {
    foreach ($task in $existing) {
        Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false
    }
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

$fetchAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$FetchScript`"" `
    -WorkingDirectory $RepoRoot

$fetchTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$digestAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$DigestScript`"" `
    -WorkingDirectory $RepoRoot

$digestTrigger = New-ScheduledTaskTrigger -Daily -At "20:00"

Register-ScheduledTask `
    -TaskName $FetchTaskName `
    -Action $fetchAction `
    -Trigger $fetchTrigger `
    -Settings $settings `
    -Description "Gal/VN Radar fetch every 30 minutes" `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName $DigestTaskName `
    -Action $digestAction `
    -Trigger $digestTrigger `
    -Settings $settings `
    -Description "Gal/VN Radar daily digest at 20:00" `
    -Force | Out-Null

Write-Host "Created scheduled tasks:"
Get-ScheduledTask -TaskName $FetchTaskName, $DigestTaskName |
    Select-Object TaskName, State |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Default registration uses the current user's interactive token."
Write-Host "Scheduled PowerShell windows are hidden."
Write-Host "To run while logged out, open Task Scheduler and select"
Write-Host "'Run whether user is logged on or not'; Windows will request your account password."
