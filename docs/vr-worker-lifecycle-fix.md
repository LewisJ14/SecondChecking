# VR06 / VR04 — frozen worker lifecycle correction

The review candidate re-extracted its full one-file runtime for every worker.
Its operation deadline included that 38–40 second cold start, and terminating
the bootloader left extraction files behind. Recurring live-battery reads filled
the test VM disk. These two findings are now implemented locally and verified
in a rebuilt windowed candidate. No server or database change is needed.

## Change

Owned short-lived workers reuse the application's existing unpacked runtime.
For the pinned PyInstaller 6.3 bootloader, the child environment restores
`_MEIPASS2` from `sys._MEIPASS`, following the mechanism in PyInstaller's own
[6.3 multiprocessing hook](https://github.com/pyinstaller/pyinstaller/blob/v6.3.0/PyInstaller/hooks/rthooks/pyi_rth_multiprocessing.py).
The parent's environment is never modified. Worker launches remove the independent
restart flag; newer bootloader metadata is retained. A future packager upgrade
must rerun the frozen acceptance, not assume compatibility from source tests.

Hardware/app helpers acknowledge startup through atomic file IPC. Startup has a
30-second limit, then the existing per-operation time limit starts. Errors
distinguish startup from native-operation timeout. Completed jobs can exit
normally for up to two seconds on a background reaper before forced termination;
cancelled jobs terminate immediately. Windows job ownership still includes
descendants and cleanup retries bounded file-lock races off the Tk thread.

Independent executable probes deliberately unpack in a private `runtime` child
of their job directory. Timeout cleanup removes only that owned tree after the
process group is terminated. It never scans/deletes arbitrary `_MEI` folders.
Operator sign-in restart explicitly uses a fresh environment so it can survive
the old process's runtime cleanup, as required by
[PyInstaller's restart contract](https://pyinstaller.org/en/latest/common-issues-and-pitfalls.html#using-sys-executable-to-spawn-subprocesses-that-outlive-the-application-process-implementing-application-restart).

## Verification

- All **248 desktop tests** passed; all **86 tracked Python files** compiled.
  New regressions cover delayed startup, bounded operation after readiness,
  thread-safe environment isolation and forced cleanup of an independent probe's
  unpack files while preserving an unrelated sentinel.
- Full windowed PyInstaller 6.3 / Python 3.12 review candidate rebuilt through
  the normal identity-aware builder: build UUID
  `81ca37c8-aa5c-4cf8-8a9c-6d99c0b2ba49`, SHA-256
  `10c3a32d565d532d34eab6bfbf8b6f29a7af8d033135652e37706e877ef35103`,
  74,858,567 bytes. It is an unsigned dirty-source review artifact, not a release.
- In the isolated VM, the production launcher module exercised that full frozen
  executable: **25 hardware worker runs**, **5 local-MDM helper runs**,
  **20 immediate cancellations** and **3 independent startup timeouts**.
  Every owned job directory disappeared after cleanup. Shared extraction count
  stayed **1 → 1**. Total probe duration: 32.39 seconds.
- Worker results arrived in **0.374–2.031 seconds**. All five live-battery reads
  measured 90%. Audio enumeration completed with no endpoints; WLAN returned
  the real stopped-service error instead of an artificial worker timeout.
- Actual GUI sign-in at 1080p/100% succeeded. Speaker now says the required
  audio device is unavailable. The live-charge footer shows **90% / AC power
  (charging unconfirmed)**. Wi-Fi logging reports WinError 1062. Closing the
  first speaker dialog during Run All stops the sequence with **1 cancelled,
  6 not started**, leaves the next check Not Run and restores the panel controls.
- After approximately seven minutes of GUI use/recurring refresh, one parent
  extraction remained and the guest retained 44,578,013,184 free bytes. This is
  a short regression soak, not a complete long-duration or physical-device soak.
- Normal GUI exit then left **zero candidate processes and zero extraction
  folders**, with 44,766,957,568 free bytes. This required no manual deletion.

The external launcher probe uses the production `hardware_job.py` in the guest
Python 3.13 harness (psutil 7.1.3), and the exact frozen executable for worker code.
The actual GUI separately exercises the bundled Python 3.12 / psutil 5.9.8 launcher.
Both paths matter; the harness alone is not a replacement for GUI acceptance.

Evidence: `C:\Users\PCR\Documents\SecondChecking Review\vr-worker-fix`, including
`build-record.json`, `vm-worker-probe.json`, `verification.json`, the reproducible
probe and executable. The verification checks current source fingerprints against
the build record and hashes the candidate and six GUI screenshots.
GUI screenshots are the `worker-fix-*.png` files in the existing
`sc22-visual\screens` evidence directory. Existing service fixture credentials
remain inside the guest and are excluded from these reports.

## Remaining work

VR01/VR05 dialog layout, VR02 dual-battery health and VR03 live DPI changes are
still open; the live-charge fix does not fix dual-battery health collection.
Repeat signed release, independent update/restart/rollback and longer idle/
cancel/exit soak acceptance before rollout. Existing orphaned files from an older
build require identified, inactive-file recovery; this change does not delete
unknown user temp folders. The original application/OVA are preserved, and no
commit, publication or production deployment was made.
