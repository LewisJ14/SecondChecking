"""Exercise the real PowerShell/native-window guard with harmless fixtures."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.maintenance import SYSPREP_SCRIPT, action_script


FIXTURE = r'''
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public class HarmlessSysprepFixture : Form {
    public int Cancels = 0;
    public IntPtr FirstChoice;
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowEx(int ex, string cls, string text, int style, int x, int y, int w, int h, IntPtr parent, IntPtr id, IntPtr instance, IntPtr unused);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] static extern bool EnableWindow(IntPtr window, bool enable);
    public void Prepare() {
        SetBounds(-32000, -32000, 400, 300);
        var parent = Handle;
        FirstChoice = CreateWindowEx(0,"ComboBox","",0x50000003,0,0,100,30,parent,new IntPtr(1003),IntPtr.Zero,IntPtr.Zero);
        CreateWindowEx(0,"ComboBox","",0x50000003,0,35,100,30,parent,new IntPtr(1004),IntPtr.Zero,IntPtr.Zero);
        CreateWindowEx(0,"Button","OK",0x50000000,0,70,80,30,parent,new IntPtr(1),IntPtr.Zero,IntPtr.Zero);
        CreateWindowEx(0,"Button","Cancel",0x50000000,90,70,80,30,parent,new IntPtr(2),IntPtr.Zero,IntPtr.Zero);
        ShowWindow(parent,4);
    }
    public void SetBusy() { EnableWindow(FirstChoice,false); }
    protected override void WndProc(ref Message message) {
        if(message.Msg==0x111 && message.WParam.ToInt32()==2) { Cancels++; return; }
        base.WndProc(ref message);
    }
}
'@
$fixture = New-Object HarmlessSysprepFixture
$fixture.Prepare()
'''


class SysprepLaunchTests(unittest.TestCase):
    def run_script(self, script):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.ps1'
            path.write_text(script, encoding='utf-8-sig')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                '-File', str(path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_native_guard_cancels_only_an_idle_owned_options_window(self):
        native = SYSPREP_SCRIPT[SYSPREP_SCRIPT.index('Add-Type'):SYSPREP_SCRIPT.index('foreach')]
        self.run_script("$ErrorActionPreference='Stop'\n" + native + FIXTURE + r'''
try {
    if ([SecondCheckingSysprepDialog]::CancelIdle($fixture.Handle, $PID+1)) { throw 'Wrong owner accepted' }
    if ($fixture.Cancels -ne 0) { throw 'Wrong owner cancelled' }
    if (-not [SecondCheckingSysprepDialog]::CancelIdle($fixture.Handle, $PID)) { throw 'Idle dialog rejected' }
    if ($fixture.Cancels -ne 1) { throw 'Cancel was not sent' }
    $fixture.SetBusy()
    if ([SecondCheckingSysprepDialog]::CancelIdle($fixture.Handle, $PID)) { throw 'Busy dialog accepted' }
    if ($fixture.Cancels -ne 1) { throw 'Busy dialog cancelled' }
} finally { $fixture.Dispose() }
''')

    def test_preflight_waits_for_idle_exit_and_refuses_active_or_unclosed_process(self):
        for scenario in ('idle', 'active', 'wrong_path', 'busy', 'not_closed'):
            with self.subTest(scenario=scenario):
                prefix = r'''
$ErrorActionPreference='Stop'
''' + FIXTURE + "\n$scenario = '" + scenario + "'" + r'''
$script:closed = $false
$script:started = $false
$existing = [pscustomobject]@{ Id=$PID; MainWindowHandle=$fixture.Handle }
$existing | Add-Member ScriptMethod Refresh {}
$existing | Add-Member ScriptMethod WaitForExit {
    param($timeout)
    if ($fixture.Cancels -ne 1) { throw 'No Cancel before wait' }
    $script:closed = ($scenario -ne 'not_closed')
    return $script:closed
}
function Get-Process { if (-not $script:closed) { return $existing } }
function Get-CimInstance {
    $cmd = '"' + $program + '"'
    $path = $program
    if ($scenario -eq 'active') { $cmd += ' /oobe /shutdown' }
    if ($scenario -eq 'wrong_path') { $path = 'C:\untrusted\Sysprep.exe' }
    return [pscustomobject]@{ CommandLine=$cmd; ExecutablePath=$path }
}
function Start-Process {
    param($FilePath,$ArgumentList,[switch]$Wait,[switch]$PassThru)
    if (-not $script:closed -or -not $Wait -or -not $PassThru) { throw 'Unsafe start' }
    if (($ArgumentList -join ' ') -ne '/oobe /shutdown') { throw 'Wrong action' }
    $script:started = $true
    return [pscustomobject]@{ ExitCode=0 }
}
if ($scenario -eq 'busy') { $fixture.SetBusy() }
$failed=$false
try {
'''
                suffix = r'''
} catch { $failed=$true } finally { $fixture.Dispose() }
if ($scenario -eq 'idle') {
    if ($failed -or -not $script:started) { throw 'Idle operation did not launch' }
} else {
    if (-not $failed -or $script:started) { throw 'Blocked operation launched' }
    if ($scenario -ne 'not_closed' -and $fixture.Cancels -ne 0) { throw 'Active operation cancelled' }
}
'''
                self.run_script(prefix + SYSPREP_SCRIPT + suffix)

    def test_launch_uses_waited_exit_code_even_with_stale_lastexitcode(self):
        for code in (0, 5):
            with self.subTest(code=code):
                prefix = r'''
$ErrorActionPreference='Stop'
$global:LASTEXITCODE=91
function Get-Process {}
function Start-Process {
    param($FilePath,$ArgumentList,[switch]$Wait,[switch]$PassThru)
    if (-not $Wait -or -not $PassThru) { throw 'Process was not waited' }
    return [pscustomobject]@{ ExitCode=CODE }
}
$failed=$false
try {
'''.replace('CODE }', str(code) + ' }')
                suffix = "\n} catch { $failed=$true; Write-Output $_ }\nif ($failed -ne $" + (
                    'false' if code == 0 else 'true') + ") { throw 'Wrong completion result' }"
                self.run_script(prefix + SYSPREP_SCRIPT + suffix)

    def test_fixed_script_is_valid_powershell_and_retains_maintenance_lock(self):
        script = action_script('sysprep')
        self.assertIn('Global\\SecondCheckingMaintenance', script)
        self.assertNotIn('Stop-Process', script)
        self.assertNotIn('taskkill', script.lower())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'parse-only.ps1'
            path.write_text(script, encoding='utf-8-sig')
            escaped = str(path).replace("'", "''")
            self.run_script("$tokens=$null; $errors=$null; "
                "[System.Management.Automation.Language.Parser]::ParseFile('" + escaped +
                "',[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { throw 'Parse failed' }")
