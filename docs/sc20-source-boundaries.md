# SC20 source tracking and service boundaries

Implemented locally on 22 October 2026. Generated/private files are removed from the Git index and ignored; their on-disk copies remain available. Reviewed application source, tests, documentation and packaging inputs are staged. No commit, history rewrite, push, release publication, database migration or deployment was performed.

## Source tracking

The repository tracked build intermediates, distribution executables, local configuration/logs, cached device specifications, last-user preferences, a source ZIP, a generated update manifest, duplicate runtime assets and BatteryInfoView preferences. Existing ignore rules did not untrack these files.

The cleanup removes **28 entries from the index only**. Before removal, their filenames, sizes and SHA-256 hashes were recorded outside the repository, alongside a copy of the previous Git index. Each local file was hashed again immediately after the index operation and matched. The cleanup did not delete or alter them. Tests may subsequently append runtime logs normally. Local recovery records are under `SecondChecking Review/sc20-source-cleanup`; they were not added to the repository.

Canonical public runtime resources remain tracked under `src/assets`, alongside the existing MySQL authentication DLL. Duplicate root `assets` and `dist` copies remain local and ignored. Source-mode BatteryInfoView lookup now uses the canonical source resource first, so a fresh checkout does not require a duplicate tool or an unnecessary download. Frozen lookup still prefers the extraction directory. The tool was not executed during this task.

Ignore rules cover generated release identity/output files, local preferences, rotated logs, update journals/backups, drafts/pending operations, source archives and local signing/environment files. `config.example.ini`, source, tests and implementation/evidence documents remain trackable. The obsolete `runtime-files.json` now has an empty list; no build should copy a bench's private config or logs.

`scripts/check_source_policy.py` inspects the current Git index. It rejects classified runtime/private paths, generated build directories, duplicate resources and unapproved binary/public-resource inputs. It also requires application/script/test Python files and mandatory public build resources to be tracked and present. Required source files can no longer be silently left untracked. Intentional new public resources require an explicit policy/spec update. The check reads filenames and source inventory, not private configuration contents.

The SC19 workflow runs the policy check, and strict release source validation calls it before packaging. Release provenance now also fingerprints the ignore/attribute rules, example config and empty legacy runtime manifest. Source changes remain dirty until committed and therefore cannot pass the clean tagged-release gate.

This is a working-tree/index cleanup, not erasure of historical commits or a general secret-content scanner. Historical revisions still contain the removed files; any decision to rewrite history or invalidate previously committed credentials remains separate. No credential values were printed, copied into documentation or changed by this task.

## Service boundaries

Authentication now resolves API settings directly through `services.configuration`. It no longer imports the large hardware/specification helper module. Configuration errors retain safe field-name messages, environment precedence and retry behaviour. Logout still clears the local session first and tolerates unavailable/malformed service configuration.

Database settings likewise read the configuration service directly, and connection logging uses the new `services.runtime` module. That module owns the existing app/log paths and bounded log rotation without GUI, SQL or hardware dependencies. The old helper function names remain compatibility delegates, preserving existing callers and default paths. Logging failures are silent and safe when a windowed app has no stdout/stderr.

The database module no longer imports Tk at module load. Its existing interactive error adapter imports the message box lazily only when a caller requests errors. Headless callers using `show_errors=False` stay free of GUI/hardware imports, including failure paths. Existing read-only schema gating, retry/close behaviour and safe diagnostics are retained.

SQL writes/schema changes remain server-owned under SC01/SC15/SC16. Direct desktop SQL reads remain for existing order/spec/schema lookups. `main_logic.py` still combines UI orchestration with read queries, and `utils/helpers.py` retains legacy hardware/payload compatibility functions. This item does not claim a complete rewrite of those modules; it removes the low-level configuration/logging dependency cycle and protects the source/package boundary without changing operator policy or assignment contracts.

## Verification

Thirteen new source/boundary tests exercise real disposable Git indexes, classified artifact rejection, required/untracked/missing source detection, ignored private-file preservation, CLI failure without private-content output, public-resource/example visibility, fresh headless service imports, read-only connection failure without GUI/credential output, API environment precedence, safe configuration failure, windowed logging failure/rotation and canonical BatteryInfoView resolution. No real service login, database mutation, hardware capture or GitHub write runs in these tests.

The existing packaged BatteryInfoView fixture now explicitly simulates `sys.frozen` and `_MEIPASS`, rather than relying on the old root duplicate resource. Measurement, authentication, configuration and schema regression assertions remain in place. Final suite/compile/policy counts and source fingerprints are in [the evidence record](sc20-source-evidence.json).

Prior SC17–SC19 executable/evidence records are historical snapshots with their original hashes; those artifacts do not contain the subsequent SC20 source changes. A new exact release still requires coordinated server/schema deployment, hosted CI, signed update/rollback and VM/physical acceptance. No new main executable was deployed for SC20.

## Next

SC21 covers transport and maintenance privilege boundaries. SC22 retains the clean/portable VM image and physical acceptance matrix. Commit/release decisions remain pending review of the staged changes; runtime files must not be force-added back into the index.
