param(
    [switch]$Web,
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$NoElevate
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $NoElevate -and -not $isAdministrator) {
    $restartArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -NoElevate"
    if ($Web) { $restartArguments += ' -Web' }
    if ($NoBrowser) { $restartArguments += ' -NoBrowser' }
    $restartArguments += " -Port $Port"
    Start-Process -FilePath 'powershell.exe' -ArgumentList $restartArguments -Verb RunAs -WindowStyle Hidden
    exit 0
}

$runtimeRoot = Join-Path $appRoot '.runtime'
$cliBin = Join-Path $runtimeRoot 'cli\node_modules\.bin'
$openAIBin = Join-Path $runtimeRoot 'openai-cli'
$pathParts = [System.Collections.Generic.List[string]]::new()
if (Test-Path -LiteralPath $cliBin) { $pathParts.Add($cliBin) }
if (Test-Path -LiteralPath $openAIBin) { $pathParts.Add($openAIBin) }
$portableNode = Get-ChildItem -LiteralPath (Join-Path $runtimeRoot 'node') -Filter node.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($portableNode) { $pathParts.Add($portableNode.Directory.FullName) }
$bundledNode = 'C:\Users\ASUS\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin'
if (Test-Path -LiteralPath $bundledNode) { $pathParts.Add($bundledNode) }
if ($pathParts.Count -gt 0) { $env:PATH = (($pathParts -join [IO.Path]::PathSeparator) + [IO.Path]::PathSeparator + $env:PATH) }
$env:PYTHONUTF8 = '1'

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pythonCommand) { throw 'Python 3.11 or newer was not found.' }

Push-Location -LiteralPath $appRoot
try {
    if ($Web) {
        $arguments = @((Join-Path $appRoot 'app.py'), '--port', $Port)
        if ($NoBrowser) { $arguments += '--no-browser' }
        & $pythonCommand.Source @arguments
    }
    else {
        $desktopExecutable = Join-Path $appRoot 'AIHub.exe'
        if (Test-Path -LiteralPath $desktopExecutable) {
            & $desktopExecutable '--max-control'
        }
        else {
            $pythonWindow = Get-Command pythonw -ErrorAction SilentlyContinue
            if ($pythonWindow) {
                & $pythonWindow.Source (Join-Path $appRoot 'desktop.py') '--max-control'
            }
            else {
                & $pythonCommand.Source (Join-Path $appRoot 'desktop.py') '--max-control'
            }
        }
    }
}
finally {
    Pop-Location
}
