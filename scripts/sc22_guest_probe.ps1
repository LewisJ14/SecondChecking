<# Read-only checks of the dedicated synthetic VM lab; never prints credentials. #>
[CmdletBinding()]
param([string]$Output = 'C:\SC22Validation\baseline.json')
$ErrorActionPreference = 'Stop'
$lab = 'C:\SecondChecking-Test'
$settings = Get-Content -LiteralPath "$lab\settings.json" -Raw | ConvertFrom-Json
$config = Get-Content -LiteralPath "$lab\App\config.ini" -Raw
$hostMatch = [regex]::Match($config, '(?im)^host\s*=\s*([^\r\n]+)')
$urlMatch = [regex]::Match($config, '(?im)^base_url\s*=\s*([^\r\n]+)')
if (-not $hostMatch.Success -or $hostMatch.Groups[1].Value.Trim() -notin @('127.0.0.1','localhost')) {
    throw 'Baseline database is not the expected loopback fixture.'
}
if (-not $urlMatch.Success -or -not ([uri]$urlMatch.Groups[1].Value.Trim()).IsLoopback) {
    throw 'Baseline API is not the expected loopback fixture.'
}
$report = [ordered]@{
    schema_version = 1
    lab_kind = 'legacy synthetic simulator baseline, not current production contract'
    os_version = [Environment]::OSVersion.Version.ToString()
    database_loopback_only = $true
    api_loopback_only = $true
    default_login_is_test = ($settings.login_password -eq 'test')
    baseline_app_sha256 = (Get-FileHash -LiteralPath "$lab\App\main.exe" -Algorithm SHA256).Hash.ToLowerInvariant()
    latest_review_app_sha256 = (Get-FileHash -LiteralPath 'C:\SC22Validation\main.exe' -Algorithm SHA256).Hash.ToLowerInvariant()
    baseline_app_present = (Test-Path -LiteralPath "$lab\App\main.exe")
    backend_present = (Test-Path -LiteralPath "$lab\TestBackend.exe")
    database_binary_present = (Test-Path -LiteralPath "$lab\Database\mariadb-11.4.12-winx64\bin\mariadbd.exe")
    process_is_administrator = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] 'Administrator')
}
# The password stays inside this disposable guest, never in arguments/output.
$client = "$lab\Database\mariadb-11.4.12-winx64\bin\mariadb.exe"
try {
    $env:MYSQL_PWD = $settings.db_password
    $query = "SELECT EXISTS(SELECT 1 FROM user WHERE username='tester'), EXISTS(SELECT 1 FROM ``order`` WHERE order_number='test');"
    $rows = & $client --host=127.0.0.1 --user=root --database=secondchecking_test --batch --skip-column-names --execute=$query 2>$null
    $report.database_fixture_checked = ($LASTEXITCODE -eq 0)
    $report.tester_and_test_order_present = ($LASTEXITCODE -eq 0 -and ($rows -join '').Trim() -match '^1\s+1$')
} catch {
    $report.database_fixture_checked = $false
    $report.tester_and_test_order_present = $false
} finally {
    $env:MYSQL_PWD = $null
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Output -Encoding utf8
Write-Output 'Synthetic baseline probe finished; report contains no credentials.'
