# VR01 / SC12 — sign-in scaling

Implemented locally and verified in the native packaged Windows VM on
26 October 2026.

The sign-in card now uses its natural content height rather than a fixed
528×428 pixel rectangle with propagation disabled. Its width follows the Tk
font scale and available viewport. The initial window is sized after the mapped
theme has settled its geometry, bounded by the desktop work area. Longer service
messages and help text wrap; Retry/Exit share a width-constrained action row.

The form has a vertical scroll surface for constrained desktops or manually
shrunk windows. Wheel/page navigation and keyboard focus use the existing scoped
scrolling helper. The password field and every action can be brought into view;
scroll/focus bindings are removed when sign-in finishes. Authentication behavior,
credentials, service contracts and database schema are unchanged.

## Validation

All 255 desktop tests passed and all tracked Python files compiled. Real Tk
tests use the actual ttkbootstrap theme and an inherited main-window geometry
at 100%, 125%, 150%, 200% and 250% font scaling. They check default geometry,
horizontal bounds, a manually shrunk 480×360 viewport, long connection errors,
focus scrolling to password/Log In/Exit, busy state, binding cleanup, and reset
form controls without entering or changing a password.

The complete unsigned review candidate is build
`75250097-d06e-41ea-a781-d93b1ebef44f`, SHA256
`75e07b621a937ee66119239649d45db09fb8b451707b90454b2cc7e5c7ec2a5f`.
It is stored with review scripts in
`C:\Users\PCR\Documents\SecondChecking Review\vr-signin-scaling-final-2026-10-26`.

An earlier candidate's 1080p native screenshots exposed an unnecessarily tall
initial window after theme initialization; that was corrected and added to the
regression test before the final build. The earlier screenshots and failed 4K
mode request are retained in the adjacent `vr-signin-scaling-2026-10-26` folder
for provenance, not final acceptance. Do not count a requested resolution as a
pass without verifying actual guest screen dimensions and window DPI.

## Native VM acceptance

The complete final executable was freshly launched for each case. Native screen
dimensions and GetDpiForWindow matched each requested combination:

| Guest resolution | Windows scaling / measured DPI | Result |
| --- | --- | --- |
| 1920×1080 | 100% / 96 | Password, Log In, Retry, Exit and help visible |
| 1920×1080 | 125% / 120 | All controls visible |
| 1920×1080 | 150% / 144 | All controls visible |
| 1920×1080 | 175% / 168 | All controls visible |
| 3840×2160 | 200% / 192 | All controls visible |
| 3840×2160 | 250% / 240 | All controls visible |
| 1800×1200 | 200% / 192 | All controls visible |

The Surface-style 1800×1200 case also displayed the complete synthetic long
username, connection-error state after stopping only the isolated review API,
successful Retry after service restoration, and the reset-password form followed
by Cancel. The synthetic tester reset flag was restored; no password was changed.
These extra states were sampled at 200%, not claimed across the entire matrix.
After restoring 1080p/100%, ordinary tester/test sign-in succeeded in the final
candidate, fresh device measurements loaded and both batteries remained 90.9%.
`verification.json` records seven native cases, 13 screenshot hashes, the exact
artifact hash and matching source fingerprints.

PNGs and native window metadata are in the final candidate's `screens` folder.
Host mouse, keyboard and focus were not used for guest automation. The owner
dismissed a host VirtualBox notice when required. A VirtualBox saved-state resume
failed with VINF_EM_TRIPLE_FAULT; the same VM was cold-booted and its isolated
services restarted before final native acceptance. This was a VM infrastructure
failure, not an application crash. The viewer was left in normal window mode;
temporary global MaxGuestResolution was unset again and guest display restored
to 1920×1080/100%. Avoid depending on this 3D VM's saved-state resume for acceptance.

VR05 hardware/serial-viewer footers and VR03 live DPI transitions remain separate
follow-ups. No OVA was rebuilt and no additional VM was cloned for these checks.
