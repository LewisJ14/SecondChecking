# SC18 update validation and rollback

Implemented locally on 22 October 2026. No release was published or installed, no signing certificate was created or trusted, and no Windows Update or certificate-store maintenance ran. Signed end-to-end upgrade/recovery and exact-release VM acceptance remain release requirements.

## Behaviour

The previous updater downloaded an unverified executable and deleted the installed copy before moving its replacement. The new path validates the release, stages it alongside the installation, preserves a working backup, and requires a separate installer to confirm readiness before closing the GUI. Downloads and checks run off the Tk thread, with progress and cancellation. Busy checks and draft preservation prevent an update from silently abandoning bench work.

Only HTTPS releases from `lewisj14/SecondChecking` are accepted. Versions must use major.minor.patch, and the release page and executable name must match the declared version. GitHub asset redirects are restricted to GitHub content hosts. Manifest and executable size limits, request/read limits, a download deadline, exact byte size and SHA-256 reject malformed, truncated, oversized or changed downloads. A manifest saying an artifact is signed is not proof of its publisher.

Automatic installation requires the operator to have maintenance permission, a packaged Windows client, manifest digest/size, and an independently configured `APP_UPDATE_SIGNER_SHA256`. This is the SHA-256 of the publisher certificate's DER bytes, not its usual SHA-1 thumbprint. Windows Authenticode must report Valid, and the certificate must match the pin for both the installed baseline and candidate. The optional manifest signer fingerprint must also agree. Source runs and releases lacking these prerequisites open the validated release page and leave the app open. Incorrect signatures or failed checks retain the current installation.

The candidate runs a private health command in an owned, bounded process. Its nonce, actual embedded version, frozen status, desktop imports and bundled script availability must pass. This check creates no GUI and performs no database, network or hardware operation. The copied installer is verified and held against writes/deletion until it confirms readiness. Independent one-file processes start without inherited PyInstaller extraction state.

## Installation and recovery

Each transaction owns `<installation>/.secondchecking-updates/<UUID>/`. Its plan records target identity, old/new versions, hashes, sizes and configured publisher. The directory also holds the verified candidate, copied baseline installer, handoff/cancellation records, startup confirmation and durable outcome journal. No credentials or configuration values are copied into these records.

The worker takes an exclusive target lock, identifies the original parent by PID and creation time, and waits for that process to exit. It rechecks the candidate, retains the original as `.<executable-name>.<UUID>.previous`, copies and verifies a replacement beside the target, then uses `os.replace`. It never deletes the installed executable to make room. Configuration and draft files are outside the replacement transaction.

After replacement, content, publisher and health are checked again. The new app must report its transaction nonce and version after constructing the controller/login screen and processing initial layout. This proves initial GUI startup, not successful login, service connectivity or physical hardware operation. On a failed replacement or unconfirmed restart, the owned failed child is stopped and the verified previous copy is restored; the worker attempts to reopen it. A failed recovery/restart is recorded distinctly for manual action.

Re-entering a journal interrupted after replacement restores the retained original rather than replaying installation. The Tools menu offers **Restore previous app version** using the copied baseline installer and verified backup. An unexpectedly changed installed file or invalid backup stops recovery instead of overwriting an unknown executable. Outcomes are retained locally and surfaced on a subsequent app startup. Backups are retained; disk-space/retention management can follow after deployment requirements are agreed.

If the app cannot open, use the retained backup as the recovery source after verifying it, or invoke the copied installer with `--restore-update <absolute-plan.json>`. It requires the configured publisher pin and write access to the installation. Do not rename/move its journal or installer independently. Restore is executable-only: it does not reverse server/database migrations or guarantee compatibility of older clients with a newly deployed service. Coordinate those deployments under SC15/SC16/SC22.

## Verification

The update tests cover trusted origins/redirect policy, version and manifest validation, streamed integrity, deadlines, cancelled/interrupted downloads, publisher rejection, actual Windows unsigned-file rejection, health identity, helper handoff, real Windows file locks, successful fixture replacement, denied replacement, failed health/restart, interrupted transactions, explicit recovery, invalid backups and preservation of fixture configuration/drafts. Hidden Tk tests exercise progress responsiveness, cancellation, manual fallback and shutdown only after successful handoff. A pre-existing note-editor test now waits for its worker result within a bounded deadline rather than assuming completion within 150 ms.

The separate one-file **windowed** `sc18-update-probe.exe` passes all 14 transaction fixture tests and the actual packaged import/asset health probe, with no GUI created and no stdout dependency. Positive publisher, candidate-health and GUI-launch boundaries in the transaction tests are mocked. These results do not establish a successful real signed installation. Exact source/artifact hashes and counts are retained in [the evidence manifest](sc18-update-evidence.json).

## Before release

27 October signed follow-up: the [SC22 signed VM matrix](sc22-signed-update-acceptance.md)
passed eight real signed transaction cases and actual Tools-menu rollback. The
user-approved guest test signer was removed afterward. This advances laboratory
acceptance; production publisher, hosted release and deployment checks remain.

27 October follow-up: [SC22 update readiness](sc22-update-readiness.md) adds real
full-artifact health and unsigned-worker rejection evidence. No signing trust
changed; the positive signed installation/recovery matrix still needs a publisher
or explicit approval for a temporary guest-only test signer.

1. Complete SC19 release/version/source identity. Obtain and independently configure the trusted publisher certificate, sign the baseline and candidate, and calculate manifests only from the final signed artifacts. An old unsigned baseline needs a verified manual installation first.
2. Use the exact release executable in a disposable VM with the matching service. Exercise a valid signed upgrade, cancellation, offline/download failure, signature/version mismatch, locked target, restart failure, interrupted replacement and Tools recovery. Verify no orphan installer/helper and retained configuration/drafts.
3. Confirm startup/login and paired service compatibility after upgrade and rollback, including schema gates. Test installation-directory permissions and actual antivirus/file-lock behaviour. Stage a recoverable backup before production rollout.

No database migration is introduced by SC18. SC19 remains the next source item; SC21 handles the wider transport/maintenance privilege boundaries.
