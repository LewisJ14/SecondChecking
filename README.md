# SecondChecking

## Environment Variables

The application expects sensitive configuration to be provided via environment variables:

- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` – MySQL connection settings.
- `WC_URL` – WooCommerce API base URL.
- `WC_CONSUMER_KEY` and `WC_CONSUMER_SECRET` – WooCommerce API credentials.
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

Detailed table layouts, including the consolidated `orders` table and the
`order_serials` table that stores hardware test results and captured device
specifications, are documented in [`docs/database.md`](docs/database.md). The
companion script [`sql/001_create_orders.sql`](sql/001_create_orders.sql)
contains the MySQL statements needed to provision the schema.

