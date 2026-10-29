# Sysprep through the app in Audit Mode — 29 October 2026

The published application reproduced the operator's failure when Audit Mode's
idle System Preparation Tool was already open. Closing that idle tool with
Cancel allowed the app to start Windows Sysprep and shut down the VM. A separate
completion-reporting defect can display an app error even when Windows proceeds.
Neither defect is claimed fixed by the reporting release 0.1.43.

## Actual application test

Used the published 0.1.42 executable, SHA-256
`39bdd44249994ef336061858e86b279ccab9e3549193561b6b3bfa2732b825a6`.
The Sysprep command and process guard are unchanged in 0.1.43; its changes add
diagnostics and a more relevant failure message. The 0.1.43 report uploaded from
the affected physical machine independently recorded helper exit code 1 with no
recent Windows Sysprep errors. The operator confirmed that machine stayed
running and the System Preparation Tool was already open.

All VM assignments used the existing isolated loopback service and synthetic
test order. No production assignment or physical-hardware result was created.

1. Signed into the packaged app, searched the test order, assigned the VM through
   the recorded-reason review and obtained the application's real operation
   receipt. Selected **OK & Sysprep**, confirmed its shutdown question and had the
   user approve the actual Windows administrator prompt. The app displayed its
   generic failure message; Windows nevertheless recorded a success tag and a
   successful shutdown request and powered off.
2. Booted to OOBE and sent **Ctrl+Shift+F3** to the guest keyboard. Signed into the
   existing built-in Administrator account after the unattended installation's
   stale default-user sign-in interrupted automatic logon. The app launcher
   recorded a built-in Administrator SID and an elevated token, and verified the
   published executable hash. Windows automatically opened the idle System
   Preparation Tool. No Audit Mode setting or Sysprep command was substituted for
   this keyboard entry sequence.
3. Launched the same unmodified EXE under that Administrator account with the
   existing guest-only loopback configuration. Performed another real test-order
   assignment and used **OK & Sysprep** while leaving the Windows tool open. The
   app displayed the generic maintenance error and the VM stayed running. The
   original idle Windows tool remained visible and had not started processing.
4. Selected **Cancel** in the idle Windows tool. Dismissed the app error, then
   retried **OK & Sysprep** from the same assignment-success dialog. The app again
   displayed an error, but Windows proceeded and the VM powered off.

The final native run began at 11:33:14 and recorded the success tag and successful
shutdown request at 11:34:31. There were no error entries in that run. The retained
error log contains an earlier 11:31:19 entry saying the Sysprep dialog returned
FALSE, which corresponds to cancelling the idle Windows tool; it must not be
misattributed to the subsequent successful app-triggered run.

Screenshots, app logs, Panther logs, account/binary verification and the final
rollback record are retained outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\audit-sysprep-2026-10-29`.
Guest controls left the host computer's mouse and keyboard available. No new OVA
or VM clone was created. The existing pre-test disk checkpoint is retained.

## Follow-up fixes identified during the original VM pass

- Explain the existing-process guard accurately. Audit Mode's idle GUI is a
  `Sysprep.exe` process, so the current guard rejects it. Tell the operator to
  close an **idle** System Preparation Tool using Cancel before retrying, while
  continuing to protect an operation that is actually processing. Never kill an
  unrelated Sysprep process to make an attempt proceed.
- Correct completion handling for the actual elevated `-EncodedCommand` launch.
  The present direct GUI executable invocation and `$LASTEXITCODE` check can
  report failure before Windows finishes. Verify explicit process waiting and
  exit handling through the packaged app; a standalone `.ps1` test is not an
  adequate substitute. Keep timeout reporting unconfirmed and preserve drafts.

Microsoft documents the keyboard entry sequence and automatic System Preparation
Tool window in [Boot Windows to Audit Mode or OOBE](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/boot-windows-to-audit-mode-or-oobe?view=windows-11).

## Implementation in 0.1.46

The maintenance script now sends Cancel to an identified idle options dialog,
then waits for that process to exit before launching the requested operation.
It requires the system Sysprep executable, a command line without operation
arguments, the owning process ID, two visible enabled selectors and enabled
OK/Cancel buttons. Unknown or busy processes block a second launch. No process
is forcefully terminated. Windows' installed dialog resources confirm the
options/progress distinction and the standard OK/Cancel control IDs.

The new operation uses `Start-Process -Wait -PassThru` and its `ExitCode`, avoiding
the stale `$LASTEXITCODE` path. Existing authorization, elevation, maintenance
mutex, draft preservation and unconfirmed-timeout behavior are retained.

Automated PowerShell tests exercise real native fixture windows without running
Windows Sysprep: idle cancellation, busy/foreign-window refusal, unrecognized
executable/active arguments, failed closure, waited launch and nonzero exit.
These validate the implementation; the earlier app/Audit Mode VM pass above
reproduced the defects before this change. The corrected packaged app still
needs an end-to-end Audit Mode shutdown retest; this release does not claim that
new VM acceptance has already taken place.
