# SC11 — responsive checks and cancellation

Implemented locally on 22 October 2026. The exact candidate executable has not
been rebuilt or deployed to the VM. No database migration or additional server
contract change is required; use the matching SC01–SC10 service for reports.

## Runner behaviour

Run All now advances through Tk callbacks rather than starting a thread that
waits indefinitely on an event. The panel identifies the current check and its
position in the sequence. Only one attempt can run at once; automatic Wi-Fi
startup is cancelled when an explicit run or override starts. An active check
also blocks new activation/override actions.

The persistent **Cancel current / remaining tests** control stops the current
attempt, runs its registered cleanup, and stops the remaining sequence. Cancel
inside a test also stops Run All. Closing or destroying the panel cancels its
active attempt and owned jobs; it does not open a result question afterwards.
Checks not started keep their previous results and override/coverage history.
Completed checks are preserved, including cancellation between two steps.

Each attempt stages its own results. The runner commits only that component's
result, override changes and coverage when it completes. A late callback cannot
overwrite another run or another component. The panel regains focus and controls
after completion/cancellation. The final summary counts outcomes among attempted
checks, reports how many were not started, and explains that results remain local
until a successful assignment saves the report.

Interactive attempts have a five-minute overall limit. Expiry records Error,
cleans up the active check and stops the sequence. Runner cancellation/error
preserves available partial coverage and records the runner exit; it never implies
a measured hardware pass. Existing assignment review/reason policy still applies.

## Native work and resource ownership

`services/hardware_job.py` launches the same executable with an early
`--hardware-worker` dispatch (or `src/main.py` from source). Dispatch occurs before
the desktop controller is imported. Workers use private temporary request/result
files, so windowed frozen executables do not depend on stdout. No worker operates
Tk widgets. Hardware errors and worker startup/exit failures return an explicit
error to the UI.

| Operation | Bound / ownership |
| --- | --- |
| Camera | Discovery/read/encoding occur in a child process. Discovery has a 25-second limit; a preview heartbeat older than five seconds disables Pass and stops the worker. Pass rechecks freshness. The image fits within 640×420; the operator confirms the live image. |
| Audio | Device enumeration and owned stream operations occur in children, each with a 15-second parent limit. SC09's explicit device selection, conservative amplitude and independent listening decisions remain. Recording/playback are finite and captured data returns through a temporary NumPy file without pickle. |
| USB | Each removable-volume enumeration has a 10-second limit in a child. The UI schedules another observation after completion and remains cancellable. SC10's port checklist and fresh-insertion requirements remain. |
| WLAN | Enumeration runs in a child with a 15-second limit. The SC10 adapter-only coverage and distinct Unavailable/Error states remain. |
| Activation | The activation command has a 15-second subprocess timeout and a 25-second parent job limit including verification. Cancelling stops waiting and terminates the owned process tree; it cannot undo licensing work already accepted by Windows. |
| Product key | Retrieval runs in a child with a 15-second parent limit and a 10-second command timeout. Closing the panel discards late completion. No key is logged. |
| Live battery footer | WMI reads occur in a child with a 10-second limit. Only one read is in flight, refresh is throttled to once per ten seconds, and failed reads show unreadable instead of retaining a stale charge claim. |

On Windows, each job uses an unnamed Job Object with kill-on-close, covering its
worker and descendants. Cancellation requests termination immediately; bounded
reaping and temporary-directory removal run away from Tk. Cleanup verifies the
absolute directory is a task-owned child of the system temporary directory before
removing it. Camera probes release unsuccessful captures and normal worker exits
release active streams/captures; process termination releases native handles when
a driver call stalls. Temporary frame/audio files are removed during normal job
cleanup and are never included in a saved check report. Crash/power-loss cleanup
and release-artifact verification remain acceptance work.

Keyboard hooks put logical events into a bounded queue. Tk drains that queue and
updates the displayed coverage. Closing/finishing capture stops polling, cancels
owned timers and unhooks both hooks, including a partial installation failure.
Late key events cannot access destroyed widgets. Display and result prompts update
the runner's registered cancellation callback as the active dialog changes.

## Notes

Order-note saves now run in a background thread, with a queue polled on Tk. Save
disables duplicate submission; a failed/unconfirmed save retains the editor text
and offers retry after checking saved state. A result updates the footer only if
the same resolved order and search generation are still current.

Closing the editor stops UI polling and discards late UI updates. The editor
explicitly states that closing does not cancel a database write already submitted.
The database connection uses one attempt, existing five-second connect/read/write
timeouts and no background message boxes. A connection failure after commit can
still have an uncertain outcome: check the saved note before retrying. This does
not introduce versioned/concurrent-edit note conflict detection.

## Verification and remaining acceptance

114 desktop tests passed with the Python 3.12 packaging runtime. Six new lifecycle
tests include a real source worker dispatch, a deliberately stalled process,
Windows descendant termination, camera resource cleanup, frozen-command/file-IPC
construction and real hidden Tk lifecycle checks. Existing audio and coverage
tests were adapted to mock the worker boundary; they still test listening gates,
independent results, port coverage, key capture, absence/error distinctions and
saved coverage. No physical camera, microphone, speaker, USB or WLAN quality is
asserted by these tests.

Before release, build the exact artifact and test all helper modes from that
windowed executable in the VM. Repeat Run All and individual checks, cancel during
each phase, close/reopen the panel, force worker startup failure/timeouts, unplug
physical devices and check no owned process survives. Confirm staged cancellation
and coverage survive draft restoration and report readback against the isolated
matching server. Verify real audio levels, camera preview, USB ports, locale,
activation semantics and high-DPI layout on physical hardware. Keep SC10's
[physical matrix](sc10-hardware-coverage.md); SC12 addresses remaining layout work.

Windows process-tree ownership follows Microsoft's [Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
