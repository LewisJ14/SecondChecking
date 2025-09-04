# Script to Open Windows Update Settings and Initiate a Check for Updates

# Run the script with administrative privileges
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Warning "You need to run this script as an administrator."
    exit 1
}

# Ensure NuGet provider is installed (no prompt)
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force

# Install PSWindowsUpdate module (no prompt)
Install-Module -Name PSWindowsUpdate -Force -Scope CurrentUser

Import-Module PSWindowsUpdate

# Start checking for updates and install them if available (no auto reboot)
Write-Output "Initiating Windows Update check..."
Get-WindowsUpdate -AcceptAll -Install

Write-Output "Process completed."