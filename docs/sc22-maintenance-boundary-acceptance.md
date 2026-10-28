# SC22 native maintenance boundary fixtures — 27 October 2026

Five elevated native fixture cases passed in `SecondChecking-Test`. This advances
the maintenance acceptance group; it does not establish successful Windows Update
installation, alternate-administrator operation or Sysprep acceptance.

## Scope and provenance

The external, windowed probe bundles the actual `services.maintenance` source
matching full review build `69e21d4c-28c3-46bb-824f-7a2dc15288e3`, version 0.1.36.
The source SHA-256 is
`912a8808dc71c83ca8696984e3019f9c5c8c24d841274e68beb5d3e79fea729b`.
Six shared native runtime binaries match that full application. An additional
`win32security` dependency observes process tokens only.

Only the action-body supplier is replaced in the probe's memory, with harmless
owned marker/sleep/throw scripts. The product's global mutex wrapper,
ShellExecuteEx elevation, process handles, wait and exit/error handling run
unchanged. Child tokens are verified elevated. The user approved UAC inside the
guest; no host mouse or keyboard was controlled. Earlier unanswered prompts
expired and were reopened without launching concurrent copies.

## Results

- A mutex owned by another process blocks the action before its marker is written.
- Releasing the mutex allows success, with no mutex remaining afterward.
- A nonzero fixture exit reports failure and releases the mutex.
- A short wait timeout reports an unconfirmed outcome. Its actual child remains
  alive and blocks a second action, then finishes naturally without termination.
- An abandoned mutex is recovered and released. Only the probe's own harmless
  fixture owner is terminated to create this condition.

The elevated suite's `result.json`, case markers and final process/mutex check
establish completion. The outer PowerShell supervisor exits before its windowed
child completes, so its zero exit alone is not treated as proof of suite success.

The current full application executable remains SHA-256
`c754a42027cc1966e81e3d62fc3a6c6adf10e3e5e1f4c4a70eb2c961182a5cfa`.
Both application processes remain non-elevated. No probe, consent, PowerShell or
Sysprep process remains, and the named maintenance mutex is absent.

Before/after configuration, draft bytes and normalized draft contents match.
Update history remains at 12 entries and no PSWindowsUpdate module was installed.
The complete public database snapshots match: six reports, six assignment-history
rows, seven receipts, the same `test` reservation and unchanged secondary fixture.
The inventory's `appSha256` field tracks the retained older review executable;
`final-state.json` separately verifies the current full application above.

## Evidence and remaining work

Public evidence and the reproducible probe are outside Git at
`C:\Users\PCR\Documents\SecondChecking Review\sc21-maintenance-boundaries-2026-10-27`:
source/package provenance, native results, before/after inventory and database
snapshots, final process state and `verification.json` (all checks true).
No product source changed; the previous full product suite remains 275 passing
tests. The guest network remains disconnected. No update, module installation,
Sysprep, new image or OVA export was performed.

The fixtures do not exercise the full GUI authorization chain or actual
maintenance action bodies. Those guards have separate
[packaged GUI evidence](sc22-maintenance-acceptance.md) and
[preflight evidence](sc21-maintenance-preflight-fix.md). Real successful update,
alternate-administrator credentials and disposable-environment Sysprep acceptance
remain open. Production signing/hosted release and physical bench/monitor
acceptance also remain open.
