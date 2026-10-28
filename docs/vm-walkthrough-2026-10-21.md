# SecondChecking VM walkthrough on 21 October 2026

## Scope and provenance

Interactive review of the packaged Windows app in VirtualBox `SecondChecking-Test`, Windows 11 Enterprise Evaluation, guest display 1024×768. The app title/version was 0.1.36 and the operator was the synthetic `tester` account. The session was already logged in; this pass did not repeat authentication or password reset.

The payload manifest identifies base commit `1895a9ba8b4ed643e379a86b88bd2502736adc32` plus the earlier local fixes. The executable predates SC01/SC02. This is evidence about that packaged baseline, not acceptance of the later source changes.

The guest used its own MariaDB database `secondchecking_test` and API simulator at `127.0.0.1:5001`. All assignments and notes below were synthetic. No production records were used. Guest fixture preparation added a trade job with reference `test`; its reference was temporarily changed while probing lookup behavior, then restored. The actual no-match query was subsequently entered as `testx` through the VM soft keyboard.

A safety snapshot was taken before the walkthrough: `Before VM walkthrough 2026-10-21`, UUID `bfd820ce-addf-4bde-8a85-007ce070be0a`. The earlier `Ready-to-test` snapshot remains available. A snapshot is not an independently portable OVA/OVF image.

## Interactive coverage

| Area | Action and observed outcome | Interpretation |
| --- | --- | --- |
| Main screen | Inspected restored and maximized app windows. Long SKU overlapped Assign Serial in both layouts. | SC12 confirmed at 1024×768. Other DPI scales remain untested. |
| Empty serial list | Opened View Serials before assignment. Blank list, Page 1 of 1, enabled actions. View Spec gave No Selection warning. | SC13; disable unavailable actions and explain empty state. |
| Order notes | Entered synthetic note `x` with VM soft keyboard and saved it. Guest SQL readback confirmed order 1 note `x`. | Basic save proved; concurrency, cancellation and failure recovery remain open. |
| Fresh hardware panel | Opened with all tests Not Run. Warning claimed no database connection. | Source condition is all results Not Run, not connection status; SC13. |
| Webcam | Opened test; No camera found error; panel result became FAIL. Panel was recovered through Test Menu after dialog dismissal. | Unavailable-device flow exercised, physical camera not tested. |
| Keyboard | Inspected layout, closed test, then closed result prompt using X. Result became FAIL. | SC04 cancellation semantics and SC12 narrow labels. Physical key coverage not proved. |
| Speaker and microphone | Speaker test produced no audio device/playback error. Both speaker and microphone became FAIL. | SC09 dependency confirmed. Audio quality and noise-only detection require physical tests. |
| Display | Clicked through red, green, blue, white and black screens, then chose Yes. Panel showed PASS. | Virtual UI sequence proved, not physical pixel quality. No visible advance/cancel guidance on color screens. |
| USB | Inspected empty removable-device list. Closed it; result prompt appeared; chose No. | Basic UI exercised; no physical device/port was tested. |
| Wi-Fi override | Automatic test showed FAIL. Override offered Pass, Fail, Not Run. Chose Pass; ordinary green PASS displayed, no reason field. | SC04 provenance and SC10 absent-device semantics. This was an artificial result in an isolated lab. |
| Activation | Inspected options View Product Key and Reactivate BIOS Key; closed dialog. | No key viewed and no licensing change attempted. |
| Order assignment | Cancelled first confirmation, then completed assignment against success-mode simulator with failed test results. Warning mentioned spec mismatches, not those failures. Selected ordinary OK on success dialog. | SC04 confirmed. No Sysprep invoked. Simulator accepted the report; production policy not validated. |
| Saved order report | Selected synthetic serial in populated list and opened View Spec. Specs/MDM displayed; saved test outcomes absent. | Expand report readback in SC03 and serial viewer acceptance. |
| API rejection | Set guest simulator to unauthorized, retried assignment and confirmed the existing-record prompt. Assignment Not Confirmed showed Unauthorized. | Correct rejection message observed. Guest report count stayed at one until later trade success. |
| Mode switch | Changed Order to Trade before searching. Old order comparison and actions stayed visible. | SC05 context invalidation required; do not infer an actual wrong-record write from appearance alone. |
| Trade lookup | Loaded reference `test`, inspected comparison and synthetic note. UI still used Order Notes heading and had no equivalent View Serials action. | SC03 parity and SC13 wording. |
| Run All | Ran through audio error, display sequence, keyboard No, missing camera and USB No. Reopened panel; results present, footer said Ready to run hardware checks. | Sequence exercised; no explicit completion summary or cancellation control. |
| Unsaved results | Closed panel after Run All, repeated same trade search, reopened tests. Results returned to PENDING without a discard warning. | SC05 reproduced interactively. |
| Trade assignment | Completed synthetic order-to-trade reassignment with incomplete tests after confirmation. Success showed one assigned serial. | Old build + simulator path exercised, not SC01 acceptance. |
| No match | Entered `testx`, searched Trade. Correct not-found dialog appeared. After dismissal, prior comparison and Assign Serial remained visible; Searching indicator continued in repeated observations. | SC05/SC13 stale-result and loading-state cleanup. Actual submission after no-match was not attempted. |
| Application updates | Selected Check for App Updates against local simulator version 0.0.0; No Updates dialog appeared. | Only no-update branch proved. This does not mean GitHub's latest build was checked. |
| Maintenance | Inspected menu labels and OK versus OK & Sysprep options. | Windows Update, Sysprep, download/install and rollback were not executed. |

## Readback and retained evidence

Guest database checks confirmed one captured order report after the successful order assignment; the rejected attempt added none. Its saved display/keyboard/Wi-Fi results were `pass` / `fail` / `pass`. The Wi-Fi value was the synthetic override. After successful trade reassignment there were two captured reports, no order assignment for that serial, and one trade assignment for reference `test`. This does not establish stock-reservation consistency: the simulator does not model the real server transaction contract.

Evidence folder: `C:\Users\PCR\Documents\SecondChecking Review\vm-evidence`.

| File | Evidence |
| --- | --- |
| 01-baseline-layout.png | Restored app layout. |
| 02-maximized-layout.png | Maximized background and empty serial viewer. |
| 03-test-results-connection-warning.png | Misleading fresh-session database warning. |
| 04-keyboard-labels.png | Keyboard layout and clipped labels. |
| 05-wifi-override.png | Override dialog with no reason field. |
| 06-assigned-with-failed-tests.png | Order assignment success. Read with the observed failures and SQL readback above. |
| 07-saved-report-missing-results.png | View Spec fields and absent test results. |
| 08-api-rejection.png | Unauthorized assignment response. |
| 09-mode-switch-stale-order.png | Trade selector with prior order comparison. |
| 10-run-all-completion.png | Mixed Run All results and generic Ready footer. |
| 11-search-cleared-unsaved-results.png | PENDING results after repeat search. |
| 12-trade-assignment-success.png | Synthetic trade assignment success. |
| 13-no-match-stale-comparison.png | Unmatched input with old results, assignment action and loading indicator. |

## Remaining acceptance work

Retest the new SC01/SC02 packaged client against a matching real Web-Tools test instance. Cover timeout after commit, retry reconciliation, concurrent assignment, reservation consistency and unassign. Add API 500, slow, missing-stock, malformed responses and updater corruption/rollback cases; those simulator modes were not exercised in this pass.

Authentication/reset flows, multiple-match/item-selection dialogs, high-DPI layouts, note save failures, worker-close races and actual assignment after a no-match remain additional acceptance cases. Physical batteries, microphone/speakers, webcam, USB ports, Wi-Fi, activation, MDM tenant state and hash enrolment require known devices. Maintenance actions need their own disposable-machine checks. No release readiness claim is made from this walkthrough.

The corresponding actions and revised order are recorded in [the improvement plan](app-improvement-plan.md).
