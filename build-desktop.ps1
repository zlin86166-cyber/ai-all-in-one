param([switch]$NoClean)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCandidates = @(
    'C:\Users\ASUS\AppData\Local\Programs\Python\Python313\python.exe',
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    (Get-Command py -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$pythonExecutable = $null
foreach ($cand in $pythonCandidates) {
    & $cand -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -eq 0) { $pythonExecutable = $cand; break }
}
if (-not $pythonExecutable) { throw 'Python with PyInstaller was not found.' }

$buildRoot = Join-Path $appRoot '.build\pyinstaller'
$specRoot = Join-Path $appRoot '.build\spec'
New-Item -ItemType Directory -Path $buildRoot, $specRoot -Force | Out-Null

$arguments = @(
    '-m', 'PyInstaller',
    (Join-Path $appRoot 'desktop.py'),
    '--name', 'AIHub',
    '--onefile',
    '--windowed',
    '--uac-admin',
    '--noupx',
    '--noconfirm',
    '--distpath', $appRoot,
    '--workpath', $buildRoot,
    '--specpath', $specRoot
)
if (-not $NoClean) { $arguments += '--clean' }

Push-Location -LiteralPath $appRoot
try {
    & $pythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}

$output = Join-Path $appRoot 'AIHub.exe'
if (-not (Test-Path -LiteralPath $output)) { throw 'AIHub.exe was not created.' }
$hash = Get-FileHash -LiteralPath $output -Algorithm SHA256
Write-Host "Desktop executable: $output"
Write-Host "SHA256: $($hash.Hash)"
