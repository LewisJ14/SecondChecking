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

$logPath = Join-Path $repoRoot "compile.log"
function Log-Line($message) {
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$timestamp $message" | Out-File -FilePath $logPath -Encoding utf8 -Append
}
Log-Line "Starting compile script (Python=$Python SkipInstall=$SkipInstall)"

if (-not $SkipInstall) {
    Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Cyan
    Log-Line "Installing dependencies via pip."
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Log-Line "Failed to upgrade pip (exit $LASTEXITCODE)."
        throw "Failed to upgrade pip using '$Python'."
    }
    & $Python -m pip install -r "requirements.txt"
    if ($LASTEXITCODE -ne 0) {
        Log-Line "Failed to install requirements (exit $LASTEXITCODE)."
        throw "Failed to install dependencies using '$Python'."
    }
    Log-Line "Dependency installation completed."
}

Write-Host "Cleaning previous build artifacts..." -ForegroundColor Cyan
Log-Line "Cleaning dist directory before building."
$distExe = Join-Path $repoRoot "dist\main.exe"
if (Test-Path $distExe) {
    try {
        Remove-Item -Path $distExe -Force
        Write-Host "Removed leftover dist\main.exe before building." -ForegroundColor Yellow
        Log-Line "Removed existing dist\main.exe."
    }
    catch [System.UnauthorizedAccessException] {
        Log-Line "Failed to delete dist\main.exe (locked). Attempting to stop running process."
        $runningProcesses = Get-Process -Name "main" -ErrorAction SilentlyContinue
        if ($runningProcesses) {
            $runningProcesses | Stop-Process -Force
            Log-Line "Stopped running 'main' process."
            Start-Sleep -Seconds 1
            Remove-Item -Path $distExe -Force
            Log-Line "Removed dist\main.exe after terminating process."
        }
        else {
            Log-Line "No running 'main' process found; please close the executable manually."
            throw "Unable to delete dist\main.exe because it is in use."
        }
    }
}
Write-Host "Running PyInstaller..." -ForegroundColor Cyan
Log-Line "Invoking PyInstaller."
& $Python -m PyInstaller --clean --noconfirm "main.spec"
if ($LASTEXITCODE -ne 0) {
    Log-Line "PyInstaller failed (exit $LASTEXITCODE)."
    throw "PyInstaller build failed."
}

Log-Line "PyInstaller build completed successfully."
Write-Host "Build completed successfully. Check the 'dist' directory for the executable." -ForegroundColor Green
