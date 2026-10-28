# SC21 maintenance prerequisite and cancellation messages — 27 October 2026

The Windows Update command now checks the machine-provisioned PSWindowsUpdate
module before requesting administrator approval. The earlier VM acceptance found
that a missing module caused an unnecessary UAC prompt followed by a generic
error. The new message identifies the prerequisite and asks an administrator to
provision it, explicitly confirming that no administrator approval was requested
and no updates were installed.

The check runs on the existing background worker after fresh service
authorization. It invokes system PowerShell without profiles or interaction,
restricts module discovery to machine/system paths, performs no import/install
or update scan, and has a 15-second limit. Missing, invalid, failed or timed-out
checks stop before elevation. A ready result continues to the fixed action.
The elevated script independently rechecks the module and retains its mutex and
administrator guard; preflight does not grant authority or replace those checks.

Windows ERROR_CANCELLED (1223), including the native pywintypes error, now becomes
a distinct MaintenanceCancelled outcome. The GUI presents normal cancellation
information. Other startup failures remain errors, and known prerequisite or
maintenance failures display their actionable message without the generic
“Unexpected error” prefix. Unexpected failures use a safe diagnostic. Timeouts
remain explicitly unconfirmed and do not terminate elevated maintenance.

## Verification

Later follow-up: the [real update/policy checkpoint](sc22-update-policy-preflight.md)
adds a read-only Restricted-policy guard after module provisioning. The newer
277-test build and its packaged VM result are recorded there; identities below
remain the original missing-module checkpoint.

All **275 desktop tests pass**. Thirteen focused maintenance tests cover missing,
ready, malformed/nonzero/timed-out preflight, authorization ordering, native and
standard cancellation error forms, distinct startup errors, GUI outcome routing,
busy-state reset and the existing fixed-action/handle/timeout invariants. The
existing helper fixture now supplies a ready prerequisite result. Tracked Python
compiles and the 140-file source-tracking gate passes.

Full unsigned review build: `69e21d4c-28c3-46bb-824f-7a2dc15288e3`, version 0.1.36,
SHA-256 `c754a42027cc1966e81e3d62fc3a6c6adf10e3e5e1f4c4a70eb2c961182a5cfa`.
The copied VM artifact matches its host digest and complete final source manifest.

At native 1280×800/100%, tester signed in to the full packaged GUI and confirmed
the Windows Update action. The actual missing-module message appeared without a
UAC request. The command could then be opened again and declined, demonstrating
that its busy state cleared. Both app processes remained non-elevated, with no
PowerShell, consent or Sysprep process left behind.

Configuration and normalized local draft key/results/baseline digests are
unchanged. Windows Update history stays at 12 entries. All six saved reports,
six assignment-history rows, seven receipts, the `test` reservation and secondary
fixture retain their contents. Authentication/session records are outside that
unchanged-data claim. The app is left signed in as tester on `test`.

Native cancellation on this new artifact was not repeated: the absent module
correctly prevents reaching UAC. Its classification and GUI handling are covered
by the native-error/unit fixtures; the preceding artifact's real denial/elevation
evidence remains in [maintenance acceptance](sc22-maintenance-acceptance.md).

Evidence, screenshots, exact build inputs and `verification.json` are outside Git:
`C:\Users\PCR\Documents\SecondChecking Review\sc21-maintenance-preflight-final-2026-10-27`.
No production configuration, schema, role policy, certificate store, VM image or
OVA changed. No release was committed, tagged, pushed or published.

The usability follow-up is complete locally and VM-tested. Successful real update
installation, alternate-admin, elevated contention/timeout and Sysprep acceptance
remain open, alongside production signing/hosted release and physical hardware.
