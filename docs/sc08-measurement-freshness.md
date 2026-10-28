# SC08 — measurement freshness and source

Implemented locally on 22 October 2026. Packaged VM capture and isolated server
save/readback were verified on 23 October; see the
[dual-battery follow-up](vr-dual-battery-fix.md). Physical battery/display and
release acceptance remain outstanding. The [VR07 correction](vr-startup-freshness-fix.md)
addresses false-future rejection at a timestamp precision boundary.

## Capture and refresh

Refresh Device performs a background measurement capture. It preserves unsaved
check drafts and the resolved order/item, disables stale actions while running,
then displays the new measurements. Changed device identity rejects the refresh
for an existing order instead of attaching its draft to a different serial.
Startup measurement gathering also uses this background path. Worker-launch and
capture failures restore controls while keeping drafts.

The header identifies capture time, age and source; age updates periodically.
Both memory and persisted specification caches expire after 300 seconds. Missing,
future or expired capture times are not fresh. Cache results use independent deep
copies. Each order search forces a capture, and assignment captures again before
final review and verifies the exact serial. A failed fresh capture never silently
submits the old comparison snapshot.

Report JSON retains `Measurements` and `Battery Evidence`. Saved-result readback
includes measurement metadata, battery evidence and battery export source/time.
No database migration is required. Receipt retry intent ignores capture timestamp
changes alone while preserving changes to the actual evidence.

## What the measurements mean

- Resolution is labelled **Current display mode**, with panel capability explicitly
  unverified. A matching Windows mode does not receive a native-panel MATCH verdict.
  The footer/final review requires acknowledgement of this remaining uncertainty.
  No EDID/native-panel capability detector was added.
- Windows is labelled **Windows edition**, separate from the activation test.
- Battery **health** is derived from paired full/design capacity values, with its
  source and capture time. Live battery **current charge/power state** is displayed
  separately. Low or zero measured health is distinct from unreadable data.
- An empty successful Windows battery inventory is **Absent**. Probe/export/parse
  errors are **Unreadable**, never proof of absence or a default healthy result.
  Unreadable battery text cannot receive a MATCH badge merely because it contains
  no numeric percentage.
- Live AC-power status is not treated as charging confirmation. Windows distinguishes
  that state from charging:
  [Microsoft Win32_Battery reference](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-battery).

## Battery export reliability

The existing BatteryInfoView helper now resolves its bundled path independently
of the working directory. Missing-helper download uses a network timeout. Every
export runs in an isolated temporary directory with a fresh filename and a
30-second process timeout; no previous CSV can substitute for a failed run.
Temporary exports are cleaned up. UTF-8/BOM, UTF-16 and legacy Windows text are
decoded without silently dropping characters.

The documented `/scomma` export is parsed with CSV quoting/delimiter handling,
rather than extracting unrelated numbers from lines. Full/design capacities stay
paired by battery column or horizontal record. Quoted thousands separators,
decimal commas, semicolon/tab delimiters, zero charged capacity, missing slots,
unit conflicts and duplicate rows have explicit handling. An inconsistent inventory
count or unsupported/localised field labels yields unreadable health for review.
The report used for upload is the one attached to the reviewed snapshot; the app
does not recapture a different export after the operator confirms.

The helper's export command and health field are described by its publisher:
[BatteryInfoView documentation](https://www.nirsoft.net/utils/battery_information_view.html).
Real exports from supported batteries/helper versions still require bench checks;
fixtures do not establish physical accuracy or every language's field names.

## Verification and remaining acceptance

100 desktop tests passed on Python 3.12, including cache expiry, future timestamps,
independent cache copies, forced assignment capture/serial checks, dual-battery
CSV layouts and decimal formats, missing slots, zero/unknown data, isolated export
paths, timeout/missing-output rejection, UTF-16, bundled paths and AC-power status.
Actual hidden Tk controls exercise Refresh Device while preserving an unsaved
order draft and updating the displayed resolution/source/age.

27 real Flask tests passed with isolated SQLite, including saved measurement and
battery metadata readback. 77 desktop and 195 Web-Tools Python files compiled;
scoped whitespace checks passed. No additional MariaDB acceptance run or migration
was performed. No executable was rebuilt or deployed during SC08.

Before release, compare fresh captures on single/dual-battery laptops, absent and
unreadable batteries, zero/poor health, changed Windows display modes, AC/charging
states, helper timeout and packaged helper lookup from another working directory.
Verify native panel capability separately; a VM/current display mode cannot prove
it. Broader Run All lifecycle (SC11), scaling/layout (SC12), helper integrity (SC17)
and release/VM acceptance remain open. SC09 independent audio tests is next.
# Live battery power — 28 October 2026

The current-charge label now includes charging/discharging rate in watts where
Windows reports a valid reading, for example `Charging — 18.4 W` or
`Discharging — 7.6 W`. `BatteryStatus` is paired with static/full-capacity data
by case-insensitive instance identity. Multi-pack capacity and rate readings use
the same identity, regardless of provider enumeration order. Single-pack systems
may retain the standard Windows charge percentage if native capacity is absent.

Capability-relative counters, missing rates and Windows unknown-rate sentinels
are never labelled as watts. An unavailable provider retains the standard charge
reading and displays `rate unavailable`. Missing data is not a zero-watt reading;
idle zero is shown only when both rate counters explicitly report zero. Native
charging/discharging flags supersede the generic AC-present status. AC presence
alone still does not establish charging, and a plugged-in battery may discharge.

Provider objects are created and released inside the existing owned, COM-balanced
live battery worker. Its ten-second polling interval is unchanged. No charge-rate
estimate is inferred from successive percentages, and no battery/charger settings
are changed. Health percentages and cycle counts retain their separate meaning.

References: Microsoft BATTERY_STATUS and BATTERY_INFORMATION documentation:
https://learn.microsoft.com/en-us/windows/win32/power/battery-status-str
https://learn.microsoft.com/en-us/windows/win32/power/battery-information-str

Regression coverage includes charging, discharging on AC, confirmed idle zero,
invalid/sentinel/relative rates, reversed two-pack records, duplicate identities,
provider fallback, native capture integration and narrow/high-scale charge labels.
Physical rate availability still depends on the tested battery/driver.
Output: `SecondChecking Review/battery-power-2026-10-28/ready/dist`.

