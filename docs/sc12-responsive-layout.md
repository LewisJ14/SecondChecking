# SC12 — layout, focus and scrolling

Original implementation: 22 October 2026. The packaged VM review on 23 October
identified additional native-DPI issues. The [VR01 sign-in correction](vr-signin-scaling-fix.md)
was implemented on 26 October. The [VR05 action-footer correction](vr-action-footer-fix.md)
also passed packaged/native layout checks. The [VR03 live scaling correction](vr-live-dpi-fix.md)
now refreshes existing fonts and bounds windows after work-area changes, with
native packaged VM transitions verified. Physical mixed-monitor checks remain open.
No migration or server contract change is required.

## Changes

The comparison uses real layout-managed widgets instead of fixed canvas text and
button coordinates. Device/order identity, actions, SKU title and the comparison
table occupy separate rows. Long titles and values wrap to the available width;
table rows grow with their contents. Resizing changes widget layout without
rerunning hardware capture, replacing the selected order or clearing check drafts.
Identity/actions precede the long title so a long SKU cannot push them underneath
or overlap them. They remain in the scrollable surface; the resolved context stays
in the main header and keyboard focus scrolls an action back into view.

The footer has a bounded scroll area plus an always-accessible Show/Hide control.
Summary, qualified MDM text, hash status, battery information and order notes remain
available inside it, rather than consuming the comparison's remaining height.
The compact footer overview retains **MDM NOT VERIFIED**. Notes no longer reserve
a fixed 44-character right column. Header context and measurement labels wrap as
the window changes width, and version text has its own row.

Hardware cards place descriptions below their actions/status, with wrapping based
on the actual card width. The Run All/Cancel footer is allocated before the growing
list, so its controls stay visible at large font scaling. The list retains a
scrollbar and supports wheel scrolling over its labels and buttons.

The keyboard diagram uses a two-direction scroll surface. Key widths are measured
using their actual font rather than assuming each label fits six average
characters. Long labels remain readable; the diagram can be panned rather than
shrinking text. Finish/Cancel and coverage counts stay outside the diagram's
scroll area. Full missing-key details and the manual explanation entry are in a
scrollable result panel with separate result controls. The duplicate bottom-row
Print Screen label is removed; its function-row key remains.

The shared scrolling helper routes wheel events only within its own surface,
including wheel events over child labels/buttons. Shift+wheel pans a horizontal
surface. Native Text/Listbox/Treeview/Combobox scrolling remains independent.
Page Up/Down and Home/End work when a canvas has focus. Focus entering an off-screen
child scrolls it into view using content coordinates, without depending on stale
screen positions. Destroying a surface removes its toplevel bindings. Keyboard
capture's scoped Tab handling remains confined to that capture window; normal
focus navigation is retained after it closes.

Dialog centring now honours the usable work-area limit even when a requested
minimum is larger than that area. These source changes do not establish that every
dialog in the application has completed visual or accessibility acceptance.

## Programmatic acceptance

115 desktop unittest tests passed using the Python 3.12 packaging runtime. The new
matrix uses a fresh Tk interpreter for each font scale, transparent mapped windows
for real geometry, long SKU/model/CPU strings, two drives, two batteries and long
footer/note content. It checks cell bounds, separation of identity/actions/title,
comparison height, visible footer controls, scoped wheel routing, focus scrolling,
hardware card bounds, readable key widths, horizontal keyboard scrolling and
restored global Tab bindings. Existing session/action-guard/storage checks now
inspect the displayed nested widgets and continue to pass.

The scale values below are **simulated Tk font scaling**, not changes to Windows
display settings or evidence of native per-monitor DPI behaviour. No screenshot
or physical VM walkthrough is claimed by these checks. Recorded geometry is in
[the generated evidence file](sc12-layout-evidence.json).

| Simulated scale | Window | Comparison viewport | Footer viewport |
| --- | --- | --- | --- |
| 100% | 1024×768 | 401 px | 160 px |
| 100% | 1366×768 | 401 px | 160 px |
| 125% | 1024×768 | 376 px | 160 px |
| 125% | 1366×768 | 376 px | 160 px |
| 150% | 1024×768 | 351 px | 160 px |
| 150% | 1366×768 | 351 px | 160 px |
| 200% | 1024×768 | 310 px | 160 px |
| 200% | 1366×768 | 310 px | 160 px |

The matrix caught and verified fixes for off-screen focus scrolling, key labels
slightly narrower than their text and the hardware Cancel footer being allocated
after a growing list at 200% scaling.

## Remaining release acceptance

Build the exact candidate and repeat the physical/VM walkthrough at 1024×768 and
1366×768, with Windows display scaling at 100%, 125%, 150% and 200%. Capture before/
after screenshots of long titles, comparison values, footer details/notes,
hardware controls, keyboard/numpad and the missing-key result prompt. Verify
monitor transitions, actual text readability, pointer hit areas, wheel/trackpad,
Tab/Shift+Tab order before/after capture, focus visibility, and all result/review
dialogs. Confirm that resize, scrolling and collapsing details preserve the active
order, exact serial, pending tests and unsaved draft. These native DPI, visual and
packaged checks remain pending. SC13 is next for saved-report presentation and
accurate empty/failure states.


## Initial window sizing correction — 28 October 2026

A physical-device screenshot showed that the post-login main window was still
capped at 1400×900 physical pixels and Hardware Tests at 620×760, irrespective of
font scaling. The hardware-test footer also reset its status wrap width to 500
pixels. At higher scaling this left roughly one test row visible. Earlier layout
checks resized the windows explicitly and did not verify their initial geometry.

The main window now scales its 1400×900 preferred size with Tk's current DPI
scaling, bounded by the monitor work area. Hardware Tests uses a scalable
1000×1000 preferred size, also bounded by the work area. Native decorations and
the taskbar retain clearance. Header context and footer status wrap to their
actual available width; status updates no longer restore the fixed wrap limit.
Windows remain resizable and the test list remains scrollable.

The new initial-layout regression checks 1280×800/100%, 1920×1080/150%,
2256×1504/150%, 2880×1920/200%, and 3840×2160 at 200% and 250%.
It constructs the actual Tk main/test widgets without production authentication
or hardware access, verifies bounds and main-content space, and requires two
complete test rows to fit alongside the long completion status. These are
simulated work-area/font-scaling checks, not a claim of fresh physical-monitor
or VM visual acceptance. The corrected build retains the restored original
speaker sample and automatic-first microphone/manual-fallback workflow.


## Details use spare comparison space — 28 October 2026

The expanded details panel now grows beyond its former 160-pixel cap when the
specification table fits and leaves unused space. It grows only as far as its
content needs, preserving the table's requested height where space permits.
When both panels need scrolling, details return to the compact baseline and the
comparison retains the remaining space. Content changes, resizing, and showing
the details again recalculate the allocation. Shorter details return space to
the specification area. Pending layout work is cancelled on lock/close.

Responsive Tk checks at 100%, 125%, 150%, and 200% cover tall-window growth,
short-content contraction, and preservation of the existing compact-window,
scrolling and toggle checks. This is automated widget-layout verification.

## Keyboard and camera opening sizes — 28 October follow-up

Keyboard sizing is calculated from the rendered keys and footer after the optional
numpad is laid out, rather than remaining at a fixed 1150-by-650 pixels. The canvas
requests room for the full key grid, and the window is bounded by the monitor work
area. Selecting the numpad recalculates the required size. Scrolling remains for
screens that cannot fit the keys or when the operator manually shrinks the window.

The camera opens at a DPI-scaled 900-by-780 preference, bounded to the work area.
Its six actions use a two-column grid. Preview frames are fitted to the remaining
body viewport after reserving room for the instructions and status, instead of
using a fixed 480-pixel image height regardless of available space.

Real Tk regressions use synthetic frames and mocked keyboard hooks at 1280x800,
1920x1080, 2880x1920 and 3840x2160 work areas with 100–250% font scaling. Checks
cover initial keyboard visibility when it fits, maximum usable width otherwise,
camera image/instruction fit and footer reachability. No host keyboard hooks or
physical camera capture are used. Native multi-monitor DPI acceptance remains
a physical bench check. Build output:
`SecondChecking Review/hardware-windows-usb-2026-10-28/ready/dist`.

### Camera preview balance follow-up

The camera's preferred opening size is reduced from 900x780 to 820x680 logical
pixels. Live frames now resize up as well as down to fit the body after measuring
the header, status, instructions and padding. Aspect ratio is preserved without
cropping. Cached source frames are redrawn after a viewport resize even if the
frame number has not changed. Only the display image is enlarged; capture scope
and saved report contents are unchanged.

The initial-size matrix now asserts the smaller opening preference, preserved
frame aspect ratio, use of the available width or height, and enlargement beyond
the original 640-pixel image when space permits. Camera lifecycle and fixed-footer
checks also pass. Output:
`SecondChecking Review/camera-preview-balance-2026-10-28/ready/dist`.

### Remove nonessential operator text

The following owner-requested pass removes implementation explanations rather
than rewriting the app's instructions. Camera discovery indices and the live
camera number are no longer shown in the test dialog or assignment coverage
summary. USB drive paths, enumeration terminology, audio backend errors and
internal WMI/registry source lines are removed from routine operator messages.
Redundant explanations about unchanged OS settings, automatic microphone noise
detection and checklist setup are removed. Keyboard text no longer uses
"logical keys" or "review coverage" terminology.

Device selectors retain backend labels where needed to distinguish otherwise
identical choices. Required actions, result states, incomplete-test handling,
manual microphone fallback, USB confirmation, unsaved-result notices and the
Autopilot NOT VERIFIED qualification remain. Capture data, provider details and
coverage scope are retained in evidence/reports and diagnostics. The smaller
camera window and expanding, aspect-preserving preview are included.

The combined build is under
`SecondChecking Review/operator-copy-2026-10-28/ready/dist`.

The battery-power follow-up also fixes an intermittent initial-position failure:
the deferred centring correction is now scheduled from the first native Map
event as well as creation, so a delayed first map cannot overwrite an earlier
correction. Later restores do not re-centre a window the operator has moved.
Eight consecutive repetitions of the position/cancellation regression passed.
