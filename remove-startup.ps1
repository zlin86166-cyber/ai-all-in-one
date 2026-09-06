$ErrorActionPreference = 'Stop'
$taskName = 'AI Hub Local Workspace'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed: $taskName"
}
else {
    Write-Host 'AI Hub startup task was not found.'
}
