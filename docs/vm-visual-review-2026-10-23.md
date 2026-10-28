# Latest packaged application visual review — 23 October 2026

**Outcome: changes required before release.** Six follow-ups are added to the
[improvement plan](app-improvement-plan.md#native-vm-visual-follow-ups--23-october-2026).
The subsequent [worker lifecycle correction](vr-worker-lifecycle-fix.md) addresses
VR06 and VR04 locally, with full frozen-candidate VM regression. The subsequent
[dual-battery correction](vr-dual-battery-fix.md) addresses VR02 with packaged GUI
capture and isolated saved-report readback. The
[26 October sign-in correction](vr-signin-scaling-fix.md) addresses VR01 in the
native packaged matrix. The [26 October action-footer correction](vr-action-footer-fix.md)
addresses VR05. The [worker file-access correction](vr-worker-file-access-fix.md)
addresses VR08 locally with Windows lock tests and packaged USB regression.
The [26 October live scaling correction](vr-live-dpi-fix.md) addresses VR03
locally with a native packaged transition matrix; physical mixed-monitor
acceptance remains outstanding.
VR07's intermittent startup freshness rejection was subsequently addressed by the
[26 October correction](vr-startup-freshness-fix.md). Findings below
retain their original review evidence.

| Priority | Finding | Plan item |
| --- | --- | --- |
| P1 | VR06: terminated frozen workers leave extraction files until the disk fills | SC11 / SC17 |
| P2 | VR04: frozen-worker startup exceeds the GUI's operation deadlines | SC11 / SC17 |
| P2 | VR01: fixed-size sign-in card clips actions at larger native DPI | SC12 |
| P2 | VR05: webcam/USB/serial-viewer action footers disappear | SC12 |
| P2 | VR02: default battery export cannot measure both installed packs | SC08 |
| P3 | VR03: live DPI changes differ from fresh-launch sizing | SC12 |

## Scope and evidence

This review uses the full windowed SC21 review executable in the visible
`SecondChecking-Test` Windows 11 VM. Guest-only automation leaves the host mouse,
keyboard and foreground applications alone. Screenshots contain synthetic data.
The executable is version 0.1.36, build UUID
`e41677af-579d-411c-af54-1b33c03b6910`, SHA-256
`e6d470538c383a89c77f76e7489e43b243a405a1570dec7fa6371a9368a5f1a0`.
Its 55 runtime source inputs matched the checkout at capture time. It is an unsigned review
artifact, not a published release.

The app signs in through the current Web-Tools auth/stock blueprints against a
new synthetic MariaDB schema, `sc22_visual_20261023`, inside the VM. The desktop
database account is SELECT-only; the service account is restricted to that schema.
The service listens on loopback port 5002 and external networking is disconnected.
This checks the actual route contract, rather than the earlier generic simulator.
Fresh `db.create_all` schema setup does not establish migration acceptance. The
loopback HTTP exception and disabled fixture rate limiting do not establish TLS
or login-throttling acceptance.

Full-resolution PNGs and per-window native DPI metadata are outside Git at
`C:\Users\PCR\Documents\SecondChecking Review\sc22-visual\screens`.
Screenshot filename scales describe the **requested** scale; metadata records
what Windows actually applied. In particular, requesting 200% at 1080p produced
168 DPI / 175%, so it must not be counted as a 200% pass.

VirtualBox's display-only graphics path initially rejected higher resolutions.
Enabling guest 3D acceleration and cold booting enabled genuine native display
mode changes. Host display resolution/scaling was not changed. Native Windows
screen dimensions and `GetDpiForWindow` are used to validate the matrix, rather
than resizing the VM viewer or substituting simulated Tk scaling.

## Confirmed follow-ups

Native fresh-launch sign-in matrix (all rows have captured PNG evidence):

| Native guest resolution | Actual scales / window DPI | Sign-in result |
| --- | --- | --- |
| 1920×1080 | 100% / 96 | All controls visible; real-route sign-in works. |
| 1920×1080 | 125% / 120 | Log In visible; Retry/Exit clipped. |
| 1920×1080 | 150% / 144 | Log In and secondary actions clipped; Enter signs in. |
| 1920×1080 | 175% / 168 | Actions clipped; requested 200% was capped by Windows. |
| 3840×2160 | 150% / 144 | Actions clipped. |
| 3840×2160 | 200% / 192 | Password field mostly clipped; actions absent. |
| 3840×2160 | 250% / 240 | Password field and actions absent. |
| 1800×1200 | 100% / 96 | All controls visible. |
| 1800×1200 | 150% / 144 | Actions clipped. |
| 1800×1200 | 200% / 192 | Password field mostly clipped; actions absent. |
| 1920×1280 | 150% / 144 | Actions clipped; Enter signs in. |

The 1800×1200 and 1920×1280 rows cover two Surface-style 3:2 modes; they do not
identify a particular physical Surface panel. Workflow coverage below is a
representative pass, not every dialog at every scale.

### VR01 / SC12 — P2: sign-in actions disappear at larger DPI

Fresh launch at 1920×1080 / 150% (144 DPI) displays Username and Password but clips
Log In, Retry, Exit and the service-help footer. At 125%, Log In remains visible
while the secondary controls disappear. At actual 175%, the password field is
also close to the card's lower edge. The same missing actions reproduce at
3840×2160 / 150%, despite the much larger available desktop.

Evidence: `login-1080p-150-fresh.png`, `login-1920x1080-125.png`,
`login-1920x1080-200.png` (actual 175%) and `login-3840x2160-150.png`.
At 150%, entering the password and pressing Enter successfully signs in against
the real service; this is a clipped UI, not an authentication failure.

`src/auth/login.py` fixes the card at at most 528×428 pixels and disables geometry
propagation, while fonts and themed controls increase with Windows DPI. Increasing
the outer window does not resize the placed card. Size the card from its content
and available work area, keep actions reachable, and add scrolling for constrained
desktops. Include password-reset/error/retry states and long usernames in the
native-DPI regression matrix.

### VR02 / SC08 — P2: default helper export cannot measure both batteries

Windows exposes both persistent simulated batteries with healthy device status,
90% current charge and paired design/full capacities of 110/100 mWh. The latest
app displays **Unreadable** health for both packs. BatteryInfoView's default
`/scomma` invocation exports only one selected battery. The collector correctly
refuses to pair that single result with a two-battery inventory, recording
`Battery count differs between inventory and export`.

Evidence: `order-test-1080p-100.png`, `main-ready-1080p-100.png`, the separate
BatterySimulator device/export evidence, and `src/utils/specs.py` collector paths.
The conservative result avoids a false pass but leaves multi-battery acceptance
unmet. Enumerate every pack using a supported source/selection method; preserve
distinct device identities even when names/serials match, and save/read back each
capacity pair. Retain Unreadable when identity or count cannot be established.
Retest distinct simulated capacities and one unreadable pack, then physical
dual-battery hardware.

### VR03 / SC12 — P3: inconsistent live DPI resizing

Changing the running 1080p app from 100% to 150% scales its Windows frame and
expands the window, but much of its existing content retains its smaller text.
A fresh launch at the same 144 DPI renders larger text correctly. Evidence:
`main-1080p-150.png` versus `main-1080p-150-fresh.png`. Test monitor transitions
and recalculate Tk fonts/layout consistently when DPI changes. A VM's single
virtual monitor does not establish physical multi-monitor acceptance.

## Baseline observations

### VR04 / SC11, SC17 — P2: packaged worker startup exceeds operation limits

Speaker and microphone device enumeration both display `Hardware operation timed
out`; automatic WLAN also errors and the primary live-charge read is Unreadable.
The app remains responsive and cancellation/result controls are reachable.
Standalone invocations of the **same frozen executable** complete in 37.90 s
(WLAN), 39.14 s (audio device enumeration), and 39.65 s (live battery). Audio
returns an empty device list, live battery returns measured 90%, and WLAN reports
the actual stopped WLAN service (WinError 1062). Those are useful results which
the app's 15 s audio/WLAN and 10 s battery deadlines expire before receiving.

Evidence: `speaker-1920x1280-150.png`, `microphone-1920x1280-150.png`, external
`worker-timing.json` and its reproducible `worker_timing.py`. The standalone probe
does not use the app's suspended/job-owned launch, so the precise contribution of
unpacking/imports versus job startup remains to be profiled. The end-to-end
deadline currently starts before process creation in `HardwareJob.__init__`.
Add bounded startup/readiness acknowledgement separately from the operation
deadline, reduce repeated frozen startup costs, and retain cancellation/process
ownership. Verify these paths in the full windowed artifact on slow/cold systems;
source-only worker tests do not establish this acceptance. Do not merely turn
timeouts into hardware Fail or extend all native operation limits without bounds.

### VR05 / SC12 — P2: secondary dialogs clip their action footers

At 1920×1280 / 150%, Webcam Test and USB port checklist initially allocate their
content, then longer timeout/error text consumes another wrapped line. The last
Cancel button collapses to a thin unlabelled strip at the bottom of each window.
Window-close still cancels and other error/unavailable actions remain visible.
Evidence: `webcam-1920x1280-150.png` and `usb-1920x1280-150.png`.

At 3840×2160 / 200%, the default Assigned Serial Numbers window also clips its
Remove, View Report and Reload list row entirely, and truncates the serial/SKU
columns. Maximizing reveals the complete identifier and all actions. Evidence:
`serials-saved-4k-200.png` and `serials-saved-4k-200-maximized.png`. Preserve the
action row before allocating the table's requested height; size columns to font
metrics and provide access to complete identifiers at the default window size.

Both dialogs calculate content geometry once, before asynchronous status updates.
Reserve the action footer outside a bounded scrollable body, wrap status text to
the available width, and re-evaluate layout when error/preview content changes.
Include no-device, lengthy native errors and successful preview states in the
125–250% native DPI checks. This is separate from the worker timeout defect.

### VR06 / SC11, SC17 — P1: terminated frozen workers exhaust the guest disk

During this review the guest's 84,398,829,568-byte C: volume reached **zero free
bytes**. There were 263 `_MEI*` extraction directories created on the review day,
totalling 44,693,417,503 logical bytes. Of those, 242 contained this exact review
build UUID. Repeated timeout/termination of the one-file executable leaves its
unpacked runtime behind; recurring live-battery refresh amplifies the growth.
The contribution of each trigger is not individually counted, but build identity
and rapid accumulation establish a packaging/lifecycle problem.

The UI displayed a PyInstaller fatal extraction error, `Failed to extract
MySQLdb\\_mysql.cp312-win_amd64.pyd: decompression resulted in return code -1`,
over the assignment Success dialog. The inspection helper also failed writing a
small JSON file with `No space left on device`. Evidence:
`assignment-disk-full.png` and the recorded volume/directory measurements.
Assignment success was visible, but does not alone prove saved report readback;
verify service state after recovery before retrying writes.

Require repeated frozen-worker timeout/cancel and idle-soak acceptance proving
bounded disk use before release. Reuse a verified runtime or otherwise allow
owned bootloader cleanup, with safe stale-extraction recovery and low-disk
handling. Preserve descendant process ownership. Do not clean arbitrary user temp
directories. Recovery stopped only the known review process tree and targeted
inactive same-day extractions whose embedded UUID exactly matched this build;
unrelated/unidentified temp directories were preserved.

Recovery restored 44,684,595,200 free bytes. The first bounded cleanup stopped
part-way through; the second removed the remaining 109 matching directories.
A subsequent read-only database check confirmed the exact VM serial assigned to
`test` by `tester`, with a report retaining the recorded reason
`SC22 synthetic VM visual review only; physical hardware not verified.` and
separate unavailable/cancelled/error/activation-fail results. Public evidence:
`saved-state-public.json`. No duplicate submission was made during recovery.
Further review launches use a dedicated guest `C:\SC22Visual\RunTemp` directory
so generated extraction files can be safely scoped and removed after testing;
this is test-fixture containment, not an application fix.

## Workflow observations

At native 1920×1080 / 100%, sign-in and synthetic `test` order lookup work against
the matching real-route service. The main comparison, separate action row,
scrollable details/notes and visible order/device context fit the desktop.
Hardware Tests opens with progress and persistent cancellation; opening Keyboard
shows a scrollable diagram with Finish and Cancel outside it. Cancel returns to
the hardware panel. A fresh 150% main screen has readable larger fonts and a
scrollable comparison/footer instead of overlapping content.

At 4K / 200%, the main window was reviewed at its default size and maximized;
the maximized comparison shows all specification rows and preserves the action
row. The main and footer scroll independently. The notes area can be reached by
dragging the footer scrollbar; wheel input over the note text scrolls that text.

| Workflow | Observed result / evidence |
| --- | --- |
| Sign-in / order lookup | Real `tester` sign-in at 1080p/100% and 150%, Surface-style 1920×1280/150% and 4K/200%; `test` lookup visually verified at 1080p/100%, 1920×1280/150% and 4K/200%. Enter/Tab used where sign-in buttons were clipped. |
| Hardware panel | Scrollable cards and persistent Run All/Cancel footer at 100% and 150%; `hardware-1920x1280-150.png`. |
| Speaker / microphone | Separate controls, selected-device fields and error/unavailable/cancel choices; enumeration timed out before useful worker results (VR04). No physical audio pass claimed. |
| Display | Full-screen instructions, advance through five colours, readable result prompt and cancellation; `display-1920x1280-150.png`, `display-result-1920x1280-150.png`. No physical panel pass claimed. |
| Keyboard | Diagram/scrollbars, Show Numpad option, persistent Finish/Cancel, long missing-key result and incomplete-pass validation; then recorded Unavailable. `keyboard-result-1920x1280-150.png`, `keyboard-incomplete-validation-1920x1280-150.png`. Physical key capture not established. |
| Webcam / USB | Timeout/error dialogs, explicit outcome controls and close/cancel path; footer defect VR05. No camera preview or inserted-media pass claimed. |
| Serial viewer empty | Clear empty message, disabled View/Remove and enabled Reload at 150%; `serials-empty-1920x1280-150.png`. |
| Assignment | Review separates failed/cancelled/unavailable/error results and requires a reason. Synthetic assignment committed through the real service; read-only database verification retained operator/reason/results after disk recovery. `assignment-review-1920x1280-150.png`, `saved-state-public.json`. |
| Saved report | Real authenticated readback loaded at 4K/200%, exact serial/operator/report ID/current assignment and historical committed receipt displayed separately; scroll and Close work. `saved-report-4k-200.png`, `saved-report-details-4k-200.png`. Viewer first required maximizing because of VR05. |
| Notes | Editor, Save/Close and status fit at 4K/200%. Appending `SC22 visual note save check at 4K 200 percent.` saved through the real service, updated the footer, and was independently read back from the synthetic DB. `notes-editor-4k-200.png`, `tools-menu-4k-200.png`, `saved-state-public.json`. |
| Maintenance / session | Windows Update confirmation fits and No cancels before elevation. Operator menu locks the app, removes the order/actions and preserves drafts; `maintenance-confirmation-4k-200.png`, `operator-menu-4k-200.png`, `locked-4k-200.png`. |

Synthetic specification mismatches (model, CPU, decimal disk capacity and
Enterprise Evaluation edition) are expected fixture outcomes. A VM without WLAN,
camera, audio or removable devices cannot establish physical hardware failures
or known-good passes. MDM explicitly remains unverified.

## Remaining acceptance and handoff

This is a representative visual/workflow review, not every state of every dialog
at every matrix entry. Fresh-install configuration, password reset/retry failures,
long SKU/username stress, conflicting assignments, lost-response retry, unassign,
stale/no-match order transitions, and a complete Run All cancellation/late-callback
regression still require dedicated acceptance. The exploratory Run All capture
does not prove successful cancellation and is not counted as a pass.

Real TLS, signed update/rollback, hosted release workflow, UAC maintenance execution,
Sysprep, tenant enrolment, physical hardware and multi-monitor transitions remain
open. No UAC prompt was approved by automation, and no maintenance/update or
Sysprep operation was executed. Screenshots of simulated devices do not replace
known-good/faulty physical bench checks.

The external `evidence-manifest.json` indexes 64 full-resolution captures with
dimensions and SHA-256 hashes, including nine machine-readable fresh-launch
matrix entries. The additional 1080p/100% and 150% screenshots/native metadata
complete the eleven observed sign-in combinations above. Preliminary/transient
captures are retained for provenance, not counted as additional passing checks.
`worker-timing.json` and `saved-state-public.json` contain public measurement and
synthetic saved-state evidence. Guest private fixture/config files are excluded.

Application source was not changed or committed during this review. The OVA was
not rewritten. The review app is closed after the checks to prevent further
extraction growth; its dedicated `RunTemp` is cleaned only after no review process
remains. The visible VM stays available, with review networking isolated and 3D
acceleration retained for working native resolution changes. Host input/display
settings were not changed.
