param(
    [string]$TaskPrefix = "GalVNRadar"
)

$ErrorActionPreference = "Stop"
$TaskNames = @("$TaskPrefix-Fetch", "$TaskPrefix-Digest")

foreach ($name in $TaskNames) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Host "[$name]"
    Write-Host "State=$($task.State)"
    Write-Host "LastRunTime=$($info.LastRunTime)"
    Write-Host "LastTaskResult=$($info.LastTaskResult)"
    Write-Host "NextRunTime=$($info.NextRunTime)"
    Write-Host ""
}
