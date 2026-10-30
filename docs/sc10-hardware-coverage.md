# SC10 — state and record hardware coverage

Implemented in local desktop and matching Web-Tools source on 22 October 2026.
The executable and VM have not been updated. Physical and packaged acceptance
remain outstanding. No database migration is needed: coverage is optional versioned
metadata inside the existing saved report JSON.

## What the checks prove

| Check | Coverage and result meaning |
| --- | --- |
| Wi-Fi adapter | Uses the language-independent Windows WLAN API to enumerate enabled WLAN interfaces. A ready interface gives an adapter-detection Pass, including when disconnected. No interfaces/not ready gives Unavailable; API, permission or service failures give Error. Disabled hardware cannot be distinguished from absent hardware by an empty enumeration. Connection, signal, throughput and internet access are not tested. |
| USB | No port count, label list or per-insertion confirmation is required. The operator moves a known-good flash drive between physical ports and each fresh insertion is recorded automatically. Finish Pass requires at least one detection, working enumeration and the operator's explicit confirmation that every physical port was checked. An already-present connection or unchanged polling result cannot add another check without removal/reinsertion. Recovery from an enumeration error establishes a fresh baseline. The app cannot prove port uniqueness or completeness from logical volumes. USB classes, speed, charging, video and file integrity remain untested. |
| Keyboard | Shows observed/missing logical keys for the displayed UK/ISO layout and selected numpad scope. A partial capture can pass only after the operator records what was checked manually; this explanation is saved and shown during assignment review. Fn and firmware functions need manual checks. Logical events cannot prove physical key position, legends or firmware functionality. Alternate layouts and unsupported keys require explicit manual confirmation or a non-pass result. |
| Display | Shows inspection instructions and five colour screens, with Click/Space/Enter to advance and Escape to cancel. Records the colours actually shown. The operator checks pixels, lines, flicker and uneven lighting on the current screen. Native-panel resolution, additional displays and calibrated colour accuracy remain unverified. Result prompts no longer pass from an unrelated Enter key. |
| Camera | Records the first readable DirectShow camera index from 0–9 and preview frame count. No readable camera is Unavailable, including privacy/driver limitations; API exceptions are Error. A Pass requires an observed live preview without a current preview error and explicit operator confirmation. Other cameras, microphone quality and calibrated camera quality remain untested. |
| Audio | SC09 independently checks the selected speaker and microphone by operator listening confirmation. Noise cannot auto-pass either. See [SC09](sc09-independent-audio.md). |

USB has explicit Finish, Fail, Unavailable, Error and Cancel actions. There is no
checklist setup or count field. Device enumeration failures are displayed and preserved,
rather than becoming an empty successful enumeration. The app does not write to
test media. Closing USB or the keyboard capture cancels directly. Keyboard capture
has a separate Finish and review action, and the result prompt provides Unavailable.
Tab interception is scoped to the keyboard window; global bindings are preserved.
Missing keyboard dependencies or failed hook installation record Error and clean up
partially installed hooks.

Camera probes now release unsuccessful captures as well as successful ones.
Loading cancellation suppresses queued completion, and closing the preview cancels
its frame timer and releases the capture. Native camera/WLAN calls are not given an
overall worker timeout here; broader I/O responsiveness and Run All cancellation
remain SC11. This item must not be presented as closing those lifecycle gaps.

## Saved evidence

`test_coverage` maps test keys to version 1 entries containing UTC `checked_at`,
`scope` and a `details` object. It contains numbered insertion checks/detections,
`operator_confirmed_all_ports` and `port_count_declared: false`, logical keyboard
coverage/manual confirmation, shown display colours, camera index/frame count and
WLAN interface descriptions/states. No image, key sequence, typed phrase, network
password or USB file content is saved. Key coverage is a set of logical key names,
not ordered keystrokes.

Coverage is copied into device/order drafts, included in the final assignment
summary, uploaded with both normal and create-stock report paths, and read back
from the authenticated saved-results endpoint. Retesting one component clears only
that component's old coverage. Override history and coverage remain separate.
Older reports without coverage return an empty mapping; their coverage must not be
inferred. SC13 still owns the complete report-viewer presentation.

The matching server validates known test keys, entry version, timestamp, scope,
details shape and a 32 KiB metadata limit before assignment writes. A submitted
keyboard Pass with recorded missing keys requires a manual confirmation reason.
This validates the report contract, not the truth of physical operator assertions.
Deploy the matching server with the client to preserve readback. SC04 continues to
require an assignment reason for failed/incomplete/unavailable/error/cancelled
results and overrides.

## Physical acceptance matrix — not yet run

Record device model, serial, client build/hash, OS/language, operator, date and
outcome for each row. Use synthetic orders against the isolated matching server.
These rows define repeatable acceptance, not completed physical evidence.

| Device/setup | Required checks and expected evidence |
| --- | --- |
| VM without hardware passthrough | No WLAN/camera/audio endpoint is unavailable or a specific service/API error, never an inferred hardware defect. Cancel each check and confirm no result is assigned to another component. |
| Known-good laptop | List every physical USB port (including applicable USB-C adapters), test a known-good flash drive in each, verify logical key coverage plus layout/Fn manually, inspect all five display colours, and review the selected camera/audio devices. |
| Laptop with numpad | Repeat keyboard capture with numpad included; verify missing keys and manual explanations survive draft/restart, assignment and readback. |
| Alternate keyboard layout | Verify differing key names are visible as incomplete capture and a partial Pass requires a saved manual check explanation. No accidental result from Enter while finishing. |
| USB/media limitations | Test an already-connected drive, repeated same port, removal/reinsertion, missing media, fixed-disk USB enclosure and enumeration failure. Listed ports need fresh observations; unobserved functions remain untested. |
| Multiple/absent/blocked cameras | Verify index/scope, no camera, privacy denied, camera busy, camera removal, failed read, loading cancellation and preview cancellation. An unavailable preview cannot Pass. |
| WLAN states/localised Windows | Test disconnected and connected enabled interfaces, disabled adapter, no adapter, stopped WLAN service, access denied and non-English Windows. Adapter presence never claims network quality. |
| Network bench acceptance | If connection/throughput is part of the bench standard, separately record connection to the approved test AP, usable traffic and required speed/signal criteria. SC10 does not automate or certify these checks. |
| Known faulty hardware | Verify observed faulty port/key/pixel/camera outcomes are recorded as Fail, then prove assignment only proceeds with the SC04 reason. |
| Saved evidence | Restore a draft, assign, reopen results and compare coverage, partial-capture explanation, states and overrides with what the operator checked. |

Automated tests use mocked hardware boundaries and real hidden Tk controls; they
do not establish physical hardware quality. See the current test totals in the
[improvement plan](app-improvement-plan.md).

The WLAN binding follows Microsoft's [WlanEnumInterfaces contract](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlanenuminterfaces), including freeing the returned list and closing the client handle.
