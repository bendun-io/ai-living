param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if ($Clean -and (Test-Path "dist")) {
    Write-Host "Cleaning dist folder..." -ForegroundColor Yellow
    Remove-Item "dist" -Recurse -Force
}

Write-Host "Installing/updating npm dependencies..." -ForegroundColor Cyan
npm install

Write-Host "Building standalone portable executable..." -ForegroundColor Cyan
npm run build:portable

Write-Host "Build finished. Output is in ./dist" -ForegroundColor Green
