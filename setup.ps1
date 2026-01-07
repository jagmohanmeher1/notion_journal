# Quick setup script for Notion Journal
# This will help you set up the conda environment and configure the project

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Notion Journal - Setup Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if conda is available
try {
    $condaVersion = conda --version
    Write-Host "✓ Found Conda: $condaVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Conda not found. Please install Anaconda or Miniconda first." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 1: Creating conda environment..." -ForegroundColor Yellow
conda env create -f environment.yml

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Conda environment created successfully!" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to create conda environment" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 2: Activating environment and installing packages..." -ForegroundColor Yellow
conda activate notion-journal
pip install -r requirements.txt

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Packages installed successfully!" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to install packages" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 3: Setting up configuration..." -ForegroundColor Yellow

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "✓ Created .env file from template" -ForegroundColor Green
    Write-Host ""
    Write-Host "⚠ IMPORTANT: Please edit .env file and add your credentials:" -ForegroundColor Yellow
    Write-Host "  1. NOTION_TOKEN - from https://www.notion.so/my-integrations" -ForegroundColor White
    Write-Host "  2. NOTION_DATABASE_ID - from your Notion database URL" -ForegroundColor White
    Write-Host "  3. GITHUB_TOKEN (optional) - from https://github.com/settings/tokens" -ForegroundColor White
    Write-Host "  4. GITHUB_USERNAME (optional) - your GitHub username" -ForegroundColor White
    Write-Host "  5. PROJECT_PATHS - paths to scan (default: d:\projects)" -ForegroundColor White
} else {
    Write-Host "✓ .env file already exists" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Edit .env file with your credentials" -ForegroundColor White
Write-Host "2. Test the script: python notion_journal.py" -ForegroundColor White
Write-Host "3. Set up automation: .\setup_scheduler.ps1 (as Administrator)" -ForegroundColor White
Write-Host ""
