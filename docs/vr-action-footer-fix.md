# VR05 / SC12 — secondary-dialog action footers

Implemented locally on 26 October 2026. No database migration or API contract
change is required.

Webcam and USB dialogs now reserve a separate footer for all decision, retry and
cancel controls. Their descriptions, changing status text, checklist and preview
occupy a bounded scrollable body. Status/guidance wrapping follows viewport width.
Minimum window heights preserve the footer plus a small body, and camera preview
images retain aspect ratio within a width limit rather than expanding the window.
Result gating, coverage, worker cancellation and unavailable/error semantics are
unchanged.

The serial viewer reserves its status, selected-identifier details, pagination
and actions below the expandable table. Column widths use font metrics and page
content; horizontal/vertical scrollbars expose overflow. Selecting a row shows
the complete serial and SKU in a selectable, read-only text area with scrolling.
Actions still use the original exact-identifier mapping, including leading zeros.
Window sizing follows font metrics and the desktop work area.

## Validation

All 256 desktop tests passed; all tracked Python compiled. Real Tk/themed tests
at 100%, 150%, 200% and 250% cover asynchronously expanded camera/USB errors,
an oversized preview, deliberately small windows, full labelled footer bounds,
exact long serial/SKU readback and cancellation. Existing hardware coverage,
serial pagination, guarded removal and saved-report tests also pass.

The complete unsigned candidate is build
`344f001f-a7a6-4cf0-9fe9-0cfc3d7f410d`, SHA256
`d8724144bf4d667bc031a3e7c14357172f0e151f5be2d3406a7e93833482914f`.
Build and evidence are in
`C:\Users\PCR\Documents\SecondChecking Review\vr-action-footers-2026-10-26`.

The actual full candidate was exercised at 1920×1280/150% against the existing
isolated synthetic review service/database. USB's native error text remained
scrollable while every action, including Cancel, stayed labelled and visible.
Cancel returned to the test panel. The serial viewer loaded order `test`, showed
all footer controls, exposed the exact selected serial/SKU, and opened the saved
report through View Report. No stock was removed or reassigned in this pass.

Native fixtures additionally use the production dialog modules in pinned
Python 3.12/Tk/ttkbootstrap, with clearly labelled synthetic camera/USB outcomes
and database rows. They save measured button bounds plus native screen/DPI and
screenshots. Fixtures cannot establish physical hardware quality or backend
acceptance; the full-candidate checks above are distinct. Fixture tests do not
save any hardware results to the review service.

Nine native fixture cases passed measured action bounds, with button heights at
least their requested size and every action inside its window:

| Native screen / DPI | Fixture states checked |
| --- | --- |
| 1920×1080 / 125% (120 DPI) | Long camera error; long USB error |
| 1920×1280 / 150% (144 DPI) | Long camera error; long USB error |
| 3840×2160 / 200% (192 DPI) | Synthetic camera preview; long serial/SKU |
| 3840×2160 / 250% (240 DPI) | Long camera error; long USB error; long serial/SKU |

Both serial fixtures retained the exact leading-zero serial and full long SKU in
the selectable detail area; horizontal/vertical overflow remained accessible.
The fixture database adapter was corrected to accept the reader's keyword
argument before serial cases ran. Product code and the full candidate were
unchanged during native fixture verification. Native cases and PNG hashes are
indexed in `verification.json`; the initial/corrected fixture hashes distinguish
their test-harness versions. Physical devices remain untested.

The guest was returned to 1920×1080/100% and temporary global display-resolution
settings were restored. No additional VM or OVA was created.

## Newly observed worker-file error

The actual USB run reported `[Errno 13] Permission denied` while accessing its
owned `ready.json` startup file under `C:\SC22Visual\ActionTemp`.
`screens/candidate-usb-status-150.png` records the error with all footer controls
visible. The cause is not established; do not infer that USB hardware failed or
that increasing timeouts will repair it. Track as VR08 / SC11 and investigate
before release, alongside the remaining VR03 live-DPI transition work.

26 October follow-up: [VR08 file-access recovery](vr-worker-file-access-fix.md)
now handles bounded transient sharing/access failures. Its Windows lock tests and
representative full-candidate USB polling/cancellation passed. The original lock
holder remains unidentified; the observation above is retained as baseline evidence.
