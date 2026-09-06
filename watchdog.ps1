param([int]$RestartDelaySeconds = 8,[switch]$Web)
$ErrorActionPreference='Continue'; $appRoot=Split-Path -Parent $MyInvocation.MyCommand.Path; $dataRoot=Join-Path $appRoot 'data'
$stopFile=Join-Path $dataRoot 'watchdog.stop'; $normalExit=Join-Path $dataRoot 'normal-exit.marker'; $logFile=Join-Path $dataRoot 'watchdog.log'
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null; Remove-Item $stopFile -Force -ErrorAction SilentlyContinue
function Write-WatchdogLog([string]$Message){
  if((Test-Path $logFile) -and (Get-Item $logFile).Length -gt 5MB){ Move-Item $logFile (Join-Path $dataRoot ("watchdog-"+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')) -Force }
  Add-Content $logFile -Value "$(Get-Date -Format o) $Message" -Encoding UTF8
}
$crashes=New-Object System.Collections.Generic.List[datetime]; Write-WatchdogLog 'watchdog started'
while(-not (Test-Path $stopFile)){
  Remove-Item $normalExit -Force -ErrorAction SilentlyContinue
  try{
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $appRoot 'start.ps1'),'-NoElevate'); if($Web){$arguments+='-Web'}
    $process=Start-Process powershell.exe -ArgumentList $arguments -WorkingDirectory $appRoot -PassThru; $process.WaitForExit(); Write-WatchdogLog "AI Hub exited code=$($process.ExitCode)"
  }catch{ Write-WatchdogLog "launch failed: $($_.Exception.Message)" }
  if(Test-Path $normalExit){ Write-WatchdogLog 'normal user shutdown detected; watchdog stops'; break }
  $now=Get-Date; $crashes.Add($now); for($i=$crashes.Count-1;$i-ge 0;$i--){if(($now-$crashes[$i]).TotalMinutes -gt 5){$crashes.RemoveAt($i)}}
  if($crashes.Count -ge 5){ Write-WatchdogLog 'crash loop protection: 5 exits within 5 minutes; manual recovery required'; break }
  if(-not (Test-Path $stopFile)){ Start-Sleep -Seconds ([Math]::Max(3,$RestartDelaySeconds)) }
}
Write-WatchdogLog 'watchdog stopped'
