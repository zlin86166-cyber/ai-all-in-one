param(
    [switch]$InstallCli,
    [switch]$InstallRecommendedModel,
    [switch]$CreateDesktopShortcut,
    [switch]$InstallStartup
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeRoot = Join-Path $appRoot '.runtime'
$nodeRoot = Join-Path $runtimeRoot 'node'
$cliRoot = Join-Path $runtimeRoot 'cli'
New-Item -ItemType Directory -Path $runtimeRoot, $nodeRoot, $cliRoot -Force | Out-Null

function Resolve-AIHubNode {
    $systemNode = Get-Command node -ErrorAction SilentlyContinue
    if ($systemNode) { return $systemNode.Source }
    $portable = Get-ChildItem -LiteralPath $nodeRoot -Filter node.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($portable) { return $portable.FullName }
    return $null
}

function Install-AIHubPortableNode {
    Write-Host 'Downloading the latest Node.js LTS release...'
    $releases = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json'
    $release = $releases | Where-Object { $_.lts -and ($_.files -contains 'win-x64-zip') } | Select-Object -First 1
    if (-not $release) { throw 'No Windows x64 LTS archive was found in the official Node.js release list.' }
    $archiveName = "node-$($release.version)-win-x64.zip"
    $downloadUrl = "https://nodejs.org/dist/$($release.version)/$archiveName"
    $temporaryArchive = Join-Path ([IO.Path]::GetTempPath()) "ai-hub-$archiveName"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $temporaryArchive
    Expand-Archive -LiteralPath $temporaryArchive -DestinationPath $nodeRoot -Force
    Remove-Item -LiteralPath $temporaryArchive -Force
    $installed = Get-ChildItem -LiteralPath $nodeRoot -Filter node.exe -Recurse | Select-Object -First 1
    if (-not $installed) { throw 'node.exe was not found after extracting Node.js.' }
    return $installed.FullName
}

if (-not ($InstallCli -or $InstallRecommendedModel -or $CreateDesktopShortcut -or $InstallStartup)) {
    $InstallCli = $true
    $CreateDesktopShortcut = $true
    $InstallStartup = $true
}

if ($InstallCli) {
    $nodeExecutable = Resolve-AIHubNode
    if (-not $nodeExecutable) { $nodeExecutable = Install-AIHubPortableNode }
    $nodeDirectory = Split-Path -Parent $nodeExecutable
    $npmCommand = Join-Path $nodeDirectory 'npm.cmd'
    if (-not (Test-Path -LiteralPath $npmCommand)) { throw 'npm.cmd was not found.' }
    $env:PATH = "$nodeDirectory$([IO.Path]::PathSeparator)$env:PATH"
    Write-Host 'Installing Codex CLI and Gemini CLI into the private project runtime...'
    & $npmCommand --prefix $cliRoot install --no-audit --no-fund '@openai/codex@latest' '@google/gemini-cli@latest'
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
    $codexLauncher = Join-Path $cliRoot 'node_modules\.bin\codex.cmd'
    $geminiLauncher = Join-Path $cliRoot 'node_modules\.bin\gemini.cmd'
    if (-not (Test-Path -LiteralPath $codexLauncher)) { throw 'Codex CLI launcher is missing after installation.' }
    if (-not (Test-Path -LiteralPath $geminiLauncher)) { throw 'Gemini CLI launcher is missing after installation.' }
    Write-Host "Codex CLI: $codexLauncher"
    Write-Host "Gemini CLI: $geminiLauncher"
}

if ($InstallRecommendedModel) {
    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaCommand) { throw 'Ollama was not found. Install Ollama before downloading a local model.' }
    Write-Host 'Downloading DeepSeek R1 Distill 7B for local use...'
    & $ollamaCommand.Source pull 'deepseek-r1:7b'
    if ($LASTEXITCODE -ne 0) { throw "Ollama download failed with exit code $LASTEXITCODE" }
}

if ($CreateDesktopShortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop 'AI Hub.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = 'powershell.exe'
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $appRoot 'start.ps1')`""
    $shortcut.WorkingDirectory = $appRoot
    $desktopExecutable = Join-Path $appRoot 'AIHub.exe'
    $shortcut.IconLocation = if (Test-Path -LiteralPath $desktopExecutable) { "$desktopExecutable,0" } else { 'shell32.dll,14' }
    $shortcut.Description = 'AI Hub native local multi-model control deck'
    $shortcut.Save()
    Write-Host "Desktop shortcut: $shortcutPath"
}

if ($InstallStartup) {
    & (Join-Path $appRoot 'install-startup.ps1')
}

Write-Host 'Setup complete. Run start.cmd to open the native AI Hub desktop.'
