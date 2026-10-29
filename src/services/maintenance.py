"""Elevate only fixed, confirmed maintenance actions; no service credentials cross UAC."""
import base64
from pathlib import Path
import subprocess
import sys
import re
import time

from services.runtime import log_diagnostic


class MaintenanceError(RuntimeError):
    """Expected maintenance failure, suitable for an operator message."""


class MaintenanceCancelled(MaintenanceError):
    """Windows explicitly reported that administrator approval was cancelled."""


def _powershell_executable():
    import win32api
    return Path(win32api.GetSystemDirectory()) / 'WindowsPowerShell/v1.0/powershell.exe'


def check_windows_update_requirements():
    """Read machine module availability without elevation or installation."""
    script = r'''
$ErrorActionPreference = 'Stop'
$machineModules = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'WindowsPowerShell\Modules'
$systemModules = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\Modules'
$env:PSModulePath = "$machineModules;$systemModules"
$module = Get-Module -ListAvailable PSWindowsUpdate | Where-Object {
    $_.ModuleBase.StartsWith($machineModules + '\', [StringComparison]::OrdinalIgnoreCase)
} | Select-Object -First 1
if (-not $module) {
    'SC_UPDATE_MODULE_MISSING'
} elseif ((Get-ExecutionPolicy) -eq 'Restricted') {
    'SC_UPDATE_POLICY_RESTRICTED'
} else {
    'SC_UPDATE_MODULE_READY'
}
'''
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    try:
        result = subprocess.run(
            [str(_powershell_executable()), '-NoProfile', '-NonInteractive',
             '-EncodedCommand', encoded], capture_output=True, text=True,
            timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        raise MaintenanceError(
            'Could not check Windows Update requirements. Retry or ask an administrator to check this machine.') from None
    status = result.stdout.strip()
    if result.returncode == 0 and status == 'SC_UPDATE_POLICY_RESTRICTED':
        raise MaintenanceError(
            'Windows Update support is installed, but PowerShell policy blocks loading it. '
            'Ask an administrator to review this machine\'s PowerShell execution policy, then retry. '
            'The app has not changed the policy or started maintenance.')
    if result.returncode == 0 and status == 'SC_UPDATE_MODULE_MISSING':
        raise MaintenanceError(
            'Windows Update support is not installed on this machine. '
            'Ask an administrator to provision PSWindowsUpdate in the machine module directory, then retry. '
            'No administrator approval was requested and no updates were installed.')
    if result.returncode != 0 or status != 'SC_UPDATE_MODULE_READY':
        raise MaintenanceError(
            'Could not check Windows Update requirements. Retry or ask an administrator to check this machine.')

SYSPREP_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
if (Get-Process -Name Sysprep -ErrorAction SilentlyContinue) {
    throw 'Sysprep is already running. Resolve it before trying again.'
}
$program = Join-Path ([Environment]::GetFolderPath('System')) 'Sysprep\Sysprep.exe'
& $program /oobe /shutdown
if ($LASTEXITCODE -ne 0) { throw 'Sysprep did not complete successfully.' }
'''


def windows_update_script():
    base = (Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
            if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parents[1])
    path = base / 'Script.ps1'
    if not path.is_file():
        raise RuntimeError('Windows Update script is missing; reinstall the matching application package.')
    return path


def action_script(action):
    if action == 'windows-update':
        script = windows_update_script().read_text(encoding='utf-8-sig')
    elif action == 'sysprep':
        script = SYSPREP_SCRIPT
    else:
        raise ValueError('Unsupported maintenance action.')
    # The mutex lives in the elevated process, including after an unconfirmed
    # timeout in the GUI. Never terminate an unrelated maintenance process.
    return r'''
$ErrorActionPreference = 'Stop'
trap { exit 1 }
$mutex = [Threading.Mutex]::new($false, 'Global\SecondCheckingMaintenance')
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { throw 'Another maintenance action is running.' }
    & {
''' + script + r'''
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
'''


def _shell_execute(script):
    import pythoncom
    import win32api
    from win32com.shell import shell, shellcon
    executable = _powershell_executable()
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    parameters = subprocess.list2cmdline(['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded])
    pythoncom.CoInitialize()
    try:
        result = shell.ShellExecuteEx(
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS | shellcon.SEE_MASK_FLAG_DDEWAIT,
            lpVerb='runas', lpFile=str(executable), lpParameters=parameters,
            nShow=0, lpDirectory=win32api.GetSystemDirectory())
        return result['hProcess']
    finally:
        pythoncom.CoUninitialize()


def run_elevated(action, timeout=1800):
    started = time.monotonic()
    log_diagnostic('maintenance.requested', kind=action, timeout_seconds=timeout)
    script = action_script(action)
    try:
        handle = _shell_execute(script)
    except Exception as error:
        code = getattr(error, 'winerror', None) or getattr(error, 'errno', None)
        if code == 1223:  # ERROR_CANCELLED from ShellExecuteEx
            log_diagnostic('maintenance.cancelled', kind=action, error=error, stage='approval')
            raise MaintenanceCancelled(
                'Administrator approval was cancelled. No maintenance action was started.') from None
        log_diagnostic('maintenance.start_failed', kind=action, error=error, stage='approval')
        raise MaintenanceError(
            'Maintenance could not start. Retry or ask an administrator to check permissions.') from None
    try:
        import win32event
        import win32process
        result = win32event.WaitForSingleObject(handle, int(timeout * 1000))
        if result == win32event.WAIT_TIMEOUT:
            log_diagnostic('maintenance.timeout', kind=action, result='error', stage='wait',
                           elapsed_ms=int((time.monotonic() - started) * 1000))
            raise MaintenanceError('Maintenance exceeded its time limit; its outcome is unconfirmed. '
                               'It may still be running. Check Windows before retrying.')
        code = win32process.GetExitCodeProcess(handle) if result == win32event.WAIT_OBJECT_0 else None
        log_diagnostic('maintenance.finished', kind=action,
                       result='error' if code != 0 else 'success', exit_code=code,
                       elapsed_ms=int((time.monotonic() - started) * 1000))
        if result != win32event.WAIT_OBJECT_0 or code != 0:
            if action == 'sysprep':
                raise MaintenanceError('Sysprep failed. Upload a bug report to include its Windows error codes.')
            raise MaintenanceError('Maintenance failed. Check Windows history, permissions and required machine modules.')
    finally:
        handle.Close()


def run_windows_updates(timeout=1800):
    from services.auth_service import authorize
    authorize('maintenance')
    check_windows_update_requirements()
    run_elevated('windows-update', timeout)


def run_sysprep_shutdown(timeout=120):
    from services.auth_service import authorize
    authorize('maintenance')
    try:
        run_elevated('sysprep', timeout)
    except MaintenanceCancelled:
        raise
    except MaintenanceError as error:
        log_diagnostic('sysprep.failed', error=error, stage='maintenance')
        collect_sysprep_diagnostics()
        raise


def collect_sysprep_diagnostics():
    """Extract recent numeric Windows codes only; never upload Panther text.

    Panther can contain account/package identifiers and full paths. Keep its
    error codes, severity and line number while leaving the native logs local.
    """
    from datetime import datetime, timedelta
    import win32api
    root = Path(win32api.GetSystemDirectory()) / 'Sysprep' / 'Panther'
    cutoff = datetime.now() - timedelta(minutes=30)
    for filename in ('setuperr.log', 'setupact.log'):
        try:
            with (root / filename).open('rb') as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - 128 * 1024))
                lines = stream.read(128 * 1024).decode('utf-8-sig', errors='replace').splitlines()
            found = 0
            for line_number, line in enumerate(lines):
                try:
                    stamp = datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                if stamp < cutoff or not re.search(r'\bError\b', line, re.I):
                    continue
                stage = ('appx' if re.search(r'appx|package', line, re.I) else
                         'bitlocker' if re.search(r'bitlocker|bde', line, re.I) else
                         'validation' if re.search(r'validat', line, re.I) else 'panther')
                for code in re.findall(r'\b0x[0-9a-fA-F]{1,8}\b', line)[-4:]:
                    log_diagnostic('sysprep.windows_error', stage=stage,
                                   kind=filename, native_code=int(code, 16),
                                   line_number=line_number + 1 if size <= 128 * 1024 else None,
                                   result='error')
                    found += 1
                if found >= 20:
                    break
            log_diagnostic('sysprep.diagnostics_read', kind=filename, count=found)
        except OSError as error:
            log_diagnostic('sysprep.diagnostics_unavailable', error=error, kind=filename)
