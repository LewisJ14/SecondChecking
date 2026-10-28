# VR02 / SC08 — separate battery health capture

Implemented and tested in the packaged Windows VM on 23 October 2026.
The desktop now reads active `root\wmi` BatteryStaticData and
BatteryFullChargedCapacity records, joining by case-insensitive InstanceName.
Duplicate names/serials and reversed enumeration order cannot merge packs.

Missing/duplicate capacity records, unknown capacity sentinels, zero design
capacity and mismatched inventory counts remain unreadable. Zero full capacity
is a valid 0% reading. Relative capacities retain a `relative` unit instead of
being labelled mWh. Unsupported native providers retain the conservative
BatteryInfoView fallback; malformed native identities do not fall back to a
selected-pack export. No database migration is needed.

The report attachment is now `battery-wmi.json` for this source, containing raw
per-instance capacities and the interpreted evidence with capture time/source.
Legacy helper function names remain compatible with their existing callers.

## Validation

- All 252 desktop tests passed; all tracked Python files compiled. Added tests
  cover reversed records with 90%/50% health, incomplete/duplicate records,
  unknown capacities, relative units, inventory mismatch, native capture/report
  preservation and unsupported-provider fallback.
- Built the complete unsigned review executable with pinned Python 3.12 and
  PyInstaller 6.3.0. SHA256:
  `da49b689bd9d528302d5f6351e7fa6c4b6e2bacc6fa0c34fe61047d81804da9d`.
- Ran the actual executable in visible `SecondChecking-Test`, 1920×1080/100%.
  Both persistent BatterySimulator packs displayed 90.9% health, with distinct
  `root\devgen\1_0` and `root\devgen\2_0` identities. Each independently reported
  design 110 / full 100. These are simulator values, not physical acceptance.
- Saved the actual frozen GUI capture through the isolated Web-Tools API as
  tester to order `test`. Report ID 2 retained both battery entries and the exact
  report content; the serial attachment also survived an exact JSON readback.
  The harness retained prior synthetic hardware results and recorded its reason;
  this was an API persistence check, not another complete GUI assignment pass.

Evidence is in `C:\Users\PCR\Documents\SecondChecking Review\vr-dual-battery`
(`build-record.json`, `vm-specs.json`, `vm-save-evidence.json`, `save_probe.py`).
Screenshots `battery-fix-measured.png` and `battery-fix-error.png` are in the
adjacent `sc22-visual\screens` folder. The original application and exported OVA
were not replaced. Physical multi-pack hardware and signed release acceptance
remain outstanding.

## Additional observation

The first fresh startup capture produced a “Fresh device measurements are
unavailable” message despite writing valid battery/spec evidence. An explicit
Refresh Device succeeded and displayed both packs. Investigate this intermittent
freshness rejection next (VR07 / SC08); a clock precision difference between
timestamp APIs is a hypothesis, not an established cause. Retain rejection of
meaningfully future/stale captures while correcting the issue.
