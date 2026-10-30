# SecondChecking

SecondChecking checks and assigns devices to **orders**. Trade job search,
assignment and note editing have been removed from the desktop app. The header
always offers Search Order; old `[app] mode = trade` settings are ignored.
Existing trade records and Web-Tools trade features are unaffected.

An unresolved request left by an older trade-enabled desktop is never resent.
The app can reconcile its existing server receipt; if the outcome is still
unknown, review it in Web-Tools before assigning that device to an order.
Do not delete a pending journal to bypass that review.

## Environment Variables

The application expects sensitive configuration to be provided via environment variables:

- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` – MySQL connection settings.
- `SECOND_CHECK_BASE_URL`, `SECOND_CHECK_KEY` – Web-Tools API URL and key. These override `[webtools] base_url` and `second_check_key` in `config.ini`. A valid key must be configured; no key is embedded in the application.
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

Web-Tools owns the shared database schema. See [the schema contract and rollout
instructions](docs/database.md). For a new empty database use the matching server's
`flask --app run.py schema init-empty`; for an existing versioned database, back up
and run `flask --app run.py db upgrade`. Minimum matching migration:
`0d9e0f1a2b3c`. The old `sql/001_create_order.sql` is historical reference and does
not provision or migrate the full current application.

Normal desktop connections perform read-only compatibility validation and block
incomplete/unreadable schemas. No desktop login/search performs DDL or schema repair.
To validate settings, connectivity and the desktop schema contract from source:

```powershell
.\venv312\Scripts\python.exe src/main.py --check-schema
```

This does not prove API authorization or all server schema constraints. The existing
`--check-config` command remains a configuration and `SELECT 1` probe only.

### Order number lookup format

Order references support both legacy and current formats:

- For `backmarket`, `remanufactured stock`, and `remanufactured-stock` platform rows, display numbers are `PC-####`.
- For all other platforms, display numbers are 5-digit values (`#####`).
- `external_id` lookups are still supported, including case-insensitive matching for `PC-####` references.
- Numeric fallback matching against `local_id` and `id` remains enabled for backward compatibility with older references.

## Update service

Update checks use system certificate trust plus the bundled public CA roots. Certificate and hostname verification stay enabled; no certificate store is changed. Startup shows checking, up-to-date, available, or failed status beside the version. **Tools > Check for App Updates** retries a failed check and displays its result.

The GUI exposes **Tools > Check for App Updates**. The updater compares the embedded version with the HTTPS release manifest, validates its repository/version/asset identity, and offers a newer release. Download and verification run in the background with progress and Cancel.

The default manifest is in the trusted `lewisj14/SecondChecking` repository. `APP_UPDATE_MANIFEST_URL` may select a release manifest within that repository; arbitrary origins are rejected:

```powershell
setx APP_UPDATE_MANIFEST_URL "https://github.com/lewisj14/SecondChecking/releases/latest/download/update.json"
```

The manifest must look like this:

```json
{
  "version": "0.1.1",
  "download_url": "https://github.com/lewisj14/SecondChecking/releases/download/v0.1.1/SecondChecking-0.1.1.exe",
  "release_page": "https://github.com/lewisj14/SecondChecking/releases/tag/v0.1.1",
  "notes": "Release notes describing the update.",
  "sha256": "<64 hexadecimal characters: SHA-256 of the final executable>",
  "size": 12345678
}
```

Automatic installation requires a packaged Windows client and the exact executable size/SHA-256 from the validated HTTPS release manifest. Only this repository's version-matching GitHub release assets are accepted. Paid signing is not required. The updater checks the downloaded file, the installed baseline and copied helper, staged version/importability and confirmed restart before completing replacement.

Publisher signing is optional. If `APP_UPDATE_SIGNER_SHA256` is explicitly configured with the SHA-256 of a trusted signing certificate's DER bytes, both the installed baseline and downloaded executable must have a valid Windows Authenticode signature from that certificate. A manifest `signer_sha256` must match that configured fingerprint; manifest metadata cannot establish publisher trust. A transaction cannot remove or change an existing publisher requirement. Sign the final artifact **before** calculating its digest/size when using this mode.

Builds through 0.1.48 contain the previous signing-only policy. Replace one of those builds manually with the corrected build once; that build can then install future matching releases through the app. Existing configuration/certificates stay beside the executable.

Without automatic-install prerequisites, accepting the prompt opens the trusted release page and leaves the app running. Automatic installation checks the candidate's embedded version/importability, preserves drafts, retains a verified previous executable, and uses a separate installer with a durable journal and atomic replacement. A failed replacement or unconfirmed restart triggers recovery of the previous copy. **Tools > Restore previous app version** uses that retained backup. Configuration and draft files are not replaced. See [SC18 recovery details and outstanding signed/VM acceptance](docs/sc18-update-validation-and-rollback.md).

### Verified builds and release preparation (SC19)

The shared pipeline is `scripts/release_package.py`. It never increments the version, moves a tag, renames an unidentified old executable, copies local credentials/logs, or removes an existing build directory. `main.spec` requires generated identity/version resources, so use the build entry points rather than invoking the spec directly.

For a local review build, including uncommitted changes:

```powershell
.\compile.ps1 -Python .\venv312\Scripts\python.exe -SkipInstall -Output 'C:\Builds\SecondChecking-review-unique'
```

Choose a **new directory outside the checkout** each time. Output includes `dist/main.exe`, embedded/sidecar `build-identity.json`, a Windows version resource and `build-record.json`. Review builds record their dirty state and individual input hashes, show a review/build identifier in the title, and cannot be published through the release tool. They retain the current version; this does not create a new release. No private configuration or logs are copied. Supply configuration separately as described above.

A release requires a clean checkout at an existing `v<major.minor.patch>` tag pointing to HEAD, with that exact version declared in `src/version.py`. Install pinned requirements in the selected Python environment first. The scripts verify dependency versions, record actual installed distribution versions, check source hashes before and after packaging, and read embedded identity plus the Windows file version from the executable without launching its elevated GUI.

```powershell
python scripts/release_package.py build --tag v0.1.37 --output C:\Builds\SecondChecking-0.1.37
python scripts/release_package.py prepare --tag v0.1.37 --output C:\Builds\SecondChecking-0.1.37 --notes-file C:\Builds\release-notes.txt
```

The example version is illustrative; no version was changed during SC19. Unsigned builds prepared by this pipeline include the size/hash needed for automatic installation by corrected clients. For optional publisher-pinned installation, sign the build's executable separately and pass its final path to `prepare --artifact <signed-exe>` with the independently configured `APP_UPDATE_SIGNER_SHA256`. The tool verifies the pinned Authenticode signature before accepting changed bytes, and hashes/copies the final artifact. Signing credentials and a production signing provider are not configured by these scripts.

Preparation writes `release/SecondChecking-<version>.exe`, `update.json`, `build-manifest.json` and `release-notes.txt`. It refuses stale source, mismatched embedded identity or an already-prepared output directory. Verify the manifest's final artifact size/hash and retain it with the release.

Publication is a separate explicit action:

```powershell
python scripts/release_package.py publish --tag v0.1.37 --output C:\Builds\SecondChecking-0.1.37
```

This revalidates source/artifact/manifest, verifies the remote tag's commit through GitHub, and creates a **draft** with `gh --verify-tag`. It refuses an existing release and never deletes or clobbers its assets. Review the draft and complete signed/VM/client-server acceptance before publishing it to users. The PowerShell wrapper supports `-Publish` and the Python compatibility wrapper supports `--publish`; both otherwise stop after preparation. `-SkipCompile` / skipping `--build` still requires a matching build record. The old force/version-bumping behaviour is removed.

The GitHub workflow runs tests in a separate job, checks out the exact tag, builds on Python 3.12, retains the prepared assets, and creates a draft for tag pushes or an explicitly requested manual upload. It has checked native-command exit codes and scoped release-write permission. It does not build in response to publishing a release, preventing that former ordering problem. See [SC19 implementation and remaining CI/VM acceptance](docs/sc19-release-identity.md).

### Assignment result review (SC04)

Review every check before assignment. Failed, incomplete, cancelled, unavailable,
error and manually overridden checks may proceed only with a recorded reason.
Wi-Fi overrides also require their own reason and retain operator/time and the
original result. Retesting supersedes the override without deleting its history.

Deploy the matching Web-Tools result-policy version 1 server and desktop together;
older clients cannot submit new order reports to the updated server. Saved results
now load through the authenticated API, including Wi-Fi and override provenance.
Legacy records with unknown history are labelled accordingly. No additional DB
migration is needed beyond the existing SC01 migration. See
[SC04 implementation and verification](docs/sc04-result-review.md).


### Local check drafts (SC05)

Unsaved checks are kept locally by resolved order and exact device serial, including
repeat searches and restart. The header identifies the loaded order/device and
local draft status. Changing the reference removes old assignment/view controls
until a lookup resolves. If the saved server report has changed, choose Restore,
Discard or Cancel before replacing a draft. Local drafts are not uploaded until
assignment succeeds. See [SC05 session protection](docs/sc05-check-session-protection.md).


### Qualified local MDM evidence (SC06)

The registry check reports local Autopilot indicators, absent indicators, errors
or unknown evidence. It always states that tenant registration/enrolment is not
verified. Source, capture time and read errors are retained in the saved report;
assignment takes a fresh reading. Deploy the matching server advertising
`mdm_evidence_version: 1`. No additional migration is required. See
[SC06 evidence meaning and acceptance](docs/sc06-local-mdm-evidence.md).


### Physical storage configuration (SC07)

Storage comparison requires the specified drive count, per-drive capacity and any
explicit media/bus type. One 1TB drive and two 512GB drives are different layouts.
Equal-size and unpartitioned devices are counted separately. USB/removable media
are excluded but recorded; missing evidence and ambiguous SKU mappings require
review. Inventory and the recorded review are saved with the report. See
[SC07 storage policy and acceptance](docs/sc07-storage-configuration.md).


### Fresh device measurements (SC08)

Use Refresh Device to capture measurements in the background without losing an
order's unsaved checks. Capture time, age and source appear in the header; memory
and disk caches expire. Search and assignment take fresh snapshots. Battery health
and live charge are separate, with absent/unreadable results identified explicitly.
The live charge bar falls back to Windows' overall battery reading when the
per-battery reading is unavailable. Failed refreshes retain a clearly labelled
last reading while retrying; stale charging status and power rates are not shown.
The current Windows display mode does not establish native panel capability, and
Windows edition does not establish activation. See
[SC08 freshness and acceptance](docs/sc08-measurement-freshness.md).

### Independent audio checks (SC09)

Speaker and microphone have separate tests and results. Choose the intended
devices, play the speaker tones or record/replay a spoken phrase, then confirm
what you heard. Noise levels never auto-pass either test. Playback starts at 15%
digital amplitude; Windows volume, mute, input gain and default devices stay
unchanged. Cancel, Unavailable and test errors remain distinct from Fail. See
[SC09 workflow, verification and pending physical checks](docs/sc09-independent-audio.md).

### Hardware coverage (SC10)

USB automatically records each fresh removable-drive insertion as the operator
moves a test drive between ports. No per-port confirmation or port count is
required; Finish confirms that every physical port was checked.
Keyboard results include observed/missing keys
and a saved explanation for manually passing incomplete capture. Display screens
show inspection instructions. Wi-Fi detects enabled WLAN adapters only and does
not certify connectivity or speed. Missing/unreadable cameras and API errors are
separate from an operator Fail. Coverage is preserved in drafts and uploaded/read
back by the matching Web-Tools server, without a migration. See
[SC10 scope and physical acceptance matrix](docs/sc10-hardware-coverage.md).

### Cancellable checks (SC11)

Run All shows the current step, has a persistent Cancel control and finishes with
an outcome summary. Cancelling a test stops the remaining sequence while keeping
checks already completed and results for checks not started. Device I/O runs in
bounded worker processes; late callbacks cannot overwrite a newer attempt. Closing
the panel cleans up owned work. Note saving also runs in the background; closing
the editor does not undo a submitted database write. See
[SC11 behaviour, timeouts and pending packaged acceptance](docs/sc11-test-lifecycle.md).

### Layout and scrolling (SC12)

Long SKU titles, identity and actions use separate rows; comparison values wrap
with the window. Footer details/notes have a bounded scroll area and Show/Hide
control. Hardware descriptions wrap below their controls, and the keyboard diagram
scrolls without shrinking its labels. Wheel events over child controls stay scoped
to their surface, and keyboard focus brings off-screen actions into view. See
[SC12 geometry evidence and pending native DPI acceptance](docs/sc12-responsive-layout.md).

### Saved reports and accurate states (SC13)

View Report loads saved checks, coverage, overrides, specifications, batteries,
operator/time, assignment and available receipt from the matching Web-Tools server.
Legacy data, absent assignments and failed requests remain distinct, with Reload
and Close controls. A fresh hardware session no longer implies a database failure,
and empty updater output no longer means up to date. See
[SC13 readback contract and pending packaged acceptance](docs/sc13-saved-reports-and-states.md).


### Fresh configuration and connection check (SC14)

Copy `config.example.ini` to `config.ini` and supply private deployment values,
or set all six variables: `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`,
`SECOND_CHECK_BASE_URL` and `SECOND_CHECK_KEY`. No API host/key is embedded.
Never commit the populated file. Placeholder and blank credentials are rejected.

Configuration is read from the repository root for source runs and beside the
executable for packaged runs, independent of the working directory. Set
`SECOND_CHECK_CONFIG` to an absolute file path to select another file; an explicit
missing/unreadable file is an error. An absent default file is allowed for
an environment-only installation. Environment variables override individual INI
fields, including empty values (which fail validation rather than reviving old
credentials). Passwords are literal: `%` does not require escaping.

The login panel loads enabled operators and authenticates through Web-Tools;
missing API settings have a Retry action. Database settings are checked when used
and by the first-run commands. Correct the file and select Retry; when
changing inherited environment variables, restart the app. Database failures
have generic messages without driver text or credential values. API URLs must
use HTTP/HTTPS without embedded credentials, query strings or fragments.
Optional search keywords may be omitted; unmatched SKU fields remain Unknown.
Hardware settings use the same file and retain defaults when absent.

For a read-only first-run check from source, run:

```powershell
.\venv312\Scripts\python.exe src/main.py --check-config
```

Exit 0 confirms local configuration validation and a bounded MySQL `SELECT 1`.
Exit 1 reports missing/invalid field names or a generic connection failure.
This command does not repair schema, launch Tk, collect hardware or validate API
connectivity/authorization. Normal login also checks the read-only schema contract before loading users;
SC15 removed runtime schema changes.
The frozen windowed executable's stdout may not be visible; use its login Retry
feedback. A newly packaged executable still needs clean-VM acceptance.


### Operator sessions and permissions (SC16)

Deploy the matching Web-Tools source and apply migrations through `0d9e0f1a2b3c`
before deploying this desktop. The deployment API key alone cannot submit reports,
remove serials, retrieve receipts or save notes. Sign-in and required password
changes are handled by Web-Tools; password hashes are never read by this desktop.

Per the owner decision, enabled `user` testers and `admin` operators may test,
assign, record reasoned overrides, remove serials and use machine-maintenance
commands. Unknown/deleted accounts and expired/reset-only sessions cannot work.
Tokens are random, kept only in memory, scoped to the configured server and expire
after 30 minutes by default. Web-Tools checks current account/password state on
requests. `SECOND_CHECK_SESSION_SECONDS` is a server-only setting (60–3600 seconds).

Use **Operator > Lock / change operator** to preserve check drafts, clear the local
session and request server revocation. Sign in opens a fresh process so old callbacks
cannot adopt a new identity. Finish active tests/search/assignment/note/maintenance
work and save or close dialogs first. Server logout is attempted with a bounded
request; offline tokens retain their original expiry. Sign in again after expiry.
Historical override operators remain recorded client evidence; the submitting actor
and assignment/removal/note audits are authenticated on the server.

Database access is now read-only: SELECT on the eight tables in desktop contract 2;
no SELECT on user/password hashes and no INSERT/UPDATE/DELETE/DDL grants are required.
Do not use migration credentials in the desktop config. Pending operations belong
to their original operator; another operator cannot replay or claim those receipts.
Legacy receipts without authenticated ownership need administrator reconciliation.

See [SC16 scope, testing and release acceptance](docs/sc16-operator-sessions.md).


### Windowed helper results (SC17) and maintenance (SC21)

GUI helper calls use versioned private JSON files with request UUIDs and bounded
owned child processes. Updater/MDM results do not depend on stdout from main.exe.
Source-only/manual --check-updates and --refresh-mdm console flags remain available.
Missing/error/mismatched output cannot mean up-to-date or device-clear.

main.spec embeds src/Script.ps1. SC21 replaces inherited administrator execution
with explicit confirmation and a scoped UAC launch. The normal GUI uses asInvoker.
Windows Update requires an administrator-provisioned machine module, installs no
providers/modules automatically, and requests no automatic reboot. Check Windows
Update history afterward. Routine checks perform no certificate-store maintenance.

See [SC17 implementation and acceptance limits](docs/sc17-packaged-helpers.md).
The separate frozen probe is a test artifact, not a released app or completed VM/
physical Windows Update test. SC18 implements update validation/recovery locally;
Later source changes have their own evidence; exact release acceptance remains.

### Source tracking and service boundaries (SC20)

Generated builds, local config/logs/preferences, device exports, update journals and old runtime/source archives are ignored and untracked. Existing local copies were preserved. Only canonical public resources under `src/assets` are source inputs; root `assets` copies are runtime material. `runtime-files.json` is deliberately empty. Configuration and credentials must be supplied privately from `config.example.ini` or environment variables.

Run `python scripts/check_source_policy.py` before review/commit. It checks the Git index for classified private/generated artifacts and missing application/build inputs; the release workflow and strict release builder enforce the same policy. New public binaries/resources require an explicit allowlist and packaging change. It does not scan secret contents or erase historical commits. Avoid force-adding ignored runtime files.

Authentication and read-only database access use `services.configuration` directly; paths/logging use `services.runtime`. Compatibility helpers remain for existing UI/hardware callers. `db.database` imports no GUI on headless paths; interactive callers retain their explicit error dialogs. Read queries remain on the desktop and all report/assignment/removal/note writes stay server-owned. See [SC20 scope, preservation proof and remaining acceptance](docs/sc20-source-boundaries.md).

### Verified connections and scoped maintenance (SC21)

Service connections require HTTPS and certificate/hostname verification. Set `SECOND_CHECK_CA_BUNDLE` to an absolute private-CA bundle path when needed. Credentialled requests refuse redirects: configure the final HTTPS service URL. SQL connections require `VERIFY_IDENTITY`; set `DB_SSL_CA` (or `[database] ssl_ca`) for a private CA. For a portable deployment, use `ssl_ca = certificates/mysql-ca.pem` and keep the `certificates` folder beside the EXE. Relative database CA paths resolve from the EXE directory (repository root for source runs), regardless of the launch working directory or an explicit configuration-file location. Absolute CA paths remain supported. There is no TLS downgrade on failure.

Only isolated loopback tests may opt into plaintext: `SECOND_CHECK_ALLOW_HTTP_LOOPBACK=1` for HTTP and `DB_ALLOW_INSECURE_LOOPBACK=1` for SQL, using literal loopback IP addresses. These flags do not permit LAN hosts or DNS aliases. No private configuration or persistent environment variables were changed. Reconcile uncertain receipts before changing a service URL.

The GUI runs with the invoking user's privileges. Windows Update and post-assignment Sysprep require explicit confirmation, a fresh service permission check and separate Windows administrator approval. Tester access is retained. No service credentials are passed to elevated PowerShell. An administrator must provision PSWindowsUpdate under Program Files; it is no longer installed automatically. Sysprep does not kill another running Sysprep. A timeout means unconfirmed, not cancelled: inspect Windows before retrying.

Unavailable standard-user hash capture is shown in the final recorded-reason review. Checks do not elevate automatically. Protected app directories may require a manual verified update. Complete real TLS, UAC/maintenance, physical evidence and signed-update VM acceptance before deployment. See [SC21 details and acceptance limits](docs/sc21-transport-privileges.md).

## Bug reports

Error dialogs offer **Upload bug report**. Tools and hardware checks also
provide the same action for inline errors; the sign-in form has no report button.
The operator sees a frozen preview
before sending anything to the configured HTTPS Web-Tools service. Upload is
manual, runs in a background thread and keeps the same reference when retried.

Reports contain the app/build and Windows/Python versions, code locations,
exception types, numeric error codes, and up to 60 structured diagnostic events
from the preceding 30 minutes. Reports also include bounded, redacted text files
selected for the current error: app diagnostics, Sysprep Panther logs, recent
Windows Update events, or allowlisted app-update state. No configuration files,
arbitrary file paths, screenshots or audio are collected. Credentials, local
account/machine names, paths and common identifiers are redacted before preview
and again by Astro. Only fixed filenames are accepted, at most 48 KiB each and
192 KiB for the complete report. Missing/unreadable files and truncated extracts
are identified in the preview. An earlier Sysprep error does not cause its logs
to be included with a later unrelated error.
`diagnostics.jsonl` is bounded/rotated at 1 MiB alongside `logs.txt`; the old text
log is kept locally and is never uploaded. A memory fallback retains diagnostics
when the app folder is not writable. GUI callback/background errors are captured.
Maintenance records approval/start/exit/timeout stages. File collection runs in
the background, and the preview remains cancellable while it is prepared.

Deploy the matching Web-Tools bug-report migration/API before distributing this
client. This attachment extension uses the existing JSON column and needs no new
migration. The client checks the server's attachment capability before sending
files and requires an attachment-count receipt. Astro administrators can preview
or download the redacted text files from each report. The API uses the existing
deployment key even before operator sign-in;
valid sessions attribute the report to its operator, but neither authentication
header is included in evidence. Missing service/migration, TLS/network failure
and throttling show a retryable upload result and never claim success. Hard
process termination cannot display an error button; use Tools on the next launch
to report the retained diagnostics.
