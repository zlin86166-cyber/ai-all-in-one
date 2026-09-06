param(
    [int]$RestartDelaySeconds = 8,
    [switch]$Web
)

$ErrorActionPreference = 'Continue'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$dataRoot = Join-Path $appRoot 'data'
$stopFile = Join-Path $dataRoot 'watchdog.stop'
$logFile = Join-Path $dataRoot 'watchdog.log'
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

function Write-WatchdogLog([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

Write-WatchdogLog 'watchdog started'
while (-not (Test-Path -LiteralPath $stopFile)) {
    try {
        Write-WatchdogLog 'launching AI Hub'
        $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $appRoot 'start.ps1'), '-NoElevate')
        if ($Web) { $arguments += '-Web' }
        $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $appRoot -PassThru
        $process.WaitForExit()
        Write-WatchdogLog "AI Hub exited code=$($process.ExitCode)"
    }
    catch {
        Write-WatchdogLog "launch failed: $($_.Exception.Message)"
    }
    if (-not (Test-Path -LiteralPath $stopFile)) {
        Start-Sleep -Seconds ([Math]::Max(3, $RestartDelaySeconds))
    }
}
Write-WatchdogLog 'watchdog stopped by marker'
