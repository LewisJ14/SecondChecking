<# Prepare a verified release. -Publish explicitly creates a draft on GitHub. #>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$Tag,
    [string]$NotesFile,
    [string]$Artifact,
    [switch]$SkipCompile,
    [switch]$Publish,
    [switch]$Force,
    [switch]$Pause
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSCommandPath
if ($Force) { throw 'Release replacement is disabled; use a new version/tag.' }
$common = @('--output', $Output)
if ($Tag) { $common += @('--tag', $Tag) }
$tool = Join-Path $repoRoot 'scripts\release_package.py'
if (-not $SkipCompile) {
    & $Python $tool build @common
    if ($LASTEXITCODE -ne 0) { throw 'Verified build failed.' }
}
$prepare = @('prepare') + $common
if ($NotesFile) { $prepare += @('--notes-file', $NotesFile) }
if ($Artifact) { $prepare += @('--artifact', $Artifact) }
& $Python $tool @prepare
if ($LASTEXITCODE -ne 0) { throw 'Release preparation failed.' }
if ($Publish) {
    & $Python $tool publish @common
    if ($LASTEXITCODE -ne 0) { throw 'Draft upload failed.' }
}
if ($Pause) { Read-Host 'Press Enter to finish' }
