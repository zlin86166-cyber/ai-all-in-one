$ErrorActionPreference = 'Continue'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$dataRoot = Join-Path $appRoot 'data'
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
Set-Content -LiteralPath (Join-Path $dataRoot 'watchdog.stop') -Value (Get-Date -Format o) -Encoding UTF8
Stop-ScheduledTask -TaskName 'AI Hub Watchdog' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'AI Hub Watchdog' -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'AI Hub Model Sync' -Confirm:$false -ErrorAction SilentlyContinue
Write-Host 'AI Hub watchdog/model-sync tasks removed.'
