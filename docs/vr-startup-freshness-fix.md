# VR07 / SC08 — startup freshness precision

Implemented locally and checked in the visible Windows VM on 26 October 2026.

`utc_now` previously created a microsecond datetime using `datetime.now`, while
`capture_age` subtracted its float epoch value from `time.time`. An immediate
comparison can be negative by a fraction of a microsecond due to clock/conversion
precision, causing valid measurements to fail the strict future-date check.
The earlier VM startup had rejected a capture despite writing valid device data.

Timestamp creation and checking now both convert `time.time` to UTC datetime
microseconds and subtract datetimes. No future-date grace period was introduced.
Expired, malformed, timezone-less and genuinely future captures remain rejected;
the five-minute freshness limit and serial identity checks are unchanged.

## Evidence and limits

- A host Python 3.12 experiment with 100,000 immediate datetime/epoch comparisons
  produced 814 negative ages, minimum −0.238 microseconds. The corrected capture
  path produced zero rejections in 100,000 checks. This demonstrates the precision
  defect; the exact timing of the original 23 October failure was not instrumented.
- Deterministic regression tests cover an epoch which rounds upward into datetime
  microseconds, immediate disk-cache save/read, exact expiry, just-expired data and
  future captures. All 254 desktop tests passed and all tracked Python compiled.
- A separate frozen Python 3.12 probe ran the previous full timestamp roundtrip
  and the corrected path 100,000 times each inside the VM. Neither failed in that
  batch; the corrected path also rejected future/expired/invalid values. This
  is not a claim that the timing-dependent old failure repeats on every machine.
- Built and ran the complete current GUI candidate, build
  `e88b52b7-c186-40f6-a9c8-43a6d5a02e0e`, SHA256
  `2f8ccfa78e269271cf7917badf9a8fe87f2e381df67b0d72a7a3c19d9aad41ef`.
  Startup capture and five subsequent explicit Refresh Device operations passed
  at 1920×1080/100% with no refresh-error dialogs. Each wrote a new capture and
  retained two measured batteries at 90.9% health.

Evidence and the unsigned review executable are in
`C:\Users\PCR\Documents\SecondChecking Review\vr-startup-freshness-2026-10-26`.
The probe is a small test executable using the pinned runtime; it is distinct
from the full application whose GUI was also exercised. No production database
was changed. Signed release, physical hardware and long-duration clock-change
acceptance remain outstanding. VR01/VR05/VR03 scaling/layout fixes are next.

During this check the host drive filled and VirtualBox paused the VM. The
owner-authorized [disposable image cleanup](sc22-repeatable-testing.md#disposable-image-cleanup--26-october-2026)
restored space and the VM resumed before GUI regression completed. The current
working VM and latest checksum-verified battery OVA are retained.
