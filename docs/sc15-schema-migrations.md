# SC15 — explicit migrations and read-only compatibility

Implemented locally on 22 October 2026. No configured astro/production database
was migrated and no grants were changed. Deployment and packaged/VM/MySQL
least-privilege acceptance remain outstanding.

Normal desktop connections now run the read-only contract in `src/db/schema.py`
before returning a connection. Missing/invisible required tables or columns and
inspection errors fail closed, close the connection and do not retry a structural
failure as a transient network problem. Background callers receive a safe typed
error; interactive callers receive an upgrade dialog. Login shows a short Retry
message so long missing-column lists cannot displace its controls; logs and
`--check-schema` include the contract identifiers. No supplied values/driver text
are exposed. Successful checks are not cached across connections.

`ensure_schema` remains a validation-only compatibility alias. Desktop ALTER,
automatic column repair, schema commits and swallowed repair failures are removed.
Contract 1 names nine direct-use tables and required columns, including login,
notes, custom-item specifications and SKU metadata/rules. It accepts extra fields
and equivalent later schemas. It checks presence/visibility, not every type, index,
constraint or privilege. API capability checks remain separate.

Web-Tools migration `0c8d9e0f1a2b` follows SC01 and adds missing legacy desktop
columns plus missing user.must_reset_password (default true), retaining existing
column definitions and values. The Wi-Fi column is also represented in OrderSerial.
The bridge is safe to rerun after partial additive DDL. It rejects missing base
tables and refuses downgrade because columns may predate this revision and contain
data. Full DB rollback uses a verified backup.

A real isolated replay of historical initialization reproduced duplicate creation
of sku_detection_rule: the initial revision creates current models before later
creation migrations run. Rather than rewrite historical migrations, the explicit
server `schema init-empty` command now creates the current primary schema and
records the exact head. It refuses any existing tables/views, uses exclusive-access
setup, avoids the Aiken bind and never stamps after creation failure. MySQL DDL can
auto-commit: a failed setup may need administrator inspection of partial tables.
Existing versioned installations still use `db upgrade`; existing unversioned
installations require the separately reviewed legacy bootstrap.

README and database documentation replace incomplete standalone-SQL provisioning
advice with these setup/upgrade paths, minimum migration, read-only check command,
rollback limits and desktop grants. The historical SQL file remains reference only.
Desktop grants need required SELECTs, note INSERT/UPDATE and existing password-field
UPDATE; no schema/assignment-table write grants. SC16 retains service permission work.

Verification: 141 desktop tests (including nine compatibility tests) and 33 isolated
Flask transaction regressions plus six migration/setup tests passed. Tests cover
normal connection refusal/cleanup/no DDL/no commit, readable supported/byte-valued
metadata, missing tables/columns, safe permission failure, Retry, explicit read-only
probe, legacy upgrade/retry/data preservation, current-model contract coverage,
downgrade refusal, fresh creation/stamping/no-op follow-on upgrade, existing-schema
refusal, untouched Aiken and no stamp after creation failure. Tests use mocks and
disposable SQLite only. Existing Flask-SQLAlchemy get_engine deprecation warnings
remain in migrations/env.py.

Release steps: verified backup; deploy matching server; apply migration with separate
administrator credentials; verify revision and desktop `--check-schema`; deploy
new desktop; test actual restricted MySQL grants, migration failure/retry, login,
custom-item search, notes, assignment/report/removal against the paired service.
Repeat in the packaged VM. No existing bench data was altered for these tests.
