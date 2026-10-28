# SC04 — failed checks, manual overrides and final review

Implemented locally on 21 October 2026. Owner policy: **allow assignment with a
recorded reason**. Matching desktop/server deployment and VM acceptance remain.

## Behaviour

Every assignment opens a scrollable final review identifying the resolved order,
serial, SKU and operator. It lists keyboard, speaker, microphone, display, webcam,
USB, Wi-Fi and activation outcomes. Failed, incomplete, cancelled, unavailable and
error states remain distinct. Active overrides show the original/replacement
outcome, operator and reason.

A non-empty reason (maximum 2,000 characters) is required when any check is not a
pass, an override is active, legacy history is unknown, or the existing MDM/spec
comparison warns. Cancel sends no assignment request. All-pass reports still need
explicit confirmation.

Wi-Fi overrides require a signed-in operator and their own reason. History retains
the original result, previous result, replacement, operator, UTC decision time and
active/superseded state. The badge reads **OVERRIDDEN PASS/FAIL**, including after
reloading a saved report. Repeating an override retains the first original result.
An explicit retest supersedes active overrides without deleting their history.
Opening the panel does not automatically overwrite an active Wi-Fi override.

Display, keyboard, webcam, USB and speaker result dialogs now have Cancel. Closing
a result dialog records `cancelled`, rather than asserting failure. Escape or
closing the full-screen display sequence cancels directly. This does not implement
Run All cancellation or independent speaker/microphone measurement.

## Server contract and storage

`POST /api/stock_units/check-report` requires `result_policy_version: 1`, all eight
canonical `test_results`, `test_overrides` history and an `assignment_review` with
operator/time/reason. Canonical states are `pass`, `fail`, `n/a`, `cancelled`,
`unavailable` and `error`.

The server validates the review before creating/restoring stock, moving ownership,
or saving a report. Missing reasons, inconsistent active overrides, absent result
states, invalid provenance and conflicting activation values reject the operation.
Rejected requests leave no assignment, report or committed operation receipt.
Existing confirmed operation receipts remain replayable.

History and review are stored in the existing `StockUnitCheckReport.report_payload`
JSON, alongside the test outcomes. **No new database migration is required.**

Authenticated `GET /api/stock_units/second-check-results` takes `order_number` and
`serial_number`. It returns results/provenance for that currently assigned device
and order, or `found: false`. The desktop uses this service instead of selecting
`test_wifi` from `order_serials`: that column is not defined by the Web-Tools model.
Wi-Fi is preserved in the report JSON. Read failures are surfaced; there is no
fallback that silently presents an overridden pass without its history.

Legacy records lacking provenance are labelled **HISTORY UNKNOWN**. That uncertainty
is retained in `assignment_review.history_unknown` when copied into a new report;
individual fresh measurements remove their corresponding unknown-history marker.
The endpoint intentionally omits raw hash/battery file content. The full saved
report viewer remains SC13.

## Verification

- 49 desktop tests passed on Python 3.12, including actual hidden Tk controls for
  reason validation, cancellation, override badges and display prompt closure.
- 22 real Flask assignment tests passed using isolated SQLite, including required
  reasons, accepted non-pass exceptions, rollback on rejection, override JSON
  persistence/readback, authenticated order scoping and response-loss retries.
- All 194 tracked/new Web-Tools Python files and 68 tracked/new desktop Python files
  compiled successfully. No additional database migration was run.

The existing SC01 MariaDB transaction verification is historical evidence; this
SC04 run used SQLite. No updated executable has been installed in the VM or
published. The existing SC03 executable does not contain SC04.

## Rollout and remaining scope

Deploy this desktop and the matching result-policy version 1 server together, after
isolated VM acceptance. Stop older desktop clients: the server rejects new order
reports without the review contract. The desktop checks server support before
submitting a version 1 report. A changed review timestamp alone does not replace an
uncertain operation; changed reasons or result history remain different decisions.

Operator identity remains supplied by the desktop under the existing shared API
key. This records the signed-in bench operator; it does not establish server-side
per-user permissions or supervisor approval. SC16 remains open. SC09/SC10 retain
the work to distinguish absent devices/test errors and separate audio outcomes;
SC11 retains Run All lifecycle work. SC05 session protection is next.
