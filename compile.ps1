<#!
.SYNOPSIS
    One-click build script for packaging the application with PyInstaller.
.DESCRIPTION
    Installs dependencies (unless --SkipInstall is provided) and invokes PyInstaller using the
    existing main.spec file. All paths are resolved relative to the repository root so that the
    script can be launched from any location.
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Path $PSCommandPath -Parent
Set-Location $repoRoot

if (-not $SkipInstall) {
    Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Cyan
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip using '$Python'."
    }
    & $Python -m pip install -r "requirements.txt"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install dependencies using '$Python'."
    }
}

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
& $Python -m PyInstaller --clean --noconfirm "main.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Write-Host "Build completed successfully. Check the 'dist' directory for the executable." -ForegroundColor Green
