# Physical bench findings and diagnostic logging — 28 October 2026

The supplied log's latest test began at 13:31 and ended at 13:35. The camera's
specific error was not recorded. A fixed 25-second camera budget was reproduced
with an otherwise fresh preview; this establishes a code defect, rather than
proving the exact unrecorded error seen on that device.

## Corrections

- Camera discovery retains a bounded startup budget. New, fresh frame sequence
  numbers renew a five-second preview lease, allowing operator inspection beyond
  25 seconds. Repeated or stale frames do not extend the lease. Cancellation and
  the runner's existing overall limit remain available.
- Each live battery read initialises COM, creates its own WMI proxies, releases
  them and uninitialises COM in the same thread. A global cached WMI interface is
  no longer shared across the lookup worker and Tk/other threads.
- CPU specifications accept explicit comma-separated alternatives. Exact Intel
  CPU models can match verbose Windows captions. Model aliases tolerate the
  existing ThinkPad prefix and Notebook PC suffix; T480 and T480s remain distinct.
- A generic Windows 10/11 requirement accepts its standard editions. An explicit
  edition requirement still rejects a different edition. Activation remains a
  separate test: the reported Windows notification mode is not resolved by an
  edition match and requires the appropriate valid licence on that machine.
- GitHub repository owner/name case is canonicalised without changing asset-path
  case or weakening origin, version, digest or publisher requirements. The live
  0.1.38 manifest used LewisJ14 rather than lewisj14 and now passes validation.
  Checking it did not install, publish or release an update.

## Diagnostic records and privacy

New log lines have local timestamps with milliseconds and UTC offsets, severity,
a random per-process run ID, PID and thread ID. Structured diagnostic events
record operation/stage, safe outcome and counts, exception types, numeric error
codes and source filename/function/line locations. Exception chains are bounded;
exception arguments, local variables, source lines and raw response bodies are
not included in those diagnostic records. Helper request IDs link worker failures
to the parent error without including credentials or device identifiers.

Camera start, first preview, errors and outcomes are logged. The runner records
test starts and committed outcomes, including the combined microphone outcome.
Tk callback exceptions and uncaught background-thread failures are captured.
Update manifest failures, helper/native worker errors, WMI failures, inventory,
search, serial-viewer and note-save failures have structured records.

Legacy text events also pass through bounded, single-line redaction. Configured
private values and secret-bearing environment values are masked, with additional
filters for labelled credentials, authorisation, URLs, email/IP/MAC addresses,
UUIDs, serials, usernames, file paths, subprocess commands, SQL and payload text.
The verbose footer event containing raw MDM observations was replaced with a
state/count event. Logging failures do not interrupt the app. Existing bounded
5 MiB rotation is retained, with thread serialisation for append/rotation.

These changes apply to newly written records. They do not rewrite the supplied
historical log or remove sensitive content from old copies/archives. Tests use
synthetic secrets and never real credentials, camera imagery or microphone audio.

## Verification and delivery

Focused regressions simulate more than 60 seconds of fresh camera frames followed
by a stall, concurrent battery COM apartments, positive and negative alias/edition
matches, repository-case and asset-origin validation, and secret/identifier/log
injection filtering. The live manifest check is read-only; physical camera and
activation acceptance must be repeated on the user's bench machine.

Build and check evidence are outside Git at
`SecondChecking Review/bench-fixes-diagnostics-2026-10-28/ready`.
All 298 desktop tests pass, and all source/test files compile. The packaged
identity and portable configuration are checked from an unrelated working
directory. A real packaged read-only update helper accepts the live manifest;
a deliberately invalid helper request verifies error recording without
writing its supplied value or configured credentials into the log. Its synthetic
log is retained with the evidence rather than deployed beside the executable.
The `dist` folder contains the executable, existing private configuration and
public CA certificate. No database/server changes, automatic activation, Git
publication or VM/OVA changes are part of this follow-up.
