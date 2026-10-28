# SC13 — saved reports and accurate states

Implemented locally on 22 October 2026 in SecondChecking and Web-Tools. No new
database migration is needed. Deploy the matching server for full report viewing;
the executable and VM have not been updated with this change.

## Saved report workflow

The serial viewer now offers **View Report** for the exact selected serial. It
loads the authenticated saved-results endpoint in a worker and displays the result
in a resizable, scrollable, read-only dialog. It no longer performs a synchronous
legacy specification query on the Tk thread or substitutes live measurements for
saved data. The existing exact-identifier selection, pagination and removal guards
are preserved. **Reload list** is available on empty/failed lists and disabled
while list loading/removal is active.

The report shows:

- Canonical order number/ID, lookup reference, exact serial, SKU, report ID,
  checking operator and recorded report time.
- Current assignment metadata when loaded, separately from a historical committed
  receipt for the selected report. A receipt is shown only when the stored
  operation matches the report, order, serial and assignment action; missing or
  mismatched receipt links remain not recorded.
- All eight saved checks, including activation and Wi-Fi, with explicit states,
  active override badges and unknown-history markers.
- Active and superseded override decisions, original/previous/replacement results,
  operator, reason and time.
- Saved specification snapshot, measurement sources/time, coverage, storage
  inventory/review, both battery values/evidence/export metadata, qualified local
  MDM evidence and the assignment review/exception reason.

Nested details use labelled, indented text. Uploaded CSV/hash bodies, private spec
keys and the complete raw request payload are not projected into this view. The
report labels itself as saved data; use Reload to refresh it. Per-check capture
time is shown where the saved coverage/evidence contains it. Missing source, time
or coverage is not inferred. Timestamps are displayed as recorded; a naive database
timestamp is not silently assigned a timezone.

The service may resolve an external lookup reference to a different canonical
order number. Both are shown. The desktop verifies the returned lookup reference
and exact serial; it does not compare an external alias directly with the canonical
order label. Receipt matching respects SC01's uppercase lock identifier while
retaining the exact serial in the report/response.

## Distinct states and retry

| State | Behaviour |
| --- | --- |
| Loading | Identifies the requested order/serial, disables Reload and explains that Close stops waiting without changing saved data. |
| Full saved report | Displays saved fields and provenance as read-only evidence. |
| Legacy serial row only | Displays the available row specifications/results with unknown override history. Full report ID, checking time/operator and receipt are not invented. Available current assignment metadata is separate. |
| No current assignment | Reports that no current assignment/report was found, suggests reloading the list and does not infer saved test results. Historical reports are not returned as a current assignment after removal. |
| Connection/access/format/version error | Reports unavailable with Retry. An older service lacking the full report projection prompts a matching-server upgrade. A successful body without an explicit `found` boolean is rejected rather than interpreted as a fresh device. |
| Timeout or close | The dialog stops waiting after 20 seconds or immediately on Close. HTTP I/O retains the existing 15-second request timeout. Generation checks discard stale replies after Retry; workers never schedule Tk calls. |

Opening a fresh hardware panel no longer displays “Not connected to database” just
because its checks are Not Run. The panel instead says that no checks are recorded
in this session and offers a clear starting action. Existing results get a neutral
session message; the result values themselves do not claim database connectivity.

## Update-check message

The headless update helper emits an explicit versioned result for a successful
no-newer-release check, including the running version, or an explicit available
manifest. Empty output, malformed output, unsupported states and mismatched
running versions are failures/unknown, not “already up to date.” An older helper
can still explicitly announce an available manifest. This changes result/message
validation only; release authenticity, updater rollback and exact packaged helper
acceptance remain SC17–SC19.

## Verification and acceptance limits

122 desktop tests and 33 real Flask transaction tests passed against isolated
SQLite. All 88 desktop and 196 selected/tracked server Python files compiled.
Tests cover full saved evidence, legacy/absent states, report identity, order
aliases, leading-zero/mixed-case serials, matched/mismatched receipts, omitted file
bodies, authentication, hidden Tk error/retry/timeout/close behaviour, fresh-session
messages and explicit headless update results. Existing serial selection/removal
tests continue to prove exact identifiers and absence of local assignment writes.

Before release, build the exact executable and deploy its matching server in the
isolated VM environment. Assign synthetic devices with a failed/cancelled check,
an override history, dual batteries and coverage; reopen View Report and compare
every field with the saved report/receipt. Test legacy rows, missing API access,
removed/reassigned serials, retry after service loss, close during a slow read,
long reports at native Windows DPI settings and the packaged updater's explicit
no-update/error responses. These packaged, visual and paired-environment checks
remain pending. SC14 fresh configuration is next.
