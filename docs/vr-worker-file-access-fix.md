# VR08 / SC11 worker file-access recovery — 26 October 2026

Transient Windows read locks on worker acknowledgement/result files now retry
across GUI polls for a fixed one-second budget. Persistent denial still produces
an explicit error. Startup and operation deadlines take precedence; no sleep is
introduced on the Tk polling path. Invalid JSON and mismatched acknowledgements
remain errors. A final result published between the first read and observing
process exit is read again before declaring the result missing.

Application helpers use the same read path, retaining their 2 MiB result limit
inside the bounded binary read and their existing identity/version validation.
Process ownership, cancellation and runtime extraction behavior are preserved.

## Evidence

A real Windows `CreateFile` handle without sharing reproduced the original
`PermissionError` reading `ready.json` before the change. The new tests prove
recovery after unlocking acknowledgement/result files, including an exited
worker's final result. They also cover persistent denial, deadlines, malformed
messages, the publication/exit race and oversized helper results. The identity
of the lock holder in the original VM observation remains unknown.

- All 262 desktop tests passed; tracked Python files compiled successfully.
- All 10 worker runtime tests also passed inside the Windows VM. That source
  harness used Python 3.13/psutil 7.1.3; the full frozen application below uses
  Python 3.12/psutil 5.9.8.
- The full application's USB checklist repeatedly polled at 1920×1080/100%.
  Selecting Record enumeration error displayed “No enumeration error has been
  observed.” The unattended session later reached the existing five-minute
  interactive limit and ended as ERROR; this was not a file-access failure.
- A fresh USB run was explicitly cancelled: the panel showed CANCELLED,
  Run All Tests became available and the dialog closed. The hardware panel was
  then closed, leaving the application running. Its live battery poll can still
  own a short-lived worker; one parent runtime extraction is expected.

Screenshots, source-test bundle and build records are under
`C:\Users\PCR\Documents\SecondChecking Review\vr-worker-file-access-2026-10-26`.
`screens/usb-no-enumeration-error.png` records the live status;
`screens/usb-cancelled-retest.png` records successful cancellation.
`screens/usb-cancelled.png` is the earlier five-minute expiry, despite its filename.

The unsigned full review candidate has build UUID
`a8da3d4d-e5dd-4694-857c-9b4b8e5467da`, SHA-256
`9c4e3c49363708f176116708630c1ea907bca481575b3f97112bbdb82bc9728e`.
The guest copy is `C:\SC22Visual\file-access-fix.exe`.

VR08 is implemented locally with representative packaged VM regression. This
does not establish physical USB function or release acceptance. No stock/report
writes or Windows security changes were made. The retained OVA is unchanged.
Next is VR03: live DPI transitions.
