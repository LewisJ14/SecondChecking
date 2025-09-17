# SecondChecking

## Environment Variables

The application expects sensitive configuration to be provided via environment variables:

- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` – MySQL connection settings.
- `BATTERYINFOVIEW_SHA256` – expected SHA256 hash of the BatteryInfoView ZIP.

## One-click build script

To package the application with PyInstaller, run the included PowerShell script from the
repository root:

```powershell
./compile.ps1
```

The script installs the required dependencies and then executes PyInstaller using the existing
`main.spec` configuration. To skip reinstalling dependencies (for example, when running inside a
pre-configured virtual environment) pass the `-SkipInstall` switch:

```powershell
./compile.ps1 -SkipInstall
```

## Database schema

Detailed table layouts, including the consolidated `order` table and the
`order_serials` table that stores hardware test results and captured device
specifications, are documented in [`docs/database.md`](docs/database.md). The
companion script [`sql/001_create_order.sql`](sql/001_create_order.sql)
contains the MySQL statements needed to provision the schema. Apply it either
from inside the MySQL client (`SOURCE sql/001_create_order.sql;`) or directly
from a shell:

```bash
MYSQL_PWD="${DB_PASSWORD}" mysql -h "$DB_HOST" -u "$DB_USER" "$DB_NAME" < sql/001_create_order.sql
```

