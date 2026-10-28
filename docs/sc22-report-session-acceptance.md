# SC22 report readback and operator-session recovery — 26 October 2026

Follow-up: the [coordinated packaged workflow matrix](sc22-assignment-workflow-acceptance.md)
now completes the synthetic workflow group. Four broad acceptance groups remain;
the five-group count below describes this earlier report/session checkpoint.

Saved-report reads now distinguish sign-in rejection from a service outage.
A locally expired/missing session is rejected before sending a request. HTTP 401
invalidates the matching in-memory session and gives sign-in instructions rather
than displaying a raw URL or suggesting that Retry can renew authentication.
The dialog keeps Close available and disables Reload / Retry in this state.
Connection failures retain their existing retry behavior; HTTP 403 does not
discard a valid operator session.

Invalidation compares the request's operator generation under the session lock.
A delayed 401 from an earlier request cannot clear a newer operator. No server
authentication policy, expiry period or tester permissions were changed.

All **269 desktop tests pass**, including local expiry without a network call,
401 invalidation/redaction, a late 401 after another sign-in, 403 preservation,
and the actual report dialog's sign-in-required/Close state. Tracked Python files
compile. The suite retains a Tcl theme-event diagnostic after a test interpreter
is destroyed; it reports no test failures.

The full unsigned review executable has build UUID
`bd985ba6-ada4-484e-9a3b-dd5703d938e2`, SHA-256
`536caaffab9da22c8fb1d0ccaffdb4c907b96ae9bbc9deb6ef349482a03bdb51`.
The frozen runtime is Python 3.12. Evidence is outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-report-session-2026-10-26`;
the guest executable is `C:\SC22Visual\report-session-fix.exe`.

## Remaining release groups

There are **five acceptance groups**, each containing several checks.
SC01–SC21 implementations and VR01–VR08 corrections are local.

1. Packaged workflows: result policies, assignment, lost-response retry, conflicts,
   report readback, session recovery and removal against matching isolated routes.
2. Actual service/private-CA and native SQL TLS.
3. Source review/commit, hosted CI, signed upgrade/failure/rollback.
4. Elevation and real maintenance on a suitable disposable machine.
5. Physical hardware, mixed-monitor DPI transitions and longer bench acceptance.

This checkpoint covers report/session behavior within group 1. It does not close
the whole group or approve a release. No commit, push or OVA update is included.

## Packaged VM evidence

The full candidate ran at native 1920×1080/100% as a standard guest user, using
the actual matching Web-Tools routes and isolated MariaDB schema
`sc22_visual_20261023`. Guest-only controls left the host mouse and keyboard alone.

1. Fresh `tester` sign-in and order `test` lookup loaded authenticated report 2
   for the exact VirtualBox serial. The reader showed its saved timestamp, current
   assignment, historical receipt and saved result states. Scrolling exposed both
   90.9% battery snapshots and their capacity evidence.
2. A guarded guest fixture expired the two active synthetic tester sessions only
   in that isolated schema. Reload received server rejection while the desktop
   session was still within its local lifetime. The dialog removed the previous
   report, showed explicit sign-in instructions, disabled Reload / Retry and kept
   Close available. It did not display the raw request URL.
3. Following those instructions closed the report/list and used Operator > Lock /
   change operator. The locked screen confirmed local drafts were preserved; its
   sign-in button opened a new process of the same review build and accepted the
   synthetic credentials again.
4. Looking up `test` in that fresh process reported “Local draft restored; not
   saved to Web-Tools.” The serial viewer reopened authenticated report 2 with
   its original saved timestamp, assignment and receipt. The new GUI process
   was PID 328, replacing PID 7556 from the deliberately expired session.

The two report rows, two assignment rows and two operation receipts retained
identical complete-row SHA-256 digests before and immediately after expiry.
The same digests also matched after signing back in and reopening the report.
Authentication session/audit changes are expected. The fixture never changes
production data, session policy, Windows security, report contents or assignments.
`db-before.json` and `db-expiry.json` record counts/digests without credentials or
session tokens. Screenshots preserve successful readback and the rejection state.
The guest executable's SHA-256 matched the host build. Source/build hashes and
the screenshot index are recorded in `verification.json`. The application remains
running with `test` loaded at 1080p/100%. The retained OVA is unchanged.
