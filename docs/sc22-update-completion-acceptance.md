# SC22 real Windows Update completion — 27 October 2026

The full application update action now completes successfully with the installed
machine module. An independent online Windows Update Agent search succeeds and
finds no available updates. This verifies the real no-update completion path;
installation of a newly offered update remains unproven.

## Actual packaged run

Full unsigned review build `73ce3899-7694-4e1b-8217-46d41f87cd5e`, version 0.1.36,
SHA-256 `c9d9276561bd8908fe3cfe737fd6712eba1f9953dd8a38fc3c969279b9f1b9de`,
remains the current VM application. Product source did not change at this
checkpoint; its preceding 277-test suite and packaged policy guard remain valid.

The user manually configured the VM user's `CurrentUser` policy as `RemoteSigned`.
Readback confirmed it, and importing the signed PSWindowsUpdate 2.2.1.5 module
exposed `Get-WindowsUpdate` successfully. The user subsequently requested keeping
this setting for the reusable test VM. It remains configured; restoration to
`Undefined` is no longer pending. No host policy or machine-wide policy changed.

The previously authorized guest network connection was enabled for the test.
Guest mouse focus failed while the user's administrator PowerShell console was
open. The prepared native app-menu control invoked the normal update command;
the ordinary application confirmation was validated by title, owning PID and
message, then accepted. Neither the host pointer nor the user's console was
controlled. The user approved the actual Windows UAC prompt.

The actual app displayed “Windows Update script has finished. Check Windows
Update history for details.” Its production wait/exit handling reaches this
message only after the elevated helper returns zero. Reopening the command
reached normal confirmation again, showing that busy state cleared. That retry
was declined without another update run.

An independent read-only WUA online search using `IsInstalled=0 and IsHidden=0`
completed in about nine seconds, returned result code 2 (Succeeded) and an empty
update collection. It does not download update payloads or install anything.
History remains at 13 entries before/after the app run. The earlier background
Defender update remains attributed separately in the
[provisioning/policy checkpoint](sc22-update-policy-preflight.md).

## Preservation and final state

Configuration and normalized draft contents match the preceding checkpoint.
Before/after public database snapshots are identical: six reports, six
assignment-history rows, seven operation receipts, the `test` reservation and the
unchanged secondary fixture. The test order and draft remain open.

Both current application processes have non-elevated tokens. The named maintenance
mutex is absent and no owned maintenance PowerShell, consent or Sysprep process
remains. The user's pre-existing administrator PowerShell console (PID 9052) was
left untouched and is explicitly excluded from the owned-helper absence check.
No restart is required or performed. The network is disconnected again.
PSWindowsUpdate and the user-requested `CurrentUser=RemoteSigned` policy remain
part of this working test VM. The retained OVA has not been rebuilt with these
later changes.

Evidence remains outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-real-update-readiness-2026-10-27`:
`retry-result.json`, `retry-outcome.png`, `scan-only-result.json`,
`retry-final-state.json`, `retry-after.json`, database snapshots and
`retry-verification.json` (all required checks pass). Earlier files in this
directory describe the preceding blocked attempt and are preserved.

Actual installation of a new offered update, alternate-administrator credentials
and disposable-environment Sysprep remain open. Production signing/hosted release
and physical hardware/monitor acceptance also remain open. No additional product
build, release, VM image, snapshot or OVA was created.

References: Microsoft's [WUA search contract](https://learn.microsoft.com/en-us/windows/win32/api/wuapi/nf-wuapi-iupdatesearcher-search),
[operation result codes](https://learn.microsoft.com/en-us/windows/win32/api/wuapi/ne-wuapi-operationresultcode)
and [execution policy scopes](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies?view=powershell-5.1).
