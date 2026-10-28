# SC16 — authenticated operator sessions and attribution

Implemented locally on 22 October 2026. No configured database migration, account
grant change, executable packaging or VM deployment was performed for this item.

## Owner-approved policy

The owner selected “Keep all these actions available to testers.” Enabled Web-Tools
`user` testers and `admin` operators may test, assign, use the SC04 recorded-reason
override policy, remove serials and authorize maintenance. They may read reports and
save notes. Unknown roles and deleted accounts are denied. User administration is
not exposed by the desktop authorization endpoint. The new permissions do not add
an admin-only override/removal policy.

## Authentication and writes

The desktop no longer retrieves password hashes, verifies passwords locally or
writes user passwords directly. Web-Tools supplies enabled usernames and performs
login/reset using its password functions. Hashes never leave the server. Invalid
credentials and malformed stored hashes produce a safe failure. Login is limited to
10/minute and 15/hour; password changes are also rate limited. Desktop network and
reset work runs in workers; a Tk queue poll handles results without worker Tk calls.
The password field is cleared after a response. A successful forced reset returns to
sign-in rather than silently reusing an old token.

The deployment API key remains required and is insufficient by itself for reports,
removal, hashes, saved results, receipts and notes. Random operator bearer tokens
are scoped to a configured service and remain in memory/HTTP headers, never config,
logs or durable pending requests. Server storage contains only token and credential
digests, user ID, expiry and reset-only state. Default lifetime is 1800 seconds;
server SECOND_CHECK_SESSION_SECONDS is bounded to 60–3600. Each request checks the
current account, known role, deletion, password digest, reset flag and expiry.
Reset-only sessions cannot work. Own-password changes revoke all operator sessions.
Auth/session responses use no-store. A late failed request cannot clear a newer
client session.

Report assigned_by and final-review operator must match the principal. Assignment/
removal audit records use its ID/name. Receipts and idempotent replays belong to the
authenticated submitting user ID. Another tester may assign/remove stock in the
normal policy, but cannot claim another operator's pending receipt or replay their
request. Legacy receipts without authenticated ownership remain preserved and need
administrator reconciliation. Note writes now use an authenticated endpoint with
server audit identity; note reads still use the existing read-only order lookup.
Historical local override operators remain recorded client assertions; authentication
of the submitting actor does not independently verify that earlier history or the
physical hardware results.

## Lock and local actions

Operator > Lock / change operator preserves check drafts and clears the current
identity/token immediately. It requests server revocation with a bounded background
call. Offline/incomplete revocation retains the original token expiry. Lock refuses
active test/search/assignment/note/maintenance work and asks that dialogs are saved
or closed first. The locked screen can open a fresh sign-in process; old UI workers
and dialogs cannot adopt the next operator's identity. New sign-in restores drafts
through the existing review workflow and requires a current final-review actor.
Ordinary application closure also attempts revocation.

Official test queue entry/next-step and override saving check local session validity;
maintenance additionally checks server authorization before launching its process.
Server mutations enforce sessions independently of desktop controls. Actual Windows
maintenance remains local: the server authorizes/audits intent, while Windows owns
process privileges. SC21 retains TLS/transport and OS privilege work. The source
still supports configured HTTP endpoints for the existing lab; secure transport and
exact packaged behaviour remain release acceptance requirements.

## Migration and grants

Migration 0d9e0f1a2b3c follows the pending SC15 bridge and adds second_check_session
plus nullable actor_user_id on existing operation receipts. Existing receipts/data
are retained; new operations receive an authenticated actor. The migration is safe
to retry and refuses downgrade to avoid losing session/receipt attribution. Full
DB rollback uses a verified backup.

Deploy matching server code, stop legacy clients, verify a backup and apply the
pending migrations with separate administrator credentials. Verify db current,
first-run checks and actual sign-in/reset/assignment/removal/note behaviour in
isolation before distributing the new desktop. Old key-only clients are rejected.
Desktop contract 2 requires SELECT on eight operational/specification tables, no
user-table access, password UPDATE, note writes, assignment writes or DDL grants.
The configured desktop SQL account can therefore be read-only. No grants were
changed locally by this implementation.

## Verification and remaining acceptance

150 desktop tests pass, including nine new session/service/hidden-Tk checks. They
cover memory-only URL-scoped tokens, expiry, reset/invalid sessions, server login,
redacted network failures, 401 invalidation with generation protection, authenticated
note saves, unauthorized assignment before journaling, hardware queue gating,
responsive workers and lock/draft/new-process behaviour. Existing UI fixtures now
explicitly install a mock signed-in operator. A battery-capture fixture's clock was
made deterministic after exposing Windows sub-millisecond wall-clock differences;
production freshness rules remain unchanged.

49 isolated Flask tests pass: 33 transaction regressions, ten authentication checks
and six SC15 setup/migration checks. Coverage includes deployment-key-only rejection,
digested tokens, expiry/logout, deleted/unknown-role accounts, malformed hashes,
password-change invalidation, forced reset, real login rate limits, approved tester
permissions, forged attribution, receipt ownership, audited notes, retryable session
migration and legacy data preservation. Tests use disposable SQLite and mocked
external/hardware boundaries. Existing migration get_engine deprecation warnings
remain. No test uses the configured astro database.

Pending release acceptance: apply migrations with backup, actual restricted MySQL
grants, paired server/executable, clean VM login/reset/offline/expiry and two-operator
switching (including uncertain writes), TLS, maintenance UAC and physical bench work.
No claim of production or physical acceptance is made from the source tests.
