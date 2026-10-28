<# Build into a new isolated directory; never copy private runtime files. #>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$Output,
    [string]$Tag,
    [switch]$Release,
    [switch]$SkipInstall,
    [switch]$UpgradePip
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSCommandPath
if (-not $Output) {
    $Output = Join-Path (Split-Path -Parent $repoRoot) ('SecondChecking-builds\' + [guid]::NewGuid().ToString())
}
if (-not $SkipInstall) {
    if ($UpgradePip) {
        & $Python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    }
    & $Python -m pip install -r (Join-Path $repoRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$arguments = @((Join-Path $repoRoot 'scripts\release_package.py'), 'build', '--output', $Output)
if ($Tag) { $arguments += @('--tag', $Tag) }
if (-not $Release) { $arguments += '--allow-dirty' }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Verified build failed; no release prepared.' }
Write-Host "Build output: $Output"
