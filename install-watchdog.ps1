$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$watchdog = Join-Path $appRoot 'watchdog.ps1'
$modelSync = Join-Path $appRoot 'sync-models.ps1'
if (-not (Test-Path -LiteralPath $watchdog)) { throw 'watchdog.ps1 not found.' }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell.exe -ArgumentList $args -Verb RunAs
    exit 0
}

$watchdogArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdog`""
$watchdogAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $watchdogArgs -WorkingDirectory $appRoot
$watchdogTrigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$principalSpec = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'AI Hub Watchdog' -Action $watchdogAction -Trigger $watchdogTrigger -Settings $settings -Principal $principalSpec -Force | Out-Null

if (Test-Path -LiteralPath $modelSync) {
    $syncAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$modelSync`"" -WorkingDirectory $appRoot
    $syncTrigger = New-ScheduledTaskTrigger -Daily -At 3:20am
    Register-ScheduledTask -TaskName 'AI Hub Model Sync' -Action $syncAction -Trigger $syncTrigger -Settings $settings -Principal $principalSpec -Force | Out-Null
}

Start-ScheduledTask -TaskName 'AI Hub Watchdog'
Write-Host 'Installed: AI Hub Watchdog (native desktop restart-on-exit loop)'
if (Test-Path -LiteralPath $modelSync) { Write-Host 'Installed: AI Hub Model Sync (daily)' }
