# SecondChecking application improvement plan

Updated 23 October 2026 during SC22 portable-baseline validation; the interactive VirtualBox walkthrough was on 21 October. This is the current status companion to the original application review. Stable SC numbers are retained; the walkthrough expands existing items rather than duplicating them.

## Current delivery status

SC01–SC21 have been implemented and tested in the local source trees. SC04 adds the owner-approved recorded-reason policy; SC05 preserves device/order drafts and invalidates stale actions. SC06 qualifies local MDM evidence without claiming tenant verification; SC09 separates audio decisions and SC10 records hardware coverage and its limits. The updated desktop and matching server have not yet been deployed. The SC01 migration was applied to the configured local `astro` MySQL database, reaching `0b7c8d9e0f1a`, after a verified backup. An earlier unreleased test executable was built, and packaged SC01/SC02 regression tests passed inside the VM; that build does not include SC04–SC21. End-to-end main-app acceptance with the matching Web-Tools server and coordinated deployment remain outstanding. See [SC01](sc01-assignment-transactions.md) and [SC02](sc02-exact-serial-identifiers.md).

SC19 also produced a full windowed review executable outside the checkout, with embedded source fingerprints/build UUID and a matching final artifact manifest. It is an unsigned, dirty-source review build of 0.1.36 and cannot be published through the release tool. Archive/version inspection passed; it has not replaced the VM app or completed elevated main-app/login acceptance. See [SC19 evidence and release requirements](sc19-release-identity.md).

The walkthrough used the earlier packaged **0.1.36** build and a local API simulator. Its manifest names base commit `1895a9ba8b4ed643e379a86b88bd2502736adc32` and earlier uncommitted review fixes. **It does not include SC01 or SC02.** Findings from that build must not be described as regressions in the later changes. The simulator does not prove production API compatibility.

## Work queue

| Item | Improvement | Status and next check |
| --- | --- | --- |
| SC01 | Server owns assignment transactions and retry receipts | Local implementation, DB migration, serial-viewer follow-ups and test build complete; paired main-app/server acceptance and rollout remain. |
| SC02 | Exact serial identifiers | Local implementation complete; exact-identifier and viewer action regressions passed in a frozen executable inside the VM. Paired main-app acceptance remains. |
| SC03 | Retire desktop trade workflows | Implemented locally by owner decision: order-only search, notes and assignment; retired requests cannot be resent. Original trade field-parity work cancelled. See sc03-order-only-desktop.md. |
| SC04 | Failed checks and overrides | Implemented locally: owner-approved reason policy, final review, server enforcement, override history/readback and explicit cancellation. Paired deployment and VM acceptance remain. See sc04-result-review.md. |
| SC05 | Preserve unsaved results and reference context | Implemented locally: persistent exact device/order drafts, guarded resolved context, staged lookup results and safe failure/loading exits. Updated VM acceptance remains. See sc05-check-session-protection.md. |
| SC06 | Qualify MDM evidence | Implemented locally: qualified local states, source/time/errors, fresh assignment capture, server validation and saved readback. Known-device tenant comparison and deployment remain. See sc06-local-mdm-evidence.md. |
| SC07 | Complete storage comparison | Implemented locally: owner-selected per-drive configuration policy, physical-ID inventory, complete capacity/type comparison, review and saved readback. Physical/VM acceptance remains. See sc07-storage-configuration.md. |
| SC08 | Refresh measurements and identify their source | Implemented locally: background Refresh Device, expiring caches, capture age/source, fresh assignment snapshot, bounded isolated battery export and explicit unknown/current-mode states. Physical/VM acceptance remains. See sc08-measurement-freshness.md. |
| SC09 | Independent speaker and microphone tests | Implemented locally; separate device selection, listening decisions and outcomes, conservative playback and owned-stream cleanup. Physical audio and packaged VM acceptance pending. See [SC09](sc09-independent-audio.md). |
| SC10 | Hardware test coverage | Implemented locally: USB port checklist, keyboard capture/manual explanation, display instructions, qualified camera/WLAN states and saved coverage. 108 desktop and 29 isolated Flask tests pass. Physical/packaged matrix remains pending. See [SC10](sc10-hardware-coverage.md). |
| SC11 | Worker lifecycle and cancellation | Implemented locally: cancellable event-driven runner, staged results, outcome summary, isolated native I/O, owned process-tree cleanup, keyboard queues and background notes. 114 desktop tests pass; exact packaged VM/physical acceptance pending. See [SC11](sc11-test-lifecycle.md). |
| SC12 | Layout, focus and scrolling | Implemented locally: wrapping comparison/header, bounded footer, readable scrollable keyboard, hardware card reflow and scoped wheel/focus handling. 115 tests pass, including eight simulated Tk size/scale cases. Native Windows DPI, visual and packaged VM acceptance pending. See [SC12](sc12-responsive-layout.md). |
| SC13 | Accurate states and saved reports | Implemented locally: authenticated full saved report with states/provenance/assignment/receipt, legacy/absent/error distinctions, neutral fresh-session message, reload and explicit updater result. 122 desktop and 33 isolated Flask tests pass; packaged/paired acceptance pending. See [SC13](sc13-saved-reports-and-states.md). |
| SC14 | Reliable fresh configuration | Implemented locally: safe environment/file precedence, shared path, required-field validation, login Retry, example config and read-only first-run probe. 132 desktop tests pass; packaged clean-VM acceptance pending. See [SC14](sc14-fresh-configuration.md). |
| SC15 | Migrations instead of runtime DDL | Implemented locally: read-only fail-closed desktop contract, additive server bridge and guarded empty-database setup. 141 desktop, 33 API and six migration/setup tests pass; migration deployment and packaged/MySQL grants acceptance pending. See [SC15](sc15-schema-migrations.md). |
| SC16 | Authenticated service permissions | Implemented locally with owner-approved tester access: server login/reset and expiring sessions, authenticated attribution/receipt ownership, audited note writes, lock/change operator and read-only desktop SQL. 150 desktop and 49 isolated server tests pass; migration/paired/VM/TLS acceptance pending. See [SC16](sc16-operator-sessions.md). |
| SC17 | Packaged helpers and required scripts | Implemented locally: versioned file IPC, owned bounded helpers, bundled Windows Update script and actual exit handling. 163 desktop tests and nine real windowed frozen-probe scenarios pass; exact main release/VM/physical acceptance pending. See [SC17](sc17-packaged-helpers.md). |
| SC18 | Update validation and rollback | Implemented locally: trusted release/publisher/content checks, cancellable preparation, verified backup, atomic replacement, confirmed restart and journalled recovery. Eight real signed VM scenarios and Tools-menu rollback pass with a temporary guest signer; production publisher and exact-release/hosted acceptance remain. See [signed VM evidence](sc22-signed-update-acceptance.md). |
| SC19 | Release workflow and artifact identity | Implemented locally: shared isolated builds, embedded source/build identity and Windows version, stale-artifact/tag guards, final-byte manifests and explicit draft uploads. 207 desktop tests, 78 compiled Python files and actionlint pass; full review executable built/inspected. Hosted CI, signing and exact-main VM acceptance pending. See [SC19](sc19-release-identity.md). |
| SC20 | Source tracking and service boundaries | Implemented locally and staged: 28 generated/private index entries removed with local bytes preserved, reviewed source tracked, CI/release source policy gate, headless configuration/logging/auth/database boundaries and canonical resources. 220 desktop tests and 81 tracked Python compilations pass; commit/history review and release/VM acceptance pending. See [SC20](sc20-source-boundaries.md). |
| SC21 | Transport and maintenance privileges | Implemented locally: verified HTTPS/no credential redirects, verified SQL TLS, bounded loopback exceptions, standard-user GUI and confirmed fixed maintenance elevation. 239 tests and 83 tracked Python compilations pass; full windowed identity/health entries pass with a standard token. Real service TLS, UAC/maintenance and physical/VM acceptance remain. See [SC21](sc21-transport-privileges.md). |
| SC22 | Repeatable testing and portable baseline | Portable OVA exported, SHA-256 verified and independently imported/cold-booted; fixture and packaged health checks pass. Current paired GUI/service and physical release acceptance remain. See sc22-repeatable-testing.md. |

## Requirements added by the walkthrough

### SC01 and SC02 follow-ups completed

The viewer now disables actions without a current exact selection and during loading/removal, explains empty and failed lists, and clears the loading state on failure. Recovered removal receipts are labelled as historical; rejected removal preserves the row and uses no local assignment write. Worker results are processed on the Tk thread and polling stops when the window closes.

Verification passed 36 source desktop tests and 20 frozen SC01/SC02 regression tests inside the VM. These frozen tests use real hidden Tk controls and mocked DB/HTTP boundaries. The 19 real Flask transaction tests also passed with temporary SQLite and disposable MariaDB 11.4.12. The updated main executable and hash manifest are staged under `SecondChecking Review/sc01-sc02-build`, without credentials or production configuration. The old VM app was preserved.

The matching real Web-Tools test service is still required for end-to-end main-app acceptance. That follow-up completed the viewer portions described above; SC04 was subsequently implemented as recorded below; the remaining SC11/SC13 work stays open. SC03 was subsequently changed to desktop trade removal, as recorded below.

### SC03 scope changed to an order-only desktop

The project owner requested removal of trade workflows from SecondChecking. The selector, trade lookup/assignment/notes, report upload and persisted mode handling are removed. Old trade settings are ignored without rewriting private configuration. Retired pending mutations are not resent or silently discarded. Web-Tools trade features and existing records are preserved. See [SC03 implementation](sc03-order-only-desktop.md).

SC04 has since been implemented locally using the owner-approved policy below. SC05 has also been implemented locally; SC06 local evidence qualification, SC07 storage configuration, SC08 measurement freshness, SC09 independent audio and SC10 hardware coverage are implemented locally; SC11 test lifecycle is also implemented locally; SC12 layout and scrolling are also implemented locally; SC13 saved reports and accurate states are also implemented locally; the remaining implementation and acceptance sequence starts with SC22. Trade-specific field parity and a desktop trade serial viewer are no longer required. Historical trade observations below describe the reviewed baseline only.

### SC13 saved order report readback — local implementation complete

View Report now reads the authenticated full saved report in a background worker and shows all checks, active/superseded override history, coverage, saved specs/measurements, dual-battery evidence, qualified MDM, assignment review, identity and a matched historical receipt. It distinguishes loading, full report, legacy-only data, absent assignment and failed/timed-out requests, with Reload/Close and stale-response protection. No current-assignment claim is inferred from a historical receipt. See [SC13 implementation and pending paired acceptance](sc13-saved-reports-and-states.md).

The following observation describes the reviewed baseline:

The order View Spec dialog showed hardware specifications and MDM text, but omitted saved hardware test outcomes. Include every test, capture time, operator, available override provenance, batteries, assignment identity and receipt in a readable order report. A successful upload message alone is insufficient proof of saved field parity. Override recording itself remains SC04.

### SC04 result policy — local implementation complete

The owner chose **allow assignment with a recorded reason**. The desktop now presents a scrollable final review including all eight checks, activation, exceptions and override details. A reason is mandatory for non-pass results, active overrides, unknown legacy history and existing MDM/spec warnings. The server independently validates the result states, review identity/time, override provenance and required reason before assignment writes. Result review policy version 1 is required; old clients must be stopped during coordinated rollout.

Wi-Fi override history records original/replacement results, previous decisions, operator, UTC time and reason. Badges say **OVERRIDDEN PASS/FAIL**. Retesting supersedes the active decision while preserving its history. Saved result loading now uses the authenticated service, including Wi-Fi and override history; legacy records are marked as having unknown history. Closing display, keyboard, webcam, USB and speaker result prompts records Cancelled; explicit Cancel buttons are present. Display Escape cancels directly.

Verification and rollout details are in [SC04 implementation](sc04-result-review.md). This does not close per-user service authentication (SC16), independent audio outcomes (SC09), device-absence detection (SC10), Run All cancellation (SC11), or the full saved-report viewer (SC13). No new database migration is needed: provenance is retained in the existing report JSON.

The following observations describe the reviewed baseline:

Show failed, incomplete, unavailable and overridden checks separately in the final assignment summary. In the VM, keyboard, speaker, microphone, webcam and USB failures did not appear in the order warning; the warning mentioned specification mismatches only. The simulator accepted that report. Agree the bench policy for when such assignments may proceed and enforce it through the server as well as the desktop.

An override must retain the measured result, record who changed it and why, and display **Overridden pass** rather than an unqualified PASS. Closing a test or its result prompt must have an explicit Cancel outcome; it must not silently assert a measured failure. Add corresponding server fields and readback tests while doing SC03/SC04.

### SC05 session protection and reference context — local implementation complete

Local drafts now preserve results and override history by resolved order ID and exact device serial, including repeat lookup and restart. Bench-only checks transfer only to the first resolved order for that device. A changed server report offers Restore, Discard or Cancel; draft write failure stops navigation. Confirmed assignment clears its matching draft while later edits remain unsaved.

Unsubmitted input edits retain the loaded order and its actions. A valid submitted search preserves the draft and clears the previous action context; invalid input retains it. Search stages results separately and commits them on the Tk thread after full resolution; stale callbacks are ignored. Lookup failure/cancel exits clear loading without restoring old actions. The resolved order/device and local draft state are visible. Context switching is blocked during active tests/assignment. See [SC05 implementation and verification](sc05-check-session-protection.md).

The following observation describes the reviewed baseline:

The historical trade walkthrough reproduced unsaved results being cleared on repeat search. Trade mode switching is now removed. Preserve an order draft by device and resolved reference, or offer Save, Discard and Cancel before replacing it. Invalidate old selections and disable assignment/view actions until a new order lookup resolves. Show the resolved reference beside the results so typed input cannot be mistaken for the loaded record.

### SC06 local evidence qualification — local implementation complete

Local Autopilot registry observations no longer become a locked/clear verdict. The desktop identifies source, capture time and incomplete reads, and always states that tenant registration/enrolment is not verified. Assignment captures fresh evidence and retains it in report JSON. Concerning or incomplete local evidence requires a recorded reason; a completed negative local read is explicitly limited to that source. The server validates version 1 evidence and returns it on readback. Legacy results are unqualified/unknown. Automatic refresh is read-only.

72 desktop and 25 isolated Flask tests passed, including real hidden Tk footer checks. See [SC06 implementation, sources and acceptance limits](sc06-local-mdm-evidence.md). A known enrolled laptop and authorised tenant comparison remain release acceptance work; the VM does not establish these outcomes. No live tenant integration or database migration was added.

### SC07 storage configuration — local implementation complete

The owner selected the specified physical-drive configuration, not equivalent total capacity. Equal-size and unpartitioned drives are retained by device ID. USB/removable evidence is excluded but recorded, and optional uniquely serial-matched media/bus evidence qualifies type. Count, every capacity and requested type are compared; missing/ambiguous evidence requires review. Full SKU layouts and resolved custom-item requirements survive into final assignment review. Inventory and storage-review JSON are saved and returned by the existing API without a migration.

83 desktop and 26 isolated Flask tests passed, including real hidden Tk storage badges. See [SC07 policy, tolerance and acceptance limits](sc07-storage-configuration.md). Physical controller/dual-drive acceptance and paired deployment remain; SC08 retains refresh/capture-age work for cached measurements.

### SC08 measurement freshness — local implementation complete

Refresh Device gathers a fresh background snapshot while preserving order/check drafts. Memory and disk caches expire; capture time, age and source are visible. Search and final assignment force a capture, with exact serial validation. Battery export uses an isolated temporary file, bounded process, proper CSV/encoding handling and paired per-battery capacity values. Absent, unreadable and measured low health remain distinct. Current charge/power state is separate from health; AC power alone does not imply charging.

Current Windows display mode is explicitly separate from unverified native-panel capability, and Windows edition from activation. An unreadable battery or unverified panel cannot silently receive a MATCH. Metadata and the reviewed battery export are saved/read back without a migration. 100 desktop and 27 isolated Flask tests passed. See [SC08 implementation and acceptance limits](sc08-measurement-freshness.md). Real battery, packaged-helper, display and VM acceptance remain release work; no native-panel detector was added.

### SC09 independent audio — local implementation complete

Speaker and microphone have independent buttons, selected devices, listening confirmation and result updates. Noise cannot auto-pass either test. Playback starts at 15% digital amplitude; Windows levels, mute, gain and default devices stay unchanged. Missing endpoints, test errors, operator failures and cancellation are distinct. Owned streams close on all normal/error/cancel exits and operations have a bounded timeout. 104 desktop tests passed, including hidden Tk audio controls with mocked endpoints. No migration is needed. See [SC09 workflow and pending physical acceptance](sc09-independent-audio.md). The VM and packaged executable still need this source update.

### SC10 hardware coverage — local implementation complete

USB now has an operator-labelled per-port checklist requiring fresh removable-volume observations, with explicit Finish, Unavailable, Error and Cancel actions. Keyboard capture records observed/missing logical keys and requires a saved explanation for manually passing incomplete capture. Display screens show inspection/advance/cancel instructions and retain shown colours. WLAN detection uses the language-independent Windows API and explicitly excludes network quality; absent/not-ready interfaces and service/API errors remain distinct. Camera absence is Unavailable, failed probes release their captures, and live-image confirmation is required to Pass.

Coverage survives drafts, final assignment review, report upload and authenticated readback; the matching server validates the optional metadata before writes. No migration is required. 108 desktop tests and 29 isolated SQLite Flask transaction tests passed. A [physical acceptance matrix](sc10-hardware-coverage.md) defines outstanding VM, known-good/faulty device, locale, port, keyboard, camera and saved-evidence checks. Those are not completed physical evidence. SC11 subsequently implemented native test I/O isolation, overall attempt limits, worker lifecycle and Run All cancellation locally; packaged/physical acceptance remains.

The following observations describe the reviewed baseline; SC09's audio coupling and SC10's coverage/instructions are now addressed locally.

The VM had no usable audio playback device, camera, removable USB drive or Wi-Fi adapter. These are lab limitations, not evidence of defective physical hardware. Report **Unavailable** or a specific test error where appropriate. The speaker error currently marks the microphone FAIL too. The display sequence needs visible instructions for advancing and cancelling. The USB screen needs per-port instructions and a clear Finish/Cancel action instead of requiring the window close button.

### SC11 workflow feedback — local implementation complete

Run All now uses an event-driven single-attempt runner with persistent cancellation, explicit step progress and a completion summary. Cancel inside a test or close/destroy the panel stops the sequence and cleans up owned dialogs/jobs. Unstarted checks retain their previous outcomes; staged per-attempt results prevent late callbacks overwriting a newer run. Native camera, audio, USB, WLAN, activation, product-key and live-battery I/O runs in isolated workers with operation limits and Windows process-tree ownership. Keyboard callbacks queue events for Tk; note saves run in the background and retain text after unconfirmed saves. 114 desktop tests passed, including real child timeout/descendant termination and hidden Tk cancel/reopen/stale-result cases. No migration is required. See [SC11 implementation and pending packaged acceptance](sc11-test-lifecycle.md).

The following observation describes the reviewed baseline:

Run All proceeded through the unavailable-device paths and returned to “Ready to run hardware checks.” Add a completion summary with counts and unsaved status. Provide a persistent Cancel control, identify the current step and restore the test panel after owned dialogs close. Repeated opening/closing and late worker callbacks still need dedicated acceptance tests.

### SC12 layout — local implementation complete

The comparison now uses layout-managed, wrapping widgets with separate identity, action and SKU rows. A bounded scrollable/collapsible footer preserves comparison space and retains the qualified MDM overview. Hardware cards wrap descriptions beneath controls; Run All/Cancel remains allocated ahead of the growing list. The keyboard diagram scrolls in both directions, measures label widths and keeps Finish/Cancel outside that surface. Scoped wheel and focus scrolling support child controls without global binding changes.

115 desktop tests passed. The new geometry matrix covers 1024×768 and 1366×768 at simulated Tk scales of 100%, 125%, 150% and 200%; comparison viewports remained 310–401 px high. This is programmatic geometry evidence, not native Windows DPI or physical visual acceptance. See [SC12 changes, measurements and outstanding release checks](sc12-responsive-layout.md).

The following layout requirement describes the reviewed baseline and remains part of physical acceptance:

Put long SKU titles and actions in separate rows. Make the fixed footer responsive so the comparison remains usable at 1024×768. Ensure keyboard labels and hardware descriptions fit their cells, and support wheel scrolling over the active list as well as dragging its scrollbar. Verify 125%, 150% and 200% scaling separately.

### SC13 messages — local implementation complete

Fresh Not Run checks now show a neutral session message; they do not diagnose database failure. Empty/failed serial lists retain disabled view/remove controls and offer Reload. The update helper emits an explicit result for a successful no-newer-release check; empty/invalid output is unknown/error. Full saved report fields are projected read-only without uploaded file bodies or private spec keys. 122 desktop and 33 isolated Flask transaction tests passed; 88 desktop and 196 server Python files compiled. No new migration is required. Matching-server deployment, exact packaged helper behaviour and VM visual acceptance remain pending.

The following observations describe the reviewed baseline:

The Hardware Tests warning “Not connected to database, failed to load test results” is triggered in `app_controller.py:open_test_panel` whenever every result is Not Run; it is not a connection check. Use a neutral fresh-session message and report actual connection failures separately. Empty serial list actions/states were addressed in the SC01/SC02 follow-up. Trade note labelling is no longer applicable after SC03.

After the unmatched trade search `testx`, the app correctly displayed Trade Job Not Found, but left the previous comparison, Assign Serial action and “Searching...” indicator visible after dismissal. Clear or explicitly invalidate stale results and finish the loading state on every success, error and no-match exit. Prove that an invalid reference cannot submit against a previously selected record.

### SC22 release testing

SC22's portable baseline is complete. A full independent clone of the Ready-to-test snapshot was exported with networking disabled and host shares/install media detached. The 10.26 GB OVA passed full SHA-256 manifest verification and was independently imported and cold-booted as SecondChecking-Redeploy-Check. The staged SC21 review executable passed fresh identity and health checks as a standard guest user; a read-only lab probe confirmed tester/test and order test after starting the synthetic services. All 244 desktop tests and 49 real Flask route/auth/migration fixture tests pass. Artifact identity, import evidence and remaining acceptance are recorded in [SC22 repeatable testing](sc22-repeatable-testing.md). SC22 remains open for current packaged GUI/server, real TLS, signed update, native DPI and physical hardware acceptance.

Retest SC01/SC02 using a newly packaged executable and the actual matching Web-Tools service in isolation. Keep simulator tests for controlled failures, but do not treat its generic success response as production contract coverage. Retain a physical-laptop checklist for batteries, audio, cameras, USB ports, Wi-Fi, MDM, activation and hash enrolment. Record image provenance and prove an independent OVA/OVF import before calling the baseline portable.

## Revised sequence

### Native VM visual follow-ups — 23 October 2026

The [latest packaged visual review](vm-visual-review-2026-10-23.md) uses the SC21
review build and matching real Web-Tools routes in a new isolated guest database.
It supersedes the earlier simulator walkthrough only for the screens/workflows
explicitly covered there. Follow-ups and their current implementation status:

- **SC12 / VR01 (P2):** replace the fixed-pixel sign-in card with content-aware,
  work-area-bounded layout. At native 125% secondary actions disappear; at 150%
  Log In also disappears, including on a 4K desktop. Add fresh-launch login,
  retry/error/reset and long-username native-DPI acceptance.
- **SC08 / VR02 (P2):** capture every battery rather than relying on the helper's
  one-selected-pack default export. Two healthy simulated packs both show
  Unreadable because inventory/export counts differ. Preserve the conservative
  unreadable result until identities/capacity pairs can be established; prove
  saved readback with duplicate pack names/serials and distinct capacities.
- **SC12 / VR03 (P3):** make live DPI changes consistent with a fresh launch;
  verify real monitor transitions after the VM's single-monitor coverage.
- **SC11/SC17 / VR04 (P2):** separate bounded frozen-worker startup/readiness from
  native operation deadlines. In the full VM artifact, standalone WLAN/audio/live
  battery workers return useful results after 38–40 s, but the GUI expires them
  after 10–15 s. Profile cold startup and keep cancellation/process ownership.
- **SC12 / VR05 (P2):** keep Webcam/USB Cancel actions outside the growing status
  content. At native 150%, wrapped timeout messages collapse Cancel into an
  unlabelled strip; cover asynchronous error and preview states in the matrix.
  The default serial viewer also hides its action row at 4K/200%; maximizing
  recovers it. Reserve footer space and expose complete identifiers by default.

The screenshot/DPI matrix and remaining acceptance are in the review record.
**VR06 (P1) and VR04 (P2) are now implemented locally and passed packaged VM
regression:** workers reuse the parent runtime, startup/operation limits are
separate, and independent probes unpack only inside owned cleanup directories.
248 desktop tests pass. The full candidate completed 30 worker/helper runs,
20 cancellations and three independent timeouts without additional extraction
folders; useful results arrive in 0.4–2.1 seconds. The actual GUI shows live 90%
charge, correct audio-unavailable/WLAN-service outcomes and Run All cancellation.
See [worker fix evidence and remaining release acceptance](vr-worker-lifecycle-fix.md).
**VR02 / SC08 is now implemented and packaged-VM tested:** native Windows
capacity records are paired by battery instance, both simulated packs display
90.9%, and the isolated API/database preserved both readings and the exact
attachment. All 252 desktop tests pass. See [dual-battery fix](vr-dual-battery-fix.md).

**VR07 / SC08 is implemented locally:** capture timestamps and age checks now
use the same wall-clock conversion, removing a reproducible sub-microsecond
false-future boundary without permitting future or expired captures. All 254
desktop tests pass. See [freshness correction and VM evidence](vr-startup-freshness-fix.md).

**VR01 / SC12 is implemented and packaged-VM tested:** the sign-in card follows
content/font scale, keeps actions reachable through scoped scrolling and sizes
after theme initialization. All 255 tests pass. Native 1080p at 100–175%, 4K at
200/250%, and 1800×1200 at 200% show every control. Error/retry, long username and
reset/cancel states were also sampled at 200%. See [sign-in fix evidence](vr-signin-scaling-fix.md).

**VR05 / SC12 is implemented and VM-layout tested:** webcam/USB action footers
remain outside scrolling content; the serial viewer reserves actions and exposes
complete selected identifiers. All 256 tests and nine native fixture cases at
125–250% pass. The full candidate also passed USB cancellation and serial/report
viewing at 150% against the isolated fixture. See [action-footer evidence](vr-action-footer-fix.md).

**VR08 / SC11 is implemented locally and VM-tested:** transient worker file
access failures retry across polls for a fixed one-second budget, with deadlines,
malformed-message errors and helper size limits preserved. All 262 desktop tests
and 10 guest worker tests pass; the full candidate's USB polling and cancellation
were checked. See [file-access recovery evidence](vr-worker-file-access-fix.md).

**VR03 / SC12 is implemented locally and packaged-VM tested:** existing fonts,
new-dialog defaults, tree metrics and window bounds follow DPI/work-area changes
without rebuilding check state. All 265 tests pass. Native 1080p, 4K at 200/250%
and 1800×1200 at 200% retain the selected serial and reachable actions. See
[live scaling evidence and mixed-monitor limitation](vr-live-dpi-fix.md).

Next: **SC22 remaining release acceptance** — complete reviewed source/hosted CI
and signed update/rollback, maintenance and physical hardware/monitor checks.
Three broad acceptance groups remain. The
[host configuration checkpoint](sc22-host-configuration.md) now provides the
canonical private INI and verifies the existing dev HTTPS/operator-list endpoint.
After explicit owner approval, the live MySQL certificate was replaced and TLS
reloaded without a restart. The actual EXE's identity/configuration/schema checks
all pass, and both Astro sites remain available. The client now uses the public
CA file with native identity verification; no table data or schema was changed. The
owner has **skipped the proposed hours-long soak**; it is not an outstanding
requirement and no timed run is scheduled. The
[physical bench checklist](sc22-physical-bench-checklist.md) now specifies the
remaining hands-on checks and real mixed-monitor transitions. It is prepared,
not completed physical evidence. The
current artifact now passes [155 accelerated worker lifecycle cases and a normal GUI restart](sc22-worker-soak-acceptance.md):
owned processes/temp directories clear, extraction count stays bounded, and the
test draft restores after sign-in. Direct guest capture replaces unreliable
VirtualBox framebuffer images for this checkpoint. Physical bench acceptance
remains open; the hours-long run is skipped at the owner's request. The
approved [real update attempt and policy follow-up](sc22-update-policy-preflight.md)
provisioned the signed machine module but found Restricted PowerShell policy.
The app now explains that prerequisite before UAC; all 277 tests and the full
VM policy-message/retry check pass. The network is disconnected again, policy is
unchanged at that checkpoint. The later [real update completion pass](sc22-update-completion-acceptance.md)
now succeeds after the user's manual policy setup: an independent online scan
finds no available updates, with history/data unchanged and no restart needed.
The user requested retaining CurrentUser RemoteSigned in the reusable VM; its
network is disconnected again. Installation of a newly offered update remains
unproven. One earlier background Windows security update is recorded separately. The
release workflow now [builds the exact tested commit](sc22-release-commit-handoff.md)
instead of independently resolving the tag again; a moved-tag regression and
workflow lint pass locally. Hosted acceptance and production signing remain open. The
maintenance group's [native boundary fixtures](sc22-maintenance-boundary-acceptance.md)
now pass five elevated mutex/exit/timeout/recovery cases with harmless bodies;
drafts, configuration, update history and database snapshots stay unchanged.
Successful real updates, alternate-administrator and Sysprep checks remain open. The
maintenance group now has [VM preflight and confirmation evidence](sc22-maintenance-acceptance.md):
non-elevated operation, busy-dialog blocking and application-level decline pass;
real UAC refusal and approved nonzero exit now report failure correctly.
The approved-failure attempt preserved draft contents/configuration and released
its process/mutex; the app remains non-elevated. The offline VM lacks the
machine PSWindowsUpdate module, so successful installation/Sysprep remain open. The
update group now has [packaged signature-guard and signing-readiness evidence](sc22-update-readiness.md):
eight real packaged checks and 44 targeted tests passed; the missing DPI test is
now tracked. A production publisher and exact-tag hosted workflow are still
needed for release acceptance. The
[signed VM matrix](sc22-signed-update-acceptance.md) now passes eight real signed
scenarios and Tools-menu rollback with the user-approved guest test signer.
Temporary guest trust/key and disposable installations were removed after tests;
production publisher and hosted CI remain open. The
[packaged TLS checkpoint](sc22-tls-acceptance.md) passed against the actual
isolated service and native SQL driver, including private CA, wrong hostname,
expired/untrusted certificates and credentialled redirect refusal. Deployment
still needs its own final endpoints, trust chain and SQL identity smoke-tested.
The [SC22 report/session checkpoint](sc22-report-session-acceptance.md) continues
the workflow group: fresh authenticated report readback and a deliberate synthetic
session expiry now distinguish sign-in rejection from connection failure. The
reader disables ineffective Retry and explains how to sign in again. All 269
desktop tests pass. The packaged recovery flow restored the local draft and
reopened the original report, with report/assignment/receipt rows unchanged.
The [coordinated packaged workflow pass](sc22-assignment-workflow-acceptance.md)
is now complete against the matching isolated service: blank reason, recorded
exceptions, exact-payload retries, persistent uncertainty/restart, changed target,
order/legacy-trade conflicts, stale-list rejection, current removal and restore.
Historical reports and the secondary fixture stayed unchanged. The serial viewer
and removal confirmation now name their order; all 269 tests pass.
These observations reopen follow-ups on locally implemented items; they do not
mean the whole release or physical hardware has passed.

**SC21 maintenance usability follow-up is implemented locally and VM-tested:**
read-only machine-module preflight now stops before UAC with an actionable
message, retaining fresh authorization and the elevated recheck. Windows approval
cancellation has its own informational outcome; other startup failures remain
errors. All 275 tests pass. The full VM candidate displays the missing-module
message without UAC and preserves drafts/configuration/history. See
[maintenance preflight fix](sc21-maintenance-preflight-fix.md).

1. SC03 desktop trade removal, SC04 result policy and SC05 session protection are implemented locally. SC06 local MDM evidence, SC07 storage, SC08 measurement freshness, SC09 independent audio and SC10 hardware coverage are also implemented locally. SC11 worker lifecycle and cancellation is also implemented locally. SC12 layout, focus and scrolling is also implemented locally. SC13 accurate states and saved-report presentation is also implemented locally. SC14 fresh configuration is also implemented locally. SC15 read-only compatibility and explicit migrations are also implemented locally. SC16 operator sessions and permissions are also implemented locally. SC17 windowed helper IPC and script packaging are also implemented locally. SC18 update validation and rollback is also implemented locally. SC19 release identity and workflow guards are also implemented locally. SC20 source tracking and service boundaries is also implemented locally and staged. SC21 transport and scoped maintenance is also implemented locally. Continue with SC22 repeatable testing and portable baseline.
2. Complete the remaining SC22 release acceptance: SC21 UAC/maintenance, the hosted SC19 workflow, signed SC18 upgrade/rollback and physical bench checks. Packaged lab TLS and workflow matrices are complete; configure and smoke-test the deployment's final endpoints before rollout.
3. Back up and apply the SC15/SC16 migrations for the rollout environment and prepare the coordinated SC01–SC21 release with the matching server. The isolated packaged assignment/retry/order-and-trade-conflict/removal matrix is complete; deployment acceptance remains separate.
4. Complete outstanding SC08–SC13 hardware/lifecycle/native DPI and saved-report acceptance, with before/after screenshots and physical bench checks.
5. Finish SC22 release acceptance, including review/commit of the staged source cleanup. Portable-image export, verification and independent import/boot are complete.

See [the walkthrough record](vm-walkthrough-2026-10-21.md) for coverage and exclusions. No pending item is closed solely because its screen opened successfully.
