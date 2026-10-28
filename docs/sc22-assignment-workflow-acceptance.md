# SC22 packaged assignment workflow acceptance — 26 October 2026

This checkpoint runs the full windowed review executable against the actual
matching Web-Tools service and isolated MariaDB schema `sc22_visual_20261023`.
The candidate is build `bd985ba6-ada4-484e-9a3b-dd5703d938e2`, SHA-256
`536caaffab9da22c8fb1d0ccaffdb4c907b96ae9bbc9deb6ef349482a03bdb51`.
It includes the preceding report/session correction; 269 desktop tests passed
for that source. Source was unchanged during the matrix. The UI follow-up below
was built separately afterward.

The guest-only fault proxy listens on `127.0.0.1:5003` and forwards the real
service at `127.0.0.1:5002`. Process-local settings point the review app at it;
`config.ini` is unchanged. A separate lab profile isolates pending operations and
drafts. The ledger stores operation IDs, payload digests, reasons and response
identities, with no authentication headers, passwords or session tokens.

Evidence and harness sources are outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-assignment-workflows-2026-10-26`.
Six relevant server source hashes matched the host checkout. No Windows security
settings, production records, VM images or OVA were changed.

## Results

- **Blank review reason:** the real review dialog blocked assignment with a
  validation message. Database report, assignment and receipt counts stayed at
  two, and no report POST was sent.
- **Lost committed response:** the first report POST committed and its response
  was deliberately dropped. The packaged app retried the identical operation
  `201d7c17-0262-424b-ad44-6517261ef266` with an identical payload digest.
  Both responses referenced report/reservation 3. Only one new report,
  reservation and receipt existed; the success dialog labelled the recovered
  historical confirmation. The explicit review reason was saved with the
  failed/incomplete result states.
- **Fully unconfirmed outcome:** all four responses for operation
  `356c42a8-bd85-47d6-8045-10b87a51fe02` were dropped and its receipt lookup was
  temporarily hidden. All four requests had the same payload digest and returned
  the same report/reservation 4 upstream. The app showed Assignment Not Confirmed
  and retained one pending operation. Its complete-file digest remained unchanged
  after normal app exit. The harness confirmed its journal contained no API key.

- **Restart with a different target:** a new process reopened the same lab profile
  and selected `test-other`. Its assignment attempt reconciled the existing
  operation by GET, cleared the pending JSON and showed “Previous operation was
  confirmed. Review the current assignment, then retry the new change.” It sent
  no new report POST, created no duplicate report/reservation/receipt and left the
  current order as `test`. This was a normal app restart, not a power-loss test.

- **Order and legacy trade conflict:** a guarded synthetic legacy trade link was
  added for the lab serial. The actual service rejected reassignment, describing
  its order reservation, order and legacy trade ownership. Choosing No preserved
  both links, created no report/receipt and cleared the pending operation.
  Choosing Yes on a fresh attempt used a new operation ID and confirmed-state
  token, created exactly report/reservation 5, moved ownership to `test-other`
  and removed the legacy trade serial link. The empty synthetic job remains as
  fixture history.
- **Stale-list removal:** the original `test` serial window stayed open while the
  main window moved the device to `test-other`. Removal from that old list returned
  409 and explained that the serial had moved. The new owner and all report/receipt
  counts were preserved; the rejected request left no journal.
- **Expired removal session:** the session naturally expired before the next
  removal. The app required sign-in and changed no ownership. A fresh process and
  sign-in resumed testing without extending or bypassing the session policy.
- **Current removal and restore:** removal from `test-other` released its
  reservation, emptied the list and added only one removal receipt. Reports
  stayed at five. A recorded-reason assignment restored `test`, producing
  report/reservation 6 and receipt 7. No pending operation or legacy trade serial
  link remained. Reports 1 and 2 retained their exact row digests throughout;
  the independent secondary device fixture also remained unchanged.

The external `verify.py` checks thirteen database stages, replay counts and payload
identity, historical reports, the secondary fixture, recorded reasons, rejected
operation receipt absence and matching server source hashes. `verification.json`
records assertions and screenshot digests. These exercises deliberately created
synthetic report/assignment history; the database as a whole was not unchanged.
The fault proxy was reset and stopped after testing.

## Serial order context follow-up

The stale-list exercise exposed missing context: serial windows and removal
confirmation omitted the order name. The viewer now includes its order in the
title, and confirmation names the exact order and raw serial. The existing
transaction/UI test asserts both strings and preservation of leading zeroes.
All **269 tests pass**; tracked Python sources compile.

The separate unsigned review build is `107dcb03-fbf8-42e7-8aef-920e5175c8ad`,
SHA-256 `b46774983149682a1b71e4030ac17b681090a540a4f702fc23bb40cbcbdf15cb`.
Its source manifest differs from the matrix artifact only in
`src/logic/view_serials_logic.py` and `tests/test_assignment_transactions.py`.
Assignment transaction code is identical.

The rebuilt executable was copied into the same visible VM and its digest
matched. With normal service port 5002 restored, a fresh tester sign-in loaded
`test`. The existing local draft conflict prompt was handled by restoring the
draft; no draft was discarded. The viewer title and exact-order removal wording
were visually verified at native 1920×1080/100%. Choosing No preserved the restored
assignment. The app remains open on `test`; the fault proxy is stopped.

## Remaining acceptance

Follow-up: [packaged TLS acceptance](sc22-tls-acceptance.md) is now complete,
leaving three broad groups. The four-group count below records this workflow
checkpoint's earlier status.

The coordinated synthetic workflow group is complete with the preceding
[report/session checkpoint](sc22-report-session-acceptance.md). Four broad groups
remain: actual service/private-CA/native SQL TLS; reviewed source and hosted CI
with signed upgrade/failure/rollback; elevated maintenance on a suitable disposable
machine; and physical hardware/mixed-monitor/longer bench acceptance.

These are synthetic lab assignments with recorded exceptions; they do not
establish physical hardware acceptance or release approval.
