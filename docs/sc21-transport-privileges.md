# SC21 transport and maintenance privileges

Implemented locally on 22 October 2026. No private deployment settings, server certificates, trust stores, schemas or operator permissions were changed. No Windows Update, Sysprep, shutdown, module installation or actual UAC elevation ran during verification.

## Transport

`services.transport` now sends authentication/session calls, assignment/receipt requests, saved-report reads and hardware-hash uploads. It requires HTTPS, certificate/hostname verification and unambiguous URLs without embedded credentials. It disables redirects for every method, including POST, and rejects redirect responses. Configure the final HTTPS service address: API/session headers and request bodies must not follow a reverse-proxy redirect.

`SECOND_CHECK_CA_BUNDLE` optionally selects an existing absolute CA bundle path for a private service CA. Otherwise Requests uses its normal verified trust configuration. Callers cannot disable verification or enable redirects. Transport errors use safe diagnostics, and hash-upload failures no longer log server response bodies. Pending operation identities and uncertain-outcome reconciliation remain unchanged.

HTTP is available only with `SECOND_CHECK_ALLOW_HTTP_LOOPBACK=1` and a literal loopback IP such as `127.0.0.1` or `::1`. DNS names, including `localhost`, do not qualify. This exception is for isolated simulator tests and does not permit LAN HTTP. Credentials on that local connection remain plaintext. No override was enabled persistently.

Both normal SQL connections and read-only configuration/schema probes require `ssl_mode=VERIFY_IDENTITY`, with local-infile disabled. Supply a trusted CA through `DB_SSL_CA` or `[database] ssl_ca` when needed; the path must be absolute and exist. Failed verification or an unsupported driver does not trigger a weaker retry. `DB_ALLOW_INSECURE_LOOPBACK=1` explicitly permits plaintext SQL only to literal loopback addresses, never remote hosts or DNS aliases.

The pinned mysqlclient 2.2.4 source maps verification to native MySQL/MariaDB TLS enforcement and server-certificate checks. Actual deployed-driver/server certificate and hostname behaviour remains an acceptance requirement: no production SQL TLS connection was opened during this task.

## Maintenance scope

The main manifest and PyInstaller spec now use `asInvoker`. Normal GUI operations run with the invoking user's token. The approved tester permission to initiate maintenance remains; Windows administrator approval is a separate OS boundary, not a new restriction on the application tester role.

Windows Update refuses an active bench/dialog and asks for confirmation before starting a worker. The worker reauthorizes the current operator through the service, then requests Windows elevation for the fixed action. Post-assignment Sysprep has its own shutdown explanation, confirmation, fresh authorization and background wait. Assignment success alone does not initiate it. Its dialog cannot be dismissed while the action is pending.

The elevation helper accepts only `windows-update` and `sysprep`, not arbitrary commands or paths. It launches system PowerShell without profiles and passes no service key, session token or database password. A global mutex prevents concurrent maintenance and handles abandoned ownership. Denied approval, failed startup and nonzero exit do not claim success. A timeout is explicitly **unconfirmed**: the elevated operation may still be running and is not forcibly killed mid-update; its mutex remains until it exits.

Windows Update uses an administrator-provisioned PSWindowsUpdate module under Program Files, with module search paths limited to machine/system locations. It no longer downloads providers or modules silently and requests no automatic reboot. Provision and review that module before deployment, and inspect Windows Update history after running it; script exit alone does not prove every update installed.

Sysprep retains `/oobe /shutdown`. It adds no `/generalize`, policy change or global process kill. An already-running Sysprep stops the new action. Routine MDM evidence refresh remains read-only and does not launch maintenance or policy refresh.

Some evidence, particularly Autopilot hash capture, may be unavailable with standard-user permissions. Hash capture now precedes final assignment review: missing capture is shown in its warnings and covered by the recorded-reason decision. It does not silently imply enrolment or verified tenant status, and does not automatically elevate. Physical acceptance must check battery, activation, MDM and hash access with the final standard-user build.

This narrows application operations; it is not a privileged service accepting untrusted requests or a complete defence against a modified local application. Trusted app signing/distribution and administrator-owned module provisioning remain release requirements. Protected installation directories may require a manual verified application update from a standard-user session.

## Verification

All **239 desktop tests** passed, including 18 new transport/privilege cases and a missing-hash review regression. Three cases use a real temporary loopback HTTPS server and ephemeral file-based certificates: an explicitly supplied CA succeeds; untrusted and wrong-host certificates fail; and credentialled redirects are refused. Nothing is installed in Windows trust. SQL tests verify both connection entry points' parameters, not a live deployed TLS handshake.

Elevation tests mock ShellExecuteEx/process handles and cover fixed actions, fresh permission checks, cancelled approval, timeout, success/failure exit, handle cleanup, system PowerShell arguments and GUI decline. Both fixed scripts were parsed without execution. Existing HTTP fixtures were changed to HTTPS fixtures while preserving their session/assignment assertions. Compilation, source policy and workflow lint also pass; counts and hashes are in [the evidence record](sc21-transport-evidence.json).

A full windowed review executable was built. Its actual PE manifest is `asInvoker`; the public CA bundle is present and private runtime config/log/key files are absent. With a verified non-elevated host token it successfully ran the real `--build-info` and packaged import/asset health entries, with matching identity/version/nonce. These are frozen-process checks, not GUI login or OS-maintenance acceptance. The unsigned 0.1.36 review build has a separate UUID, cannot pass publication checks, and was not installed in the VM. Earlier executable/evidence records retain their original source snapshots.

## Before deployment

27 October usability follow-up: [maintenance prerequisite preflight and messages](sc21-maintenance-preflight-fix.md)
are implemented and VM-tested. A missing module now explains its prerequisite
before UAC; cancellation is distinct from startup failure. All 275 tests pass;
the elevated guards and remaining successful-maintenance acceptance are preserved.

27 October follow-up: [SC22 maintenance guard checks](sc22-maintenance-acceptance.md)
now exercise actual app decline, UAC refusal and an approved nonzero exit in the
offline/module-missing VM. The approved attempt preserves draft contents and
configuration and leaves no maintenance process/mutex. Successful installation,
alternate-admin, elevated timeout/contention and Sysprep remain open. Module
preflight and clearer cancellation messaging are recorded usability follow-ups.

26 October follow-up: the [SC22 packaged TLS matrix](sc22-tls-acceptance.md)
now verifies the actual native driver's trusted, wrong-host, untrusted and expired
certificate behaviour, plus full GUI service/readback over private-CA TLS. The
earlier limits above describe the original implementation checkpoint. Production
configuration, signed release and real maintenance acceptance remain outstanding.

1. Configure the real service's final HTTPS URL, trust chain/hostname, SQL TLS identity and read-only account. Existing LAN HTTP/plaintext SQL deployments will fail these defaults until prepared. Reconcile uncertain receipts before changing the service URL, and preserve journals/drafts.
2. Review/commit the staged source, run the exact tagged hosted workflow with signing, and test login, reset, expiry, writes/readback and pending retries against the matching service/schema. Exercise valid and invalid CA/hostname cases on the actual native SQL driver.
3. Test UAC approval, denial and alternate-admin credentials, module provisioning/history, mutex behaviour, timeout reporting and post-receipt Sysprep on a disposable machine. These actions have not been run on this host.
4. Complete standard-user physical evidence, signed upgrade/rollback and independent VM export/import acceptance under SC22.

SC21 introduces no migration or service role-policy change. SC22 repeatable testing and portable baseline is next.

Reference contracts: [Requests TLS verification](https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification), [mysqlclient 2.2.4 native SSL mapping](https://github.com/PyMySQL/mysqlclient/blob/v2.2.4/src/MySQLdb/_mysql.c), and [Windows ShellExecuteEx behaviour](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecuteexw).
