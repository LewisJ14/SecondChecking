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

## Update service

The GUI exposes **Tools > Check for App Updates**, which uses `src/update_service.py`. It compares the local `src/version.py` `__version__` against an HTTPS-hosted manifest (`APP_UPDATE_MANIFEST_URL`), and when a newer release appears it opens the provided download page for the user.

`update_service.py` ships with a default manifest location such as `https://github.com/your-org/SecondChecking/releases/latest/download/update.json`, but you should override it in production so it points to this repository’s GitHub release manifest:

```powershell
setx APP_UPDATE_MANIFEST_URL "https://github.com/<owner>/<repo>/releases/latest/download/update.json"
```

The manifest must look like this:

```json
{
  "version": "0.1.1",
  "download_url": "https://github.com/<owner>/<repo>/releases/download/v0.1.1/SecondChecking-0.1.1.exe",
  "release_page": "https://github.com/<owner>/<repo>/releases/tag/v0.1.1",
  "notes": "Release notes describing the update.",
  "metadata": {
    "signed": "true"
  }
}
```

`download_url` or `release_page` is opened automatically when users accept the update prompt.

### GitHub release automation

A new release is prepared by creating (or publishing) a GitHub release for the desired tag; `.github/workflows/release.yml` then runs on `release.published`, executes `compile.ps1`, renames `dist/main.exe` to `SecondChecking-<version>.exe`, uploads both the executable and the manifest as release assets, and writes the `update.json` manifest using the release notes as `notes`. The manifest that the app reads is exposed as `https://github.com/<owner>/<repo>/releases/latest/download/update.json`.

The workflow uses `src/version.py` to find the current version string, so bump `__version__` before publishing each release so that the manifest version is always strictly greater than the one embedded in deployed builds.

### Local release publish script

Run `publish-release.ps1` after you’ve updated `src/version.py` and committed a new tag (e.g., `git tag v0.1.2`). The script invokes `compile.ps1`, prepares `SecondChecking-<version>.exe`, writes an `update.json` manifest, and uses the GitHub CLI (`gh`) to create or update the `v<version>` release with both artifacts. Pass `-Notes "Release notes..."` to embed custom release notes, and use `-Force` if you need to recreate a release that already exists.  
Ensure `gh` is authenticated and available on `PATH` before running this helper.

### Cross-platform upload helper

If you prefer a Python-based helper that performs the same release upload without PowerShell, run `python scripts/upload_update.py` from the repository root. It exposes the same `--notes` and `--force` flags, and you can add `--build` to rerun `compile.ps1 -SkipInstall` before uploading. The script reads `src/version.py`, renames `dist/main.exe`, writes `update.json`, and calls `gh release create`/`edit` so the auto-update manifest stays in sync.
