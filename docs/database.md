# Database compatibility and migrations

Web-Tools owns the database schema. The desktop never creates or alters tables.
`sql/001_create_order.sql` is retained as historical reference only: it is not a
current provisioning or incremental migration script. `CREATE TABLE IF NOT EXISTS`
does not upgrade definitions on existing tables.

## Supported contract

Desktop contract 2 is defined in `src/db/schema.py`; minimum matching server
migration `0d9e0f1a2b3c` follows the SC15 bridge `0c8d9e0f1a2b`. Later equivalent schemas are
accepted by structure, without requiring the desktop account to read Alembic
administrative tables. The check queries information_schema.columns with bound
parameters before returning each normal connection; it does not cache success.
Missing required tables/columns or failed inspection closes the connection and
blocks use. Login retains Retry after the administrator corrects the schema.

Required tables and purpose:

| Table | Desktop use |
| --- | --- |
| order | Resolve exact display/external references and SKU |
| order_serials | Assigned serial list and legacy check-state read |
| order_note | Read saved notes; writes now use the authenticated service |
| custom_order_item | Saved per-item specification candidates |
| dropdown_option | Specification metadata |
| attribute_term_metadata | SKU tag metadata |
| attribute_dropdown_map | Specification category mapping |
| sku_detection_rule | Administrator-managed detection rules |

The contract checks required column presence/visibility, not every server index,
constraint, type or row privilege. API assignment/removal/report writes still go
through the matching server and its capability checks. An unrelated table or newer
extra column does not make a schema incompatible.

## Setup and upgrade

Use private deployment settings and a separate administrator account. Stop clients
and give setup exclusive database access. Verify backups before existing-schema work.

- Empty database: in Web-Tools, run `flask --app run.py schema init-empty`. It
  refuses any existing tables, creates current primary model tables, then records
  the repository migration head. The external Aiken bind is untouched. The old
  root-to-head replay currently fails on duplicate SKU-rule creation; use this
  explicit fresh-install path rather than replaying historic initialization.
- Existing versioned database: run `flask --app run.py db upgrade`, then
  `flask --app run.py db current`. The SC15 bridge only adds missing legacy fields;
  it preserves existing values and definitions and can resume after partial DDL.
- Unversioned existing database: follow the server's reviewed legacy bootstrap
  instructions with backup/inspection. Never stamp head merely to hide missing
  migrations. `schema init-empty` deliberately refuses this case.

Then from SecondChecking run `python src/main.py --check-schema`. Exit 0 means
configuration, bounded SELECT 1 and desktop contract validation succeeded; exit 1
reports a safe setup/compatibility failure. It does not verify API authorization.
Validate the matching API and main-app workflow in isolation before deployment.

The bridge adds missing sku/battery/battery2/microphone/Wi-Fi/MDM/operator/status
columns and missing user.must_reset_password (default true). The migration is
forward-only: columns may already predate it and contain data, so downgrade refuses
to delete them. Restore a verified backup for a full database rollback. Fresh setup
may leave unstamped partial tables on DDL failure; inspect before retrying.

## Desktop permissions

The desktop needs SELECT on the eight contract tables. Login, password resets and
note writes now use authenticated Web-Tools services; no user-table SELECT or
INSERT/UPDATE/DELETE/CREATE/ALTER/DROP grants are needed. Migrations use separate
credentials. Retire old clients before reducing grants. SC16 implemented operator
sessions and authenticated attribution locally; deployment and transport/OS-boundary
acceptance remain outstanding.

See [SC15 verification and pending acceptance](sc15-schema-migrations.md).


SC16 supersedes the earlier direct password/note write grants. See [operator sessions](sc16-operator-sessions.md).
