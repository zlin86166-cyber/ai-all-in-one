param(
    [switch]$InstallCli,
    [switch]$InstallRecommendedModel,
    [switch]$CreateDesktopShortcut,
    [switch]$InstallStartup,
    [switch]$InstallWatchdog
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

if (-not ($InstallCli -or $InstallRecommendedModel -or $CreateDesktopShortcut -or $InstallStartup -or $InstallWatchdog)) {
    $InstallCli = $true
    $CreateDesktopShortcut = $true
}

if ($InstallCli) {
    $nodeExecutable = Resolve-AIHubNode
    if (-not $nodeExecutable) { $nodeExecutable = Install-AIHubPortableNode }
    $nodeDirectory = Split-Path -Parent $nodeExecutable
    $npmCommand = Join-Path $nodeDirectory 'npm.cmd'
    if (-not (Test-Path -LiteralPath $npmCommand)) { throw 'npm.cmd was not found.' }
    $env:PATH = "$nodeDirectory$([IO.Path]::PathSeparator)$env:PATH"
    $codexVersion = if ($env:AI_HUB_CODEX_VERSION) { $env:AI_HUB_CODEX_VERSION } else { '0.153.4' }
    $geminiVersion = if ($env:AI_HUB_GEMINI_VERSION) { $env:AI_HUB_GEMINI_VERSION } else { '0.58.0' }
    Write-Host "Installing tested CLI versions: Codex $codexVersion / Gemini $geminiVersion"
    & $npmCommand --prefix $cliRoot install --save-exact --no-audit --no-fund "@openai/codex@$codexVersion" "@google/gemini-cli@$geminiVersion"
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
    $codexLauncher = Join-Path $cliRoot 'node_modules\.bin\codex.cmd'
    $geminiLauncher = Join-Path $cliRoot 'node_modules\.bin\gemini.cmd'
    if (-not (Test-Path -LiteralPath $codexLauncher)) { throw 'Codex CLI launcher is missing after installation.' }
    if (-not (Test-Path -LiteralPath $geminiLauncher)) { throw 'Gemini CLI launcher is missing after installation.' }
    Write-Host "Codex CLI: $codexLauncher"
    Write-Host "Gemini CLI: $geminiLauncher"

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        Write-Host 'Installing/updating Hugging Face CLI for optional model-weight downloads...'
        & $python.Source -m pip install --disable-pip-version-check --upgrade 'huggingface_hub[cli]'
        if ($LASTEXITCODE -ne 0) { Write-Warning 'huggingface_hub installation failed; metadata sync still works, direct HF download may require a separate Python environment.' }
    }
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
    $desktopExecutable = Join-Path $appRoot 'AIHub.exe'
    if (Test-Path -LiteralPath $desktopExecutable) {
        $shortcut.TargetPath = $desktopExecutable
        $shortcut.Arguments = ''
        $shortcut.IconLocation = "$desktopExecutable,0"
    }
    else {
        $shortcut.TargetPath = 'powershell.exe'
        $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $appRoot 'start.ps1')`" -Source"
        $shortcut.IconLocation = 'shell32.dll,14'
    }
    $shortcut.WorkingDirectory = $appRoot
    $shortcut.Description = 'AI Hub local multi-model operator console'
    $shortcut.Save()
    Write-Host "Desktop shortcut: $shortcutPath"
}

if ($InstallStartup -and -not $InstallWatchdog) {
    & (Join-Path $appRoot 'install-startup.ps1')
}
if ($InstallWatchdog) {
    & (Join-Path $appRoot 'install-watchdog.ps1')
}

Write-Host 'Setup complete.'
$desktopExecutable = Join-Path $appRoot 'AIHub.exe'
if (Test-Path -LiteralPath $desktopExecutable) {
    Write-Host 'Launch AIHub.exe to work locally.'
}
else {
    Write-Host 'AIHub.exe is not present; use start.ps1 -Source for source development.'
}
