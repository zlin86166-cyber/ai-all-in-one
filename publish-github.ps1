param(
    [string]$RemoteUrl = "https://github.com/zlin86166-cyber/ai-all-in-one.git",
    [string]$Branch = "main",
    [string]$CommitMessage = "feat: AI Hub 純白極簡 Windows 多模型控制台 (Codex CLI, Gemini CLI, Ollama, 50B Kimi & DeepSeek)"
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Ensure git is available
$gitPath = 'C:\Users\ASUS\AppData\Local\Programs\Git\cmd\git.exe'
if (-not (Test-Path -LiteralPath $gitPath)) {
    $found = Get-Command git -ErrorAction SilentlyContinue
    if ($found) { $gitPath = $found.Source }
    else { throw "Git was not found. Please install Git first." }
}

Push-Location -LiteralPath $appRoot
try {
    Write-Host "Checking git repository in $appRoot..."
    if (-not (Test-Path -LiteralPath (Join-Path $appRoot '.git'))) {
        Write-Host "Initializing git repository..."
        & $gitPath init -b $Branch
    }

    # Set user info if not already configured
    $userName = & $gitPath config user.name
    if (-not $userName) {
        & $gitPath config user.name "zlin86166-cyber"
    }
    $userEmail = & $gitPath config user.email
    if (-not $userEmail) {
        & $gitPath config user.email "zlin86166-cyber@users.noreply.github.com"
    }

    # Configure remote
    $remotes = & $gitPath remote
    if ($remotes -contains 'origin') {
        Write-Host "Updating remote origin: $RemoteUrl"
        & $gitPath remote set-url origin $RemoteUrl
    } else {
        Write-Host "Adding remote origin: $RemoteUrl"
        & $gitPath remote add origin $RemoteUrl
    }

    Write-Host "Staging files..."
    & $gitPath add -A

    $status = & $gitPath status --porcelain
    if ($status) {
        Write-Host "Committing changes..."
        & $gitPath commit -m $CommitMessage
    } else {
        Write-Host "Working tree clean, nothing new to commit."
    }

    Write-Host "Pushing to $RemoteUrl ($Branch)..."
    & $gitPath push -u origin $Branch

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Successfully published to GitHub: $RemoteUrl" -ForegroundColor Green
    } else {
        Write-Warning "Push failed. Please ensure you have write access or personal access token configured."
    }
}
finally {
    Pop-Location
}
