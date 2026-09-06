param([switch]$NoClean)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCandidates = @(
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    (Get-Command py -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$pythonExecutable = $null
foreach ($cand in $pythonCandidates) {
    & $cand -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -eq 0) { $pythonExecutable = $cand; break }
}
if (-not $pythonExecutable) { throw 'Python with PyInstaller was not found.' }

$entry = Join-Path $appRoot 'desktop_geek.py'
if (-not (Test-Path -LiteralPath $entry)) { $entry = Join-Path $appRoot 'desktop.py' }
$buildRoot = Join-Path $appRoot '.build\pyinstaller'
$specRoot = Join-Path $appRoot '.build\spec'
New-Item -ItemType Directory -Path $buildRoot, $specRoot -Force | Out-Null

function Invoke-PyInstallerBuild {
    param(
        [Parameter(Mandatory=$true)][string]$Entry,
        [Parameter(Mandatory=$true)][string]$Name,
        [switch]$Windowed
    )
    $arguments = @(
        '-m', 'PyInstaller',
        $Entry,
        '--name', $Name,
        '--onefile',
        '--noupx',
        '--noconfirm',
        '--distpath', $appRoot,
        '--workpath', (Join-Path $buildRoot $Name),
        '--specpath', $specRoot
    )
    if ($Windowed) { $arguments += '--windowed' } else { $arguments += '--console' }
    if (-not $NoClean) { $arguments += '--clean' }
    & $pythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for $Name with exit code $LASTEXITCODE" }
}

Push-Location -LiteralPath $appRoot
try {
    Invoke-PyInstallerBuild -Entry $entry -Name 'AIHub' -Windowed
    Invoke-PyInstallerBuild -Entry (Join-Path $appRoot 'tools\model_sync.py') -Name 'AIHubModelSync'
    Invoke-PyInstallerBuild -Entry (Join-Path $appRoot 'tools\play_publish.py') -Name 'AIHubPlayPublish'
    Invoke-PyInstallerBuild -Entry (Join-Path $appRoot 'tools\google_sites_assist.py') -Name 'AIHubSitesAssist'
}
finally { Pop-Location }

$outputs = @('AIHub.exe','AIHubModelSync.exe','AIHubPlayPublish.exe','AIHubSitesAssist.exe')
foreach ($name in $outputs) {
    $output = Join-Path $appRoot $name
    if (-not (Test-Path -LiteralPath $output)) { throw "$name was not created." }
    $hash = Get-FileHash -LiteralPath $output -Algorithm SHA256
    Write-Host "$name SHA256: $($hash.Hash)"
}
Write-Host "Native desktop entry: $entry"
