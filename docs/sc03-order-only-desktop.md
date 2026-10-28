# SC03 order-only desktop

Implemented locally on 21 October 2026 after the project owner decided to
remove trade workflows from SecondChecking. This supersedes the original
SC03 proposal to align the desktop trade report fields.

## Changes

- Removed the Order/Trade selector. Search Order is the only reference action.
- Removed trade lookup, product selection, result reload, assignment and notes
  code, and the trade-report upload helper.
- Removed persisted mode loading/saving. Existing `config.ini` files are not
  rewritten; a legacy `[app] mode = trade` value cannot enable the retired mode.
- Kept order lookup, comparison, notes, hardware tests, exact serial handling
  and server-owned order assignment/removal.
- Restricted the desktop mutation transport to order report and unassign
  endpoints. An unresolved journal from a retired workflow may have its receipt
  queried, but its mutation is never resent. An unknown result blocks a new
  assignment for that device and retains the journal for review in Web-Tools.
  A confirmed earlier receipt is not presented as success for a new order.

No Web-Tools code, database tables, trade records or migration state were
changed. The server can still identify a device owned by an existing trade
job and require confirmation before assigning it to an order.

## Verification

The desktop suite passes 39 tests on Python 3.12 and 3.13. Coverage includes
the actual order-only header, note placeholder and assignment/view callbacks
in a fresh hidden Tk app, order dispatch despite legacy mode state,
invalid-reference rejection, and
retired pending-request preservation/reconciliation. Existing order API,
receipt, exact-identifier and viewer tests continue to pass.

The desktop transport timeout/retry check against the actual Flask endpoints
also passed. All 34 desktop source/test Python files compiled.

Trade-specific desktop tests were removed with the retired entry points.
Web-Tools trade transaction tests remain valid server coverage.

## Remaining review work

The original trade field-parity work is cancelled for this desktop. The
order-only saved-report improvements remain under SC13: show the saved tests,
batteries, timestamps, operator, receipt and available provenance. Override
policy/provenance remains SC04, and protecting unsaved order results remains
SC05. The historical VM walkthrough still describes the earlier trade-enabled
0.1.36 package; it is not a screenshot record of this change.

This is an unreleased local change. Installing the new desktop still requires
the coordinated SC01 server/client rollout. No production deployment was made.

The order-only executable and source/artifact hash manifest are staged at
`C:\Users\PCR\Documents\SecondChecking Review\sc03-order-only-build`.
It is built with Python 3.12.0 and PyInstaller 6.3.0 and still displays 0.1.36;
use the manifest to identify it. Private configuration was not copied into
the candidate. The existing VM app was not replaced.
