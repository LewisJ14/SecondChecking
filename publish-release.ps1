<#
    Build a release bundle, rename it, produce the updater manifest,
    then push the executable + manifest to GitHub releases via `gh`.

    Usage: .\publish-release.ps1 [-Notes "Release notes"] [-Force] [-Pause] [-SkipCompile]
#>

param(
    [string]$Notes = "Release build",
    [switch]$Force,
    [switch]$Pause,
    [switch]$SkipCompile
)

$repoRoot = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
$logPath = Join-Path $repoRoot "publish-release.log"

function Log-Message {
    param($Message)
    $entry = "{0} {1}" -f (Get-Date).ToString("s"), $Message
    $entry | Out-File -FilePath $logPath -Encoding utf8 -Append
}

$needsCompile = $false
if (-not $SkipCompile) {
    $answer = Read-Host "Run compile.ps1 before releasing? (Y/N)"
    $needsCompile = $answer.Trim().ToUpper().StartsWith("Y")
} else {
    $needsCompile = $false
}

function ExitIfError {
    param($Message)
    if (!$?) {
        Write-Host $Message -ForegroundColor Red
        Log-Message $Message
        if ($Pause) { Read-Host "Press Enter to close..." }
        exit 1
    }
}

Log-Message "Starting publish-release.ps1 (notes='$Notes' force=$Force skipCompile=$SkipCompile pause=$Pause)"

Write-Host "Preparing release (notes = '$Notes')..."

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI ('gh') is required."
    Log-Message "GitHub CLI not found"
    exit 1
}
Log-Message "GitHub CLI available"
$script = "import importlib.util, pathlib; spec = importlib.util.spec_from_file_location('version', pathlib.Path('src/version.py')); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print(mod.__version__)"
$version = & python -c $script
ExitIfError "Failed to determine version from src/version.py."

$version = $version.Trim()
$tag = "v$version"
$exeName = "SecondChecking-$version.exe"
$dist = Join-Path $repoRoot "dist"
$exeSource = Join-Path $dist "main.exe"
$exeTarget = Join-Path $dist $exeName

if ($needsCompile) {
    Write-Host "Running compile.ps1..."
    Log-Message "Invoking compile.ps1"
    & "$repoRoot\compile.ps1" -SkipInstall
    ExitIfError "Compile script failed."
} else {
    Write-Host "Skipping compile as requested."
    Log-Message "Skipped compile.ps1"
}

if (-not (Test-Path $exeSource)) {
    Write-Error "dist/main.exe missing after compile."
    exit 1
}

Copy-Item -Path $exeSource -Destination $exeTarget -Force
Log-Message "Copied $exeSource -> $exeTarget"

$repoSlug = ((git remote get-url origin) -replace '^.*[:/](.+?)(\.git)?$', '$1')
$manifest = @{
    version = $version
    download_url = "https://github.com/$repoSlug/releases/download/$tag/$exeName"
    release_page = "https://github.com/$repoSlug/releases/tag/$tag"
    notes = $Notes
    metadata = @{ generated_at = (Get-Date).ToUniversalTime().ToString("o") }
}

$manifestPath = Join-Path $repoRoot "update.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding utf8
Log-Message "Manifest written to $manifestPath"

$releaseExists = $false
try {
    gh release view $tag -q >/dev/null 2>&1
    if ($LASTEXITCODE -eq 0) {
        $releaseExists = $true
    }
} catch {
    $releaseExists = $false
}
if ($releaseExists -and $Force) {
    gh release delete $tag --yes
    Log-Message "Deleted existing release $tag (force)"
}

if ($releaseExists -and -not $Force) {
    Write-Host "Updating release $tag..."
    gh release upload $tag $exeTarget $manifestPath --clobber
    gh release edit $tag --notes "$Notes"
    Log-Message "Updated release $tag"
} else {
    Write-Host "Creating release $tag..."
    gh release create $tag $exeTarget $manifestPath --title "SecondChecking $version" --notes "$Notes"
    Log-Message "Created release $tag"
}

Write-Host "Release $tag uploaded."
Log-Message "Release $tag uploaded"

if ($Pause) {
    Read-Host "Press Enter to finish..."
}
