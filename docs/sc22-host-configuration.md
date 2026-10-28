# SC22 host configuration and verified MySQL TLS — 27 October 2026

**Completed after explicit approval:** the replacement server certificate/key
are installed and the existing DBA connection successfully ran
`ALTER INSTANCE RELOAD TLS`. Fresh native-driver identity verification and
encrypted `SELECT 1` pass. The actual packaged executable's identity,
configuration and schema checks all exit 0. Both dev and production login pages
remain HTTP 200 over verified HTTPS, and the operator-list API succeeds.
The deployment decision and earlier prepared-state notes follow for provenance.

The current build remains `73ce3899-7694-4e1b-8217-46d41f87cd5e` (0.1.36).
Its configuration format is unchanged. The briefly proposed long-form URL alias
was removed at the owner's direction; the loader/tests match this tested build.

## Completed desktop/API configuration

A private `config.ini` is now beside the executable at
`C:\Users\PCR\Documents\SecondChecking Review\sc22-real-update-readiness-2026-10-27\candidate\dist`.
Existing database and optional settings were preserved. Its `[webtools] base_url`
is `https://dev.astro-portal.co.uk`, and the existing API key remains private.
The obsolete `second_check_base_url` spelling is absent. Neither private config
in the repository was modified, and no credentials are included in this document.

The existing Cloudflare tunnel maps that hostname to local port 5001. The public
certificate validates normally, and a read-only operator-list request with the
configured key returns success (11 operator choices). No proxy/tunnel change,
HTTP exception, certificate-store change or server restart was needed. The
production hostname routes to port 5002 and was not substituted for dev.

## Separate database prerequisite

The MySQL 9.2 server advertises TLS, but the native desktop driver's identity
check returns error 2026. Its automatically generated server certificate has
no usable server hostname/IP identity. A CA path alone cannot fix that mismatch.
The application retains `VERIFY_IDENTITY`; verification was not disabled.

Prepared outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-host-configuration-2026-10-27`:

- A replacement server certificate signed by the existing MySQL CA, with SANs
  for `192.168.1.188`, `127.0.0.1` and `localhost`. All three identities validate
  using OpenSSL. It has a new server key; private material remains outside Git
  and is not copied beside the client executable.
- A fingerprint manifest, guarded staging/rollback helper, and a native-driver
  `SELECT 1`/encrypted-session verifier. The helpers compile. Applying requires
  an explicit live-server approval switch.
- A read-only preflight confirmed the original CA/exact server certificate and
  default certificate paths. Its administrative bootstrap verifies the CA and
  pins the exact local server leaf before credentials can be sent. This does not
  change the desktop's hostname/IP verification policy.

The desktop database account has privileges on the application schema but no
server-level CONNECTION_ADMIN privilege. The existing connected DBA tool does
have that privilege and identifies the same port/data directory. No new account,
password sharing or privilege grant is required.

## Approved rollout procedure

1. Recheck the original files and prepared fingerprints. Back up the original
   server certificate/key and current client config outside Git.
2. Atomically replace only the server certificate and key at their validated
   current paths. The existing CA remains unchanged.
3. Through the existing DBA connection, execute `ALTER INSTANCE RELOAD TLS`
   using its default rollback-on-error behaviour. No restart or change to
   `require_secure_transport` is planned.
4. Establish a fresh connection with the actual desktop driver using
   `VERIFY_IDENTITY`, then run only `SELECT 1` and an encrypted-session status
   read. Restore originals and reload the original context if verification fails.
5. Copy only the public CA certificate beside the client and add its absolute
   `ssl_ca` path to the private INI. Check the packaged configuration/schema
   read-only; report any separate migration prerequisite without applying one.

**Current status:** HTTPS/API and MySQL identity configuration are complete.
The shared server certificate/key were replaced with the approved prepared pair;
the CA is unchanged. Original certificate/key and client INI backups were
verified. Windows initially denied replacement (error 5) while originals remained
unchanged. The user approved a fresh administrator PowerShell prompt on the host
PC; staging then succeeded. The connected DBA tool reloaded TLS with its default
rollback-on-error behaviour, without restarting MySQL (process PID remains 4724).
No privilege grant, schema migration or table mutation was performed.

Only the public CA was copied to the client's `dist/certificates/mysql-ca.pem`,
and its absolute path was added as `[database] ssl_ca` in the private INI. The
private database credentials and other settings were preserved. No server key or
CA private key was included in the client folder, executable or repository. The
application still uses native `VERIFY_IDENTITY`; no remote plaintext exception
or Windows trust-store change was introduced.

The three real packaged checks completed in about 3–4 seconds each with exit 0:
`--build-info`, `--check-config`, `--check-schema`. The separate authenticated
operator-list GET succeeds with 11 choices. The user can now select **Retry** in
the existing sign-in window. No host mouse/keyboard input or real operator login,
assignment, report save or removal was automated.

Public evidence is in the external preparation directory: `verification.json`,
`stage-state.json`, `packaged-host-checks.json`, `services-after-tls.json` and the
packaged identity. Private server material/backups stay outside Git. No new EXE
was required; all recorded build inputs still match the current tested artifact.

References: MySQL documents the
[automatic-certificate identity limitation](https://dev.mysql.com/doc/refman/9.7/en/using-encrypted-connections.html)
and [TLS reload privilege/rollback behaviour](https://dev.mysql.com/doc/refman/9.7/en/alter-instance.html).
