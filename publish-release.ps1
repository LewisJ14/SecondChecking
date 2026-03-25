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
$versionFile = Join-Path -Path $repoRoot -ChildPath "src\version.py"

function Log-Message {
    param($Message)
    $entry = "{0} {1}" -f (Get-Date).ToString("s"), $Message
    $entry | Out-File -FilePath $logPath -Encoding utf8 -Append
}

function Get-CurrentVersion {
    param($Path)
    if (-not (Test-Path $Path)) {
        throw "Version file not found at $Path"
    }
    $content = Get-Content -Raw -LiteralPath $Path
    if ($content -notmatch '__version__\s*=\s*"([^"]+)"') {
        throw "Unable to find __version__ declaration in version.py"
    }
    return $Matches[1]
}

function Normalize-RepoSlugFromUrl {
    param($Url)
    if (-not $Url) {
        return $null
    }
    $clean = $Url.Trim()
    $clean = $clean -replace '\.git$', ''
    $clean = $clean -replace '^.+://', ''
    $clean = $clean -replace '^.+@', ''
    $clean = $clean -replace ':', '/'
    $parts = $clean.Split('/') | Where-Object { $_ -ne "" }
    if ($parts.Count -lt 2) {
        return $null
    }
    return "$($parts[-2])/$($parts[-1])"
}

function Get-RepoSlugFromConfig {
    param($Root)
    $configPath = Join-Path $Root ".git\config"
    if (-not (Test-Path $configPath)) {
        return $null
    }
    $config = Get-Content -Raw -LiteralPath $configPath
    $match = [regex]::Match($config, '(?m)^\s*url\s*=\s*(.+)$')
    if (-not $match.Success) {
        return $null
    }
    return Normalize-RepoSlugFromUrl -Url $match.Groups[1].Value
}

function Get-RepoSlug {
    param($Root)
    $slug = $null
    try {
        $raw = git remote get-url origin
        $slug = Normalize-RepoSlugFromUrl -Url $raw
    } catch {
        $slug = $null
    }
    if (-not $slug) {
        $slug = Get-RepoSlugFromConfig -Root $Root
    }
    if (-not $slug) {
        $slug = "lewisj14/SecondChecking"
    }
    return $slug
}

function Set-Version {
    param($Path, $Version)
    $content = Get-Content -Raw -LiteralPath $Path
    $newContent = $content -replace '__version__\s*=\s*"([^"]+)"', "__version__ = `"$Version`""
    Set-Content -LiteralPath $Path -Value $newContent -Encoding utf8
}

function Bump-Version {
    param($Path)
    $current = Get-CurrentVersion $Path
    $parts = $current.Split('.')
    $parts[$parts.Count - 1] = ([int]$parts[-1] + 1).ToString()
    $newVersion = $parts -join '.'
    Set-Version -Path $Path -Version $newVersion
    return $newVersion
}

$needsCompile = $false
if (-not $SkipCompile) {
    $answer = Read-Host "Run compile.ps1 before releasing? (Y/N)"
    if ([string]::IsNullOrWhiteSpace($answer)) {
        Write-Host "No compile choice provided; defaulting to compile."
        Log-Message "No compile choice provided; defaulted to compile."
        $needsCompile = $true
    } else {
        $needsCompile = $answer.Trim().ToUpper().StartsWith("Y")
    }
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

Log-Message "Preparing release (notes = '$Notes')..."
Write-Host "Preparing release (notes = '$Notes')..."

$currentVersion = Get-CurrentVersion $versionFile
Write-Host "Current version: $currentVersion"
$notesInput = Read-Host "Release notes (leave blank to use '$Notes')"
if (-not [string]::IsNullOrWhiteSpace($notesInput)) {
    $Notes = $notesInput.Trim()
}
$versionChoice = Read-Host "Enter version for this release (blank to auto-increment patch)"
if ([string]::IsNullOrWhiteSpace($versionChoice)) {
    $version = Bump-Version $versionFile
    Log-Message "Auto-incremented version to $version"
} else {
    Set-Version -Path $versionFile -Version $versionChoice.Trim()
    $version = $versionChoice.Trim()
    Log-Message "Manually set version to $version"
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI ('gh') is required."
    Log-Message "GitHub CLI not found"
    exit 1
}
Log-Message "GitHub CLI available"
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

$repoSlug = Get-RepoSlug $repoRoot
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
