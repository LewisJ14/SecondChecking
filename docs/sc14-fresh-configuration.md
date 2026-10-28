# SC14 — reliable fresh configuration

Implemented locally on 22 October 2026. Exact packaged/clean-VM acceptance remains pending.

The eager `os.getenv` fallback is removed. Database settings use environment
presence first and a safe optional INI fallback per field. Empty environment
values deliberately fail validation. Literal percent passwords work without
interpolation. Configuration paths are consistent across DB/API/SKU/hardware:
repository root in source, executable directory when frozen, or explicit
`SECOND_CHECK_CONFIG`. An absent default file permits environment-only setup;
a missing explicit file or malformed INI produces safe actionable feedback.

Startup user loading validates required DB/API fields before any connection.
The existing login Retry action reloads file settings. Required blank,
placeholder/control-character values and invalid API URL forms are rejected.
No database credentials, malformed INI lines or driver exception text are
included in configuration/connection errors. There is no embedded API host.
Optional missing search lists produce Unknown rather than a startup exception;
hardware defaults use the same configuration file.

`python src/main.py --check-config` validates settings then performs only a
bounded `SELECT 1`, closes the connection and returns exit 0/1. It bypasses GUI
and hardware imports and does not call schema repair. It verifies database
reachability, not user-table/schema compatibility or API authorization. Normal
connections still perform runtime schema checks/DDL: that remains SC15.
`config.example.ini` contains placeholders only; private configs were preserved.

Verification: 132 desktop tests passed, including ten new checks for environment
only, file only, mixed precedence, empty overrides, percent passwords, invalid
and missing fields, malformed files, source/frozen path selection, credential
redaction, read-only probe cleanup, login Retry and a real clean subprocess
started from an unrelated directory. DB/HTTP boundaries are mocked; no test
contacts the configured database. Optional SKU fallback is also exercised.

Release acceptance: package current source, start a fresh VM without config.ini,
set private environment settings, confirm login and API-backed order lookup;
repeat with a private file and mixed overrides. Demonstrate missing/malformed
settings, safe Retry and logs without supplied values. Verify the exact frozen
artifact's path resolution and first-run feedback. No new executable or VM
acceptance was produced for this item.
