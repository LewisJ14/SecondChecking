# VR03 / SC12 live scaling correction — 26 October 2026

The app now observes native Windows DPI and work-area changes on the Tk thread.
It refreshes existing named fonts and replaces cached anonymous widget fonts with
retained named fonts. New dialogs inherit a named default font; the UI timer also
normalizes newly created controls with explicit fonts, including saved-report
Text widgets. Tree columns and row height follow the new metrics; the login
card refits without clearing the username or password.

This keeps the existing widgets, operator session, loaded order, selected serial,
test state and unsaved input. It does not restart the application or rebuild the
controller. The polling callback is removed when the root is destroyed.

Window fitting uses the window's monitor work area and accounts for the native
frame/title bar. A smaller work area triggers fitting even when DPI is unchanged.
Normal open windows are bounded; Windows retains control of maximized windows.

## Validation

Real Tk regression tests compare existing label/button metrics with newly created
controls through 100→150→200→250→125→100% transitions. They preserve unsaved text,
the selected row and exact serial, check column widths and timer teardown, and
verify that an unchanged-DPI work-area reduction bounds the root and open dialog.

All **265 desktop tests passed** and all tracked Python files plus the new test
module compiled. The suite emitted a Tcl theme-event diagnostic after a test
interpreter was destroyed; it reported no test failures.

The full unsigned review build has UUID
`44dcef8f-a4d7-4c0b-8f76-c5c24489acdf`, SHA-256
`98f0f35a4552814c021b81075eea929abfa9e163674cf303a9240ef9951b2f7b`.
Its frozen runtime is Python 3.12. Native VM evidence is in
`C:\Users\PCR\Documents\SecondChecking Review\vr-live-dpi-complete-2026-10-26`;
the guest executable is `C:\SC22Visual\live-dpi-fix.exe`.

The same GUI process (PID 4484) and existing windows were retained throughout:

| Native desktop / scaling | Observed behavior |
| --- | --- |
| 1920×1080, 100→150% | Sign-in text/actions resize; entered password remains masked and signs in successfully. |
| 1920×1080, return to 100% | Sign-in succeeds after the round trip; synthetic order `test` loads normally. |
| 3840×2160, 100→200→250→200% | Existing serial table, selected row, exact serial/SKU and footer actions remain usable. |
| 1800×1200, unchanged 200% | Smaller work area refits open windows; full selected details and all footer actions remain visible. View Report opens the correct dialog; its text now scales correctly, including the long service error. |
| Return to 1920×1080, 100% | Recorded separately in the screenshot/metadata index. |

The native matrix measures actual guest pixel dimensions and window DPI, not
simulated Tk scaling. It samples sign-in, main, serial list and report screens;
it does not cover every application state at every scale. No assignment,
unassignment or server report/note write was performed. No VM clone or OVA was
created, and host mouse/keyboard control was not used.

Preliminary evidence is retained separately under
`C:\Users\PCR\Documents\SecondChecking Review\vr-live-dpi-2026-10-26` and
`C:\Users\PCR\Documents\SecondChecking Review\vr-live-dpi-final-2026-10-26`.
The latter exposed the same-DPI work-area case subsequently corrected. Its
`serial-surface-attempt-still-4k-200` capture is a rejected display-mode attempt,
not Surface-resolution evidence.

The intermediate `vr-live-dpi-accepted-2026-10-26` build verified window fitting
but exposed a stale explicit font when opening a saved report after scaling.
The final candidate above also normalizes new controls on the UI timer and
rechecks that report. Earlier candidate evidence does not establish final-build
acceptance. An experimental Map-binding approach failed targeted tests, was
removed, and its in-progress build was interrupted.

Tk 8.6 has one scaling value per interpreter: this implementation follows the
focused application window. The VM's single virtual display cannot establish
simultaneous mixed-DPI monitor behavior. Physical monitor transitions remain in
release acceptance, along with the other SC22 hardware and deployment checks.

The final report request returned HTTP 401 after the long-running lab session
had aged. Its screenshot proves readable error text and reachable Retry/Close,
not successful authenticated report readback. The earlier intermediate candidate
did load report 2, before this final new-control font correction. Repeat report
readback with a fresh session and verify session-expiry UX in SC22 workflow
acceptance; no authentication bypass was introduced. After the transition matrix,
the guest was restored to 1080p/100% and the app reopened at a fresh sign-in screen.

Subsequent checkpoint: [SC22 report/session acceptance](sc22-report-session-acceptance.md)
uses a newer package for fresh authenticated report readback and deliberate lab
session expiry. It replaces generic Retry guidance with explicit sign-in recovery.
