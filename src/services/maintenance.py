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


SYSPREP_FAILURES = {
    11: ('maintenance_lock_create', 'Windows could not prepare the maintenance lock.'),
    12: ('maintenance_lock_acquire', 'Another maintenance action is running. Wait for it to finish before retrying.'),
    31: ('dialog_support', 'The Sysprep window check could not load.'),
    32: ('process_query', 'Windows could not identify the existing Sysprep process.'),
    33: ('process_identity', 'The existing Sysprep executable could not be verified.'),
    35: ('dialog_identify', 'The Sysprep window could not be confirmed idle. Close its idle options window and retry.'),
    36: ('dialog_close', 'The idle Sysprep window did not close. No second operation was started.'),
    37: ('process_recheck', 'Sysprep is still running. No second operation was started.'),
    38: ('process_launch', 'Windows could not launch Sysprep.'),
    39: ('process_result', 'Windows Sysprep returned a failure result.'),
}


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
$program = Join-Path ([Environment]::GetFolderPath('System')) 'Sysprep\Sysprep.exe'
$script:scMaintenanceExit = 31
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class SecondCheckingSysprepDialog {
    private delegate bool EnumChild(IntPtr window, IntPtr unused);
    [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, EnumChild callback, IntPtr unused);
    [DllImport("user32.dll")] private static extern bool IsWindowEnabled(IntPtr window);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] private static extern int GetDlgCtrlID(IntPtr window);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr window, StringBuilder name, int count);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SendMessageTimeout(IntPtr window, uint message, IntPtr wparam, IntPtr lparam, uint flags, uint timeout, out IntPtr result);
    public static bool CancelIdle(IntPtr window, int processId) {
        uint owner;
        GetWindowThreadProcessId(window, out owner);
        if (window == IntPtr.Zero || owner != (uint)processId) return false;
        int choices = 0;
        IntPtr ok = IntPtr.Zero, cancel = IntPtr.Zero;
        EnumChildWindows(window, delegate(IntPtr child, IntPtr unused) {
            var name = new StringBuilder(256);
            GetClassName(child, name, name.Capacity);
            if (!IsWindowVisible(child) || !IsWindowEnabled(child)) return true;
            if (name.ToString() == "ComboBox") choices++;
            if (name.ToString() == "Button") {
                if (GetDlgCtrlID(child) == 1) ok = child;
                if (GetDlgCtrlID(child) == 2) cancel = child;
            }
            return true;
        }, IntPtr.Zero);
        // The idle options dialog has two choices and OK/Cancel.
        // Processing windows do not qualify. Never terminate a process.
        if (choices != 2 || ok == IntPtr.Zero || cancel == IntPtr.Zero) return false;
        if (!IsWindowEnabled(ok) || !IsWindowEnabled(cancel)) return false;
        IntPtr result;
        return SendMessageTimeout(window, 0x0111, new IntPtr(2), cancel,
                                  0x0002, 5000, out result) != IntPtr.Zero;
    }
}
'@
foreach ($existing in @(Get-Process -Name Sysprep -ErrorAction SilentlyContinue)) {
    $script:scMaintenanceExit = 32
    $details = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $existing.Id)
    if (-not $details) { continue }
    $script:scMaintenanceExit = 33
    if ($details.ExecutablePath -ine $program) {
        throw 'The existing Sysprep executable could not be verified.'
    }
    # Windows can open an idle options dialog using different command lines.
    # Identify idle state from its enabled native controls, not its arguments.
    $existing.Refresh()
    $script:scMaintenanceExit = 35
    if (-not [SecondCheckingSysprepDialog]::CancelIdle($existing.MainWindowHandle, $existing.Id)) {
        throw 'The existing Sysprep window is busy or could not be identified safely.'
    }
    $script:scMaintenanceExit = 36
    if (-not $existing.WaitForExit(10000)) {
        throw 'The idle Sysprep window did not close. No second operation was started.'
    }
}
$script:scMaintenanceExit = 37
if (Get-Process -Name Sysprep -ErrorAction SilentlyContinue) {
    throw 'Sysprep is still running. No second operation was started.'
}
$script:scMaintenanceExit = 38
$operation = Start-Process -FilePath $program -ArgumentList '/oobe', '/shutdown' -Wait -PassThru
$script:scMaintenanceExit = 39
if ($operation.ExitCode -ne 0) { throw 'Sysprep did not complete successfully.' }
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
$script:scMaintenanceExit = 11
trap { exit $script:scMaintenanceExit }
$mutex = [Threading.Mutex]::new($false, 'Global\SecondCheckingMaintenance')
$owned = $false
try {
    $script:scMaintenanceExit = 12
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
                       stage=(SYSPREP_FAILURES.get(code, ('wait', ''))[0]
                              if action == 'sysprep' else 'wait'),
                       elapsed_ms=int((time.monotonic() - started) * 1000))
        if result != win32event.WAIT_OBJECT_0 or code != 0:
            if action == 'sysprep':
                if code in SYSPREP_FAILURES:
                    raise MaintenanceError(SYSPREP_FAILURES[code][1] +
                                           ' Upload a bug report if it persists.')
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
