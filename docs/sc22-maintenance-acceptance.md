# SC22 maintenance VM checks — 27 October 2026

Latest follow-up: [real update completion](sc22-update-completion-acceptance.md)
passes with the provisioned module and user-configured policy. An independent
online scan succeeds with no available updates; no new installation is claimed.
The guest is offline again, and the user requested retaining its CurrentUser
RemoteSigned policy. Historical blocked-attempt evidence follows.

Follow-up: the [maintenance preflight/message fix](sc21-maintenance-preflight-fix.md)
is now implemented and tested in a new full artifact with 275 passing tests. The
artifact identities and original generic-message observations below remain the
historical guard/approval evidence.

Maintenance acceptance is in progress and is not closed. This uses full review
build `107dcb03-fbf8-42e7-8aef-920e5175c8ad`, version 0.1.36, SHA-256
`b46774983149682a1b71e4030ac17b681090a540a4f702fc23bb40cbcbdf15cb` in the
existing visible `SecondChecking-Test` VM. No application source changed.

Later follow-up: the [approved online update attempt](sc22-update-policy-preflight.md)
installed the signed machine module and exposed a Restricted-policy import
failure. The new full build reports that prerequisite before UAC, with 277 tests
passing. The guest is offline again; successful app-driven installation remains
open pending administrator policy review. Historical module/history statements
below describe this earlier checkpoint.

## Completed checks

- The app/guest session runs with a filtered, non-elevated token.
- The actual packaged maintenance sources and bundled `Script.ps1` match the
  recorded source manifest. Seven targeted maintenance boundary tests pass;
  their elevation/exit/timeout boundaries remain mocked.
- With the serial viewer open, **Tools > Run Windows Updates** showed **Bench
  busy** and requested closing dialogs, rather than launching maintenance.
- With dialogs closed, the app displayed its explicit install/administrator
  approval/no-automatic-restart confirmation. Choosing No returned to the bench
  without a UAC request.
- A fresh attempt reached an actual Windows PowerShell UAC prompt showing
  Microsoft Windows as verified publisher. The user chose **No**. The actual app
  reported “Administrator approval was cancelled or maintenance could not start”
  and stayed open. Executable/configuration digests and the 12-entry update
  history are unchanged; both draft filenames remain. One draft's byte digest
  changed before the post-denial capture, so exact pre-denial draft-content
  identity is not claimed. The approved test now captures normalized draft
  key/results/baseline hashes separately from its update timestamp.
- The first approval prompt timed out before the user could respond. The app's
  operator session subsequently expired too. Native guest app-menu control
  reached the normal sign-in-required guard, and Operator > Lock/change operator
  opened a fresh process. Tester signed in again; no session policy was bypassed.
- The user approved a fresh UAC request. The actual app reported “Maintenance
  failed. Check Windows history, permissions and required machine modules,”
  rather than success. The lab has no PSWindowsUpdate module. The approved
  attempt preserved normalized draft key/results/baseline digests, configuration,
  executable and the 12-entry update history. No module or update was installed.
- Reopening the maintenance command reached its confirmation again, proving the
  busy state was cleared; it was declined without another elevation request.
  Both actual app processes still have non-elevated tokens. No consent,
  PowerShell or Sysprep process remains, and the maintenance mutex is absent.

## Lab prerequisites and limits

The VM's network link remains disabled. No machine-provisioned PSWindowsUpdate
module is available. The approved attempt returned the expected nonzero/failure
outcome in this environment; its generic GUI diagnostic does not name the module.
This proves failure reporting, not a successful update installation.

The baseline history contains 12 entries. Reading history through the Windows
Update COM API activated the update service; its running status is not evidence
of installing an update. No module or update has been installed by this checkpoint.

The [native boundary fixture follow-up](sc22-maintenance-boundary-acceptance.md)
now passes five real elevated lock, exit, timeout and abandoned-mutex cases with
harmless action bodies. Actual successful Windows Update installation/history
verification, alternate administrator credentials and Sysprep remain acceptance
work. Sysprep would enter OOBE and shut down; it has not been run on
this working VM containing the lab database and evidence. It needs a suitable
disposable environment. No new VM image/clone or OVA was created.

## Evidence and next action

Evidence is outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-maintenance-2026-10-27`:
native screenshots, `before-uac.json` with configuration/draft hashes and history
count, `source-verification.json`, actual outcome screenshots, `final-state.json`
and `verification.json`. Before/after synthetic database snapshots retain six
reports, six assignment-history rows and seven receipts with unchanged contents,
plus the same `test` reservation and secondary fixture. Authentication/session
records are outside that unchanged-data claim.

The user handled Windows security confirmations. Denial and approved-failure
checks are complete. The app is open as tester on `test` at the current guest
resolution, 1280×800/100%; no host mouse/keyboard was used.

The SC21 prerequisite/cancellation-message usability follow-up is complete in the
new artifact linked above. Successful maintenance acceptance remains open.
Three broad groups remain: production signing/hosted release, maintenance, and
physical hardware/monitors.
