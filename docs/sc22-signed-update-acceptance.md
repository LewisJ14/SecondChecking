# SC22 signed update and recovery VM acceptance — 27 October 2026

The offline VM passed eight real signed transaction scenarios and the app's
Tools-menu recovery flow, using a user-approved temporary guest test signer.
Publisher verification, health checks and GUI launches were not mocked or
disabled. No application source change was needed.

## Signer and artifacts

The user approved a two-day, non-exportable test key in the guest user's `My`
store and manually accepted Windows' trust warning. Only its public certificate
was added to that guest user's `Root` store. No host certificate store changed.
Script execution policy was scoped to the individual PowerShell process.

Microsoft SDK SignTool signed the two disposable copies. Independent Windows
Authenticode checks returned `Valid` and the same certificate DER SHA-256 pin
for both. The pin was supplied only to test-process environments. The VM remained
offline; no timestamp server or external network was used.

| Artifact | Review build | Signed SHA-256 |
| --- | --- | --- |
| 0.1.36 baseline | `107dcb03-fbf8-42e7-8aef-920e5175c8ad` | `be47cbb0a100ed8791969da2e154ae11b41ec1792c46b5392d4a788440f28803` |
| 0.1.37 lab candidate | `302b4a90-8cab-4715-9819-a53d45dabec1` | `220a6690aa1c91cccd929bd7f13bfe2dfd66e9ccaba4f4d18a905e1ab2263aeb` |

The repository remains at 0.1.36. The candidate was built outside the checkout
from the same tested source with only its copied `src/version.py` changed. It is
explicitly review-only and must not be published. No tag, commit, push, release
or hosted CI run was created.

## Passed scenarios

| Scenario | Observed result |
| --- | --- |
| Valid signed installation | Verified handoff, atomic replacement, signed backup, health checks and 0.1.37 startup; `installed` |
| Wrong publisher pin | Rejected before handoff; `blocked`; target unchanged |
| Cancelled handoff | Verified helper honoured cancellation while waiting for its identified parent; `blocked`; target unchanged |
| Invalid signature | Tampered candidate had matching recomputed fixture size/hash, leaving real publisher verification as the rejecting boundary; `failed_retained` |
| Version mismatch | Valid signed 0.1.37 candidate declared as 0.1.38 failed actual packaged version/health; `failed_retained` |
| Locked target | Real Windows sharing handle denied replacement; original and verified backup retained; `failed_retained` |
| Failed restart | Harness killed only the candidate startup process in the worker's owned descendant tree; updater restored/started 0.1.36; `rolled_back` |
| Interrupted re-entry | Durable post-replacement fixture with candidate and signed backup restored/started baseline; `rolled_back`. This simulates journal state, not actual power loss |

The initial installation attempt exposed a harness error: PID 0 was Windows' idle
process rather than an absent parent. The updater waited and retained the target.
That attempt was cancelled/archived; the corrected harness passed without
weakening product checks.

## Full GUI recovery and compatibility

The ordinary synthetic operator `review_operator_with_a_deliberately_long_name`
signed in on 0.1.37, loaded `test`, restored the local draft and read authenticated
saved report 6. **Tools > Restore previous app version** obtained actual service
authorization, completed its verified handoff and restarted 0.1.36. The restored
app signed in and reopened report 6 and its current reservation. Outcome dialogs
correctly showed installed/rolled-back results and running versions.

All transactions preserved configuration and the synthetic draft fixture. The
actual draft key/results/baseline matched immediately before and after Tools
recovery. Loading the draft beforehand normally rebased its baseline against the
saved report; that expected pre-recovery change is separate from rollback
preservation. No synthetic result was submitted as a physical hardware pass.

Before/after database evidence retains six reports, six assignment-history rows,
seven receipts and the `test` reservation with identical contents, plus an
unchanged secondary fixture. Authentication naturally exercised session/audit
records; this does not claim every database table was unchanged.

## Evidence and cleanup

Public results, scoped harness sources and native 1920×1080/100% screenshots are
outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-updates-2026-10-27`.
Each scenario has result/process-cleanup records. `signed-verification.json`
certifies the results, actual Tools rollback, unchanged report/assignment/receipt
data, and removal of the temporary root certificate and private key.

The user confirmed Windows' Root Certificate Store removal dialog. Both the
marked root certificate and private key are absent, and all signed fixture
processes stopped. Disposable installations, backups, worker extraction folders
and guest signer-tool/executable copies were deleted after public evidence was
saved. The normal unchanged review app was reopened using the original lab
settings. No VM clone, snapshot or OVA was created or rewritten.

Automatic approval review blocked deletion of the host's temporary
`candidate-build/work` directory; it remains in the external evidence folder.
No alternative deletion method was attempted. This does not affect VM cleanup.

## Remaining gates

Tests start from pre-staged local transaction plans. They prove real Windows
signatures, transaction failure handling and Tools recovery, not an end-to-end
GitHub download or production signing pipeline. The earlier 30 update and 14
provenance tests retain their documented mocked boundaries in
[update readiness](sc22-update-readiness.md).

Three broad groups remain: production signing/reviewed exact-tag hosted release
acceptance; elevated maintenance; and physical hardware/mixed-monitor/longer bench
checks. The lab signed upgrade/recovery portion and guest certificate/key cleanup
are complete.
