param(
    [switch]$Source,
    [switch]$Elevate,
    [switch]$MaxControl,
    [switch]$NoElevate,
    [switch]$SafeMode,
    [switch]$PreferExe,
    [switch]$Web,
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Web) {
    throw 'AI Hub Web mode is no longer a supported product surface. Launch the native Windows desktop app instead.'
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Elevate -and -not $isAdministrator) {
    $restartArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Elevate"
    if ($Source) { $restartArguments += ' -Source' }
    if ($MaxControl) { $restartArguments += ' -MaxControl' }
    if ($SafeMode) { $restartArguments += ' -SafeMode' }
    Start-Process -FilePath 'powershell.exe' -ArgumentList $restartArguments -Verb RunAs
    exit 0
}

$runtimeRoot = Join-Path $appRoot '.runtime'
$cliBin = Join-Path $runtimeRoot 'cli\node_modules\.bin'
$openAIBin = Join-Path $runtimeRoot 'openai-cli'
$pathParts = [System.Collections.Generic.List[string]]::new()
if (Test-Path -LiteralPath $cliBin) { $pathParts.Add($cliBin) }
if (Test-Path -LiteralPath $openAIBin) { $pathParts.Add($openAIBin) }
$portableNodeRoot = Join-Path $runtimeRoot 'node'
if (Test-Path -LiteralPath $portableNodeRoot) {
    $portableNode = Get-ChildItem -LiteralPath $portableNodeRoot -Filter node.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($portableNode) { $pathParts.Add($portableNode.Directory.FullName) }
}
if ($pathParts.Count -gt 0) {
    $env:PATH = (($pathParts -join [IO.Path]::PathSeparator) + [IO.Path]::PathSeparator + $env:PATH)
}
$env:PYTHONUTF8 = '1'

Push-Location -LiteralPath $appRoot
try {
    $desktopExecutable = Join-Path $appRoot 'AIHub.exe'
    $arguments = @()
    if ($MaxControl) { $arguments += '--max-control' }
    elseif ($SafeMode -or $NoElevate) { $arguments += '--safe-mode' }

    if (-not $Source -and (Test-Path -LiteralPath $desktopExecutable)) {
        & $desktopExecutable @arguments
        exit $LASTEXITCODE
    }

    $pythonWindow = Get-Command pythonw -ErrorAction SilentlyContinue
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { $pythonCommand = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $pythonWindow -and -not $pythonCommand) {
        throw 'AIHub.exe was not found and Python 3.11 or newer is not installed. Download the Windows release package or rebuild AIHub.exe.'
    }
    $entry = Join-Path $appRoot 'desktop.py'
    if ($pythonWindow) { & $pythonWindow.Source $entry @arguments }
    else { & $pythonCommand.Source $entry @arguments }
}
finally {
    Pop-Location
}
