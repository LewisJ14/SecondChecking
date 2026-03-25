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
    [switch]$SkipInstall,
    [switch]$UpgradePip
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Path $PSCommandPath -Parent
Set-Location $repoRoot

$logPath = Join-Path $repoRoot "compile.log"
if (Test-Path $logPath) {
    Remove-Item -Path $logPath -Force
}
function Log-Line($message) {
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$timestamp $message" | Out-File -FilePath $logPath -Encoding utf8 -Append
}
function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    $commandText = $FilePath
    if ($Arguments.Count -gt 0) {
        $commandText = "$FilePath $($Arguments -join ' ')"
    }
    Log-Line "Running command: $commandText"

    $quotedArgs = (($Arguments | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + ($_ -replace '"', '\"') + '"'
        }
        else {
            $_
        }
    }) -join ' ')
    $commandForCmd = '"' + $FilePath + '"'
    if ($quotedArgs) {
        $commandForCmd += " $quotedArgs"
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/d /c $commandForCmd 2>&1"
    $psi.WorkingDirectory = $repoRoot
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $false

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    $exitCode = $null

    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEnd()
        $process.WaitForExit()
        $exitCode = $process.ExitCode
    }
    finally {
        $process.Dispose()
    }

    foreach ($streamText in @($stdout)) {
        if ([string]::IsNullOrWhiteSpace($streamText)) {
            continue
        }
        foreach ($line in ($streamText -split "`r?`n")) {
            $text = [string]$line
            if ([string]::IsNullOrWhiteSpace($text)) {
                continue
            }
            Write-Host $text
            Log-Line $text
        }
    }

    if ($exitCode -ne 0) {
        Log-Line "$FailureMessage (exit $exitCode)."
        throw "$FailureMessage"
    }
}
Log-Line "Starting compile script (Python=$Python SkipInstall=$SkipInstall UpgradePip=$UpgradePip)"

$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Log-Line "Python executable '$Python' was not found."
    throw "Python executable '$Python' was not found."
}
$pythonExecutable = $pythonCommand.Source
try {
    $resolvedPython = (& $Python -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
    if ($resolvedPython) {
        $pythonExecutable = $resolvedPython
    }
}
catch {
    Log-Line "Falling back to PowerShell-resolved Python path."
}
Log-Line "Resolved Python command to $pythonExecutable."
Invoke-LoggedCommand -FilePath $pythonExecutable -Arguments @("--version") -FailureMessage "Failed to run '$Python --version'."

if (-not $SkipInstall) {
    Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Cyan
    Log-Line "Installing dependencies via pip."
    if ($UpgradePip) {
        Invoke-LoggedCommand -FilePath $pythonExecutable -Arguments @("-m", "pip", "install", "--upgrade", "pip") -FailureMessage "Failed to upgrade pip using '$Python'."
    }
    Invoke-LoggedCommand -FilePath $pythonExecutable -Arguments @("-m", "pip", "install", "-r", "requirements.txt") -FailureMessage "Failed to install dependencies using '$Python'."
    Log-Line "Dependency installation completed."
}

$runtimeManifestPath = Join-Path $repoRoot "runtime-files.json"
if (-not (Test-Path $runtimeManifestPath)) {
    Log-Line "Runtime manifest not found at $runtimeManifestPath."
    throw "Runtime manifest not found at '$runtimeManifestPath'."
}
$runtimeFiles = Get-Content -Path $runtimeManifestPath -Raw | ConvertFrom-Json
Log-Line "Loaded runtime file manifest from $runtimeManifestPath."

Write-Host "Cleaning previous build artifacts..." -ForegroundColor Cyan
Log-Line "Cleaning dist directory before building."
$buildDir = Join-Path $repoRoot "build"
$distDir = Join-Path $repoRoot "dist"
$distExe = Join-Path $repoRoot "dist\main.exe"
if (Test-Path $buildDir) {
    Remove-Item -Path $buildDir -Recurse -Force
    Log-Line "Removed existing build directory."
}
if (Test-Path $distDir) {
    foreach ($runtimeFile in $runtimeFiles) {
        if (-not $runtimeFile.overwrite) {
            continue
        }
        $targetPath = Join-Path $distDir $runtimeFile.target
        if (Test-Path $targetPath) {
            Remove-Item -Path $targetPath -Force
            Log-Line "Removed managed dist artifact $($runtimeFile.target)."
        }
    }
}
if (Test-Path $distExe) {
    try {
        Remove-Item -Path $distExe -Force
        Write-Host "Removed leftover dist\main.exe before building." -ForegroundColor Yellow
        Log-Line "Removed existing dist\main.exe."
    }
    catch [System.UnauthorizedAccessException] {
        Log-Line "Failed to delete dist\main.exe (locked). Attempting to stop running process."
        $runningProcesses = Get-Process -Name "main" -ErrorAction SilentlyContinue | Where-Object {
            try {
                $_.MainModule.FileName -and ([System.IO.Path]::GetFullPath($_.MainModule.FileName) -eq $distExe)
            }
            catch {
                $false
            }
        }
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
Invoke-LoggedCommand -FilePath $pythonExecutable -Arguments @("-m", "PyInstaller", "--clean", "--noconfirm", "main.spec") -FailureMessage "PyInstaller build failed."

foreach ($runtimeFile in $runtimeFiles) {
    $sourcePath = Join-Path $repoRoot $runtimeFile.source
    $targetPath = Join-Path $distDir $runtimeFile.target
    if (-not (Test-Path $sourcePath)) {
        Log-Line "Expected runtime file not found at $sourcePath."
        throw "Expected runtime file not found at '$sourcePath'."
    }
    if ((Test-Path $targetPath) -and (-not $runtimeFile.overwrite)) {
        $preserveReason = if ($runtimeFile.userManaged) { "user-managed" } else { "preserved" }
        Log-Line "Preserved existing $($runtimeFile.target) in dist directory ($preserveReason)."
        continue
    }
    Copy-Item -Path $sourcePath -Destination $targetPath -Force
    Log-Line "Copied $($runtimeFile.target) to dist directory."
}

Log-Line "PyInstaller build completed successfully."
Write-Host "Build completed successfully. Check the 'dist' directory for the executable." -ForegroundColor Green
