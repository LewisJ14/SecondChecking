# SC05 — preserve checks and bind actions to the resolved order

Implemented locally on 21 October 2026. The updated executable has not been
installed in the VM or released.

## Draft preservation

Hardware outcomes, active/superseded override history and legacy-history markers
are preserved as local drafts under
`%LOCALAPPDATA%/SecondChecking/check-drafts`. These are unsaved bench checks, not
confirmed Web-Tools reports. Files contain check data and identity keys, without
API keys or database credentials.

Drafts use the resolved database order ID and exact device serial. Repeat searches
and application restarts restore the corresponding draft. Marketplace aliases that
resolve to the same order use the same identity. Different orders and different
serials remain separate, including serials with leading zeroes.

Checks performed before selecting an order are kept as a device-only bench draft.
The first successful order lookup for that same device can transfer those checks
into its order draft. The device-only source is removed only after the destination
has been stored. It is not copied into later orders.

Draft writes replace complete JSON files atomically. They occur when test badges
update, before searching, and before normal close/update. If a write fails,
navigation/closing stops and the current checks remain in memory. Invalid draft
files are preserved and reported instead of being silently reset. A confirmed
assignment clears its matching draft; edits made after the uploaded snapshot
remain dirty and are preserved. Rejected or uncertain assignments do not clear it.

If the saved server results differ from a draft's original baseline, the app offers
Restore local draft, Discard it and load saved results, or Cancel lookup. Otherwise
the draft restores automatically. Local drafts should be used with one active
SecondChecking instance per bench/user; concurrent draft editing across multiple
app instances is not a supported merge workflow.

## Resolved context and actions

- The loaded order and device appear beside the comparison and in the hardware
  panel. A header distinguishes a local unsaved draft from the resolved lookup.
- Editing the search reference leaves the loaded order, checks, notes and action
  controls active. Only submitting a valid search switches context; invalid input
  leaves the loaded order intact. Controls continue using the displayed resolved
  order, independently of unsubmitted text. Device refresh also retains that order.
- Each lookup stages its data separately. It replaces visible results only after
  order resolution, SKU selection, result loading and comparison preparation finish.
  Late results from older generations or different submitted references are ignored.
- Missing orders/items, cancelled SKU/fallback selection and DB/API
  errors leave the order unresolved. Drafts remain available; assignment controls
  stay absent. Every completion clears the searching indicator and restores input.
- Delayed bench rendering and hash-status callbacks cannot replace a newer order
  context. Search cannot switch context while an assignment or hardware test runs.
  The test panel and app cannot close during an active hardware test; finish or
  cancel its owned result dialog first. Full Run All cancellation remains SC11.

The saved-result API introduced in SC04 is still required. SC05 adds no server
endpoint, schema change or database migration.

The 2026-10-28 submitted-search follow-up follows the owner's requested workflow.
Its real Tk regression edits the entry, exercises the retained actions, submits
invalid and missing references, restores a draft and refreshes the loaded device
while a different reference is still unsubmitted. Build output:
`SecondChecking Review/submitted-search-2026-10-28/ready/dist`.

## Verification

64 desktop tests passed on Python 3.12 (the packaging runtime), including:

- Repeated lookup and restart restoration with exact order/device isolation;
  bench-to-order transfer and preservation of override history.
- Changed server results and all Restore/Discard/Cancel choices; corrupt drafts;
  storage failure blocking navigation; confirmed-upload cleanup with later edits.
- Worker isolation and database, not-found, fallback, empty-order, SKU-cancel and
  report-load failure exits; stale lookup/default-screen callbacks.
- Actual hidden Tk controls: input edits destroy old buttons; guarded actions refuse
  unresolved context; failed lookup clears loading; returning to the original order
  restores the unsaved outcome and creates fresh controls.

All 71 tracked/new desktop Python files compiled, and the scoped whitespace check
passed. These are source/hidden-Tk checks, not a manual VM walkthrough or physical
hardware acceptance. No new Web-Tools changes were made for SC05. Package the paired
SC01–SC05 desktop/server and repeat isolated VM assignment/retry/readback acceptance
before rollout. SC06 is next in the improvement queue.
