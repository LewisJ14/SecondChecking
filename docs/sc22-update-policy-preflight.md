# SC22 real update attempt and policy preflight — 27 October 2026

Later follow-up: the [real completion pass](sc22-update-completion-acceptance.md)
now completes with no updates available after the user's manual policy setup.
The user requested retaining CurrentUser RemoteSigned in this reusable VM;
restoration instructions below describe the earlier temporary proposal and are
not a pending action. Earlier failure/policy observations remain historical.

The approved real Windows Update attempt found a second prerequisite failure.
PSWindowsUpdate was correctly installed, but the VM's effective PowerShell policy
is `Restricted`, which blocks its nested `.psm1` module. Successful app-driven
update installation remains open. The application now detects this condition
before UAC and explains it without changing Windows policy.

## Provisioning and actual attempt

The user approved connecting `SecondChecking-Test`, provisioning the module and
running the actual application update command, with no automatic restart. The
guest database SQL dump and configuration/drafts archive were backed up and
validated inside the guest only. Host evidence contains their digests, not their
private contents. No new VM, snapshot or OVA was created.

[PowerShell Gallery PSWindowsUpdate 2.2.1.5](https://www.powershellgallery.com/packages/PSWindowsUpdate/2.2.1.5)
was downloaded without running it on the host. Package SHA-256:
`174e05b1c194377f8d9ae0b004c93304c662ea9b5fc4dafa19426049d2d5cf50`.
Its DLL, manifest and module script have valid Authenticode signatures on both
host and guest. The prepared installer verifies every copied file's digest and
the signatures, refuses replacement, and provisions only the machine module
directory. It does not start updates, download providers, change execution policy
or add certificate trust. The user approved the guest UAC prompt. The first
launcher timed out before installation; the corrected detached launcher completed.

The app's old tester session had expired. Its actual sign-in guard rejected the
maintenance command, and the normal lock/sign-in flow established a fresh tester
session. Full review build `69e21d4c` then reached normal confirmation and UAC.
The user approved it. The app reported failure. A separate import diagnostic
identified `Restricted` / `UnauthorizedAccess` on the nested module script.
No policy was changed to make the test pass.

Connecting the guest allowed Windows itself to install a Defender intelligence
update before the app attempt: KB2267602, version 1.461.226.0, successful history
result 2 / HRESULT 0 at 13:59:15 UTC. History increased from 12 to 13 **before**
the app update command. It stayed at 13 afterward. This background installation
does not establish that the app installed an update successfully.

## Fix and packaged verification

The existing read-only machine-module preflight now also reads the effective
execution policy. With an installed module and `Restricted`, it returns a fixed
status token and raises an actionable maintenance error before requesting UAC.
Fresh service authorization still precedes preflight. No import, policy mutation,
module download or execution-policy command-line override is added. Unknown,
nonzero and timed-out probes still stop. The elevated action's independent guards
remain intact; other policy/import failures are not claimed covered by this check.

All **277 desktop tests pass**, including the real-Git release handoff regression
and the new policy-blocking test. All 25 transport/maintenance tests pass, tracked
Python compiles and the source gate passes with 140 tracked files.

New unsigned full review build: `73ce3899-7694-4e1b-8217-46d41f87cd5e`, version
0.1.36, SHA-256
`c9d9276561bd8908fe3cfe737fd6712eba1f9953dd8a38fc3c969279b9f1b9de`.
In the visible VM at 1280×800/100%, tester confirmed the normal update action.
The full app displayed the policy-specific message without UAC. Retrying reached
normal confirmation again, demonstrating busy-state reset, and was declined.
The `test` order reopened and restored its draft.

The configuration and normalized draft key/results/baseline digests match the
pre-test values. Draft byte identity differs after the sign-in/reload sequence;
exact byte preservation is not claimed. Complete public database snapshots match:
six reports, six assignment-history rows, seven receipts, the `test` reservation
and unchanged secondary fixture. Both current application processes are
non-elevated, the maintenance mutex is absent and no consent, PowerShell or
Sysprep process remains. No restart is required or performed. The guest network
is disconnected again. The approved module remains installed for further testing.

## Evidence and next dependency

Public package/provisioning records, screenshots, before/after inventory and
database snapshots, update history, build inputs and verification are under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-real-update-readiness-2026-10-27`.
Private recovery files remain at
`C:\SC22Visual\RealUpdateHarness\private-backup` inside the VM.

An administrator must review the VM's intended execution policy before a
successful module-based update test can proceed. The application does not make
that decision or weaken the policy. Actual successful app-driven installation,
alternate-admin and disposable-environment Sysprep acceptance remain open, along
with production signing/hosted release and physical hardware/monitor acceptance.
No product commit, tag, push or release was created.

### Manual prerequisite for the next attempt

A fresh read confirms all five policy scopes are `Undefined`; the effective
Windows-client policy is therefore `Restricted`. There is no configured Group
Policy override. The guest remains running with its network disconnected.

For this VM-only test, the operator can manually run the following in Windows
PowerShell **inside SecondChecking-Test**, confirming the change when asked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

This permits local scripts and requires trusted signatures on scripts marked as
downloaded, for this guest user. It affects subsequent PowerShell sessions for
that user until restored. No host setting or machine-wide policy is involved.
After the test, the operator should restore the observed original scope value:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy Undefined
```

These are prepared manual instructions, not executed changes. Read back both
effective and scoped policies before testing and after restoration. Microsoft
documents the [policy scopes, RemoteSigned and restoration to Undefined](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies?view=powershell-5.1).
