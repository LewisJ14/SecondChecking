# SC22 physical bench checklist — 27 October 2026

Status: prepared, not physically executed. The owner has explicitly skipped the
proposed hours-long stability run. No two-hour or overnight test is required or
scheduled; the completed accelerated worker/restart evidence remains valid.

Use the current review executable, version 0.1.36, build
`73ce3899-7694-4e1b-8217-46d41f87cd5e`, SHA-256
`c9d9276561bd8908fe3cfe737fd6712eba1f9953dd8a38fc3c969279b9f1b9de`.
Host file:
`C:\Users\PCR\Documents\SecondChecking Review\sc22-real-update-readiness-2026-10-27\candidate\dist\main.exe`.
This is an unsigned review build. Its build inputs match the current repository.
Use a matching isolated service/schema, synthetic orders and test assignments;
configuration, credentials and private recovery material stay outside Git.

## Practical sequence

Allow roughly 15–20 minutes for the core sequence on a representative laptop,
depending on the number of ports and manual checks. This is a planning estimate,
not a mandatory timer. Record model, serial, OS, keyboard layout, operator, date,
build ID and actual outcome. Mark an unavailable setup Not Run with its reason.

| Check | Action | Expected result/evidence |
| --- | --- | --- |
| Identity and refresh | Sign in, load the synthetic order, note serial and capture time, then Refresh Device. Compare installed RAM and individual drives with the SKU. | Correct device/order retained, fresh measurement time, existing draft preserved. Two 512GB drives do not satisfy a SKU requiring one 1TB drive. |
| Battery | Compare per-pack full/design capacities with the device's available battery evidence. Check live power state on AC and battery where supported. Include a dual-pack device if available. | Health and current charge stay separate; packs are paired correctly. Unreadable evidence is not healthy or absent. AC connection alone is not confirmed charging. |
| Keyboard | Select the applicable numpad scope; exercise the displayed logical keys. Check layout-specific and Fn functions manually. Cancel once, then finish. | Missing keys remain visible. Partial capture can pass only with the required manual explanation, preserved in the report. Closing records cancellation. |
| USB | Label each physical port. Use known-good removable media, remove it between ports, and obtain a fresh appearance for every listed port. | Finish Pass requires all listed ports. Already-connected media cannot certify a new port. Coverage identifies removable-volume detection, without claiming speed/charging/video. |
| Display | Inspect all five colour screens. Cancel once and repeat to completion. | Reachable controls; explicit operator decision records the result. The check covers the current screen; reported display mode does not certify native-panel capability. |
| Camera | Confirm an actual moving preview, then explicitly choose the result. Close during loading and during preview on separate attempts. | Preview is live; missing/busy/unreadable devices cannot pass. Cancellation releases the capture and the app stays usable. |
| Speaker | Select the intended output and listen to the complete original sample playback. | Explicit listening confirmation; correct output. The app does not raise Windows volume or pass the microphone automatically. |
| Microphone | Select input/output and try automatic detection; retry in silence, then record/replay a phrase manually. Cancel a separate capture. | Sound (including background noise) may auto-pass the microphone. Insufficient sound/errors enable manual phrase replay. Cancellation closes owned streams; speaker result stays independent. |
| WLAN | Check a supported enabled adapter, disconnected and connected if available. | Adapter detection is distinguished from connection/throughput. A service/API failure is Error, not an invented hardware defect or network-quality pass. |
| Run All cancellation | Start Run All, cancel an active check and reopen the panel. | Sequence stops, later checks remain Not Run, controls recover and no active device is retained by the cancelled check. |
| Save/readback | Keep one non-pass result; confirm blank assignment reason is rejected. Supply a reason, assign to the synthetic order, reopen the saved report. | Correct order/serial, independent results, coverage, battery evidence and recorded reason match the reviewed submission. Use isolated fixture data only. |
| Draft/restart | Leave a local draft, close normally, reopen, sign in and reload its order. | Correct draft restored; no results leak between orders/devices. |

Known faulty hardware and alternate keyboard/camera configurations are useful
additional samples when already available; unavailable equipment is recorded,
not simulated as a physical pass. This checklist does not request changes to
Windows privacy/security settings or production configuration.

## Physical monitor transition check

On supported hardware, check 1080p at 100%, 4K at the operator's normal scale
(including 200/250% where used), and the Surface's actual native resolution and
scale. Record the real dimensions; do not assume a particular Surface model.
Move the open app between monitors with different scales, including with a
serial list or saved report open. Check fonts, scrolling, selection, dialog
bounds and the availability of primary actions. Preserve the selected item and
draft. VM resolution changes do not establish this physical transition result.

## Record outcomes

For each failure record the action, expected/actual result, affected build and
a current screenshot. Keep serials and private evidence in the local review
location. A physical defect, missing test equipment and an application failure
must be distinguished in the notes. The screen merely opening does not pass a
functional hardware check.

Still separate: production publisher/exact-tag hosted release, alternate-admin
and disposable-environment Sysprep, and actual installation of an offered update.
The working VM's module/policy and later app are not included in the retained
historical OVA until a future export is explicitly requested.
