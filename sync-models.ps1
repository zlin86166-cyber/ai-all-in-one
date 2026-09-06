$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$helper = Join-Path $appRoot 'AIHubModelSync.exe'
Push-Location -LiteralPath $appRoot
try {
    if (Test-Path -LiteralPath $helper) {
        & $helper --output 'data/latest-models.json'
    }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
        if (-not $python) { throw 'AIHubModelSync.exe and Python were both unavailable.' }
        & $python.Source (Join-Path $appRoot 'tools\model_sync.py') --output 'data/latest-models.json'
    }
    if ($LASTEXITCODE -ne 0) { throw "model sync failed: $LASTEXITCODE" }
}
finally { Pop-Location }
