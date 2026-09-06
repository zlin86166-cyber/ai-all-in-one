$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Python not found.' }
Push-Location -LiteralPath $appRoot
try {
    & $python.Source (Join-Path $appRoot 'tools\model_sync.py') --output 'data/latest-models.json'
    if ($LASTEXITCODE -ne 0) { throw "model sync failed: $LASTEXITCODE" }
}
finally { Pop-Location }
