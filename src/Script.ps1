# Explicitly confirmed Windows Update action, run by the scoped UAC helper.
$ErrorActionPreference = 'Stop'
trap { exit 1 }
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] 'Administrator')) {
    throw 'Administrator approval is required.'
}
# Use machine-provisioned modules only. No provider/module downloads or profile scripts.
$machineModules = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'WindowsPowerShell\Modules'
$systemModules = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\Modules'
$env:PSModulePath = "$machineModules;$systemModules"
$module = Get-Module -ListAvailable PSWindowsUpdate | Where-Object {
    $_.ModuleBase.StartsWith($machineModules + '\', [StringComparison]::OrdinalIgnoreCase)
} | Sort-Object Version -Descending | Select-Object -First 1
if (-not $module) {
    throw 'An administrator must provision PSWindowsUpdate in the machine module directory first.'
}
Import-Module $module.Path -ErrorAction Stop
Get-WindowsUpdate -AcceptAll -Install -IgnoreReboot -ErrorAction Stop
