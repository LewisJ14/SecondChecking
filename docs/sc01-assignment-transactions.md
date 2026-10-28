# SC01 server owned assignment transactions

Implemented locally on 21 October 2026 across SecondChecking and Web-Tools.
This change is not a deployed release.

## Behaviour

- Order assignment is saved only by the Web-Tools endpoints. SC01 initially
  also moved trade assignment to the server; SC03 later removed the desktop
  trade workflow entirely. The desktop does not delete conflicting rows directly.
- Remove Serial calls `/api/stock_units/unassign`. The server removes the
  selected order link and releases its active reservations in one transaction.
  A stale list cannot remove a device that has moved to another order or job.
- Reassignment checks both order and trade links and reservations on the
  server. A conflict returns the current owners and a confirmation token. The
  token is valid only while that state remains unchanged. The desktop asks
  before submitting it; cancelling leaves the assignment untouched.
- Historical check reports and reservation transitions remain available.
  Assignment and removal actions also write an audit entry.
- Each mutation has a UUID operation ID. Its result is committed in the same
  transaction as the records it changes. Retrying that ID returns the original
  receipt without applying the change again, even if the device has since moved.
- The desktop stores an uncertain request in
  `%LOCALAPPDATA%\SecondChecking\pending-operations`. It contains the pending
  report and operation ID, including any device evidence, but no API key.
  Confirmation deletes the pending JSON. Thread and process locks prevent
  concurrent desktop instances from replacing each other's pending request.
- On retry the desktop queries the receipt first, or resends the exact request
  with its existing ID. A different new change must wait until the previous
  one is reconciled. A recovered historical receipt is labelled in the result
  dialog; it does not prove that another operator has not subsequently moved
  the device.
- Serial viewer actions use an exact string mapping rather than reading a
  serial back from numeric-converting Treeview display values. This is needed
  to send the correct identity to the removal API and also addresses that part
  of SC02.

## Rollout order

1. Stop legacy SecondChecking clients during the coordinated rollout. Old
   clients can still contain direct SQL writes outside the new API protocol.
2. Back up the Web-Tools database and deploy the matching server changes.
   Apply its Alembic migration with the normal configured environment:

   ```powershell
   flask --app run.py db upgrade
   ```

   The new head `0b7c8d9e0f1a` follows `0a6b7c8d9e0f` and adds
   `second_check_operation` and `second_check_device_lock`. Request handlers
   do not create or alter tables.
3. Check the authenticated capabilities endpoint returns
   `transactional_assignments: 1`. The updated desktop refuses to send a
   mutation to an older server.
4. Build and distribute the matching desktop executable. Check order assignment,
   removal and reassignment against the staging server, including a device
   currently owned by an existing Web-Tools trade job.
5. Confirm that API receipts, report history and reservation state agree before
   reopening normal bench use. Do not delete pending requests to bypass an
   unresolved timeout; restore connectivity and let the app reconcile them.

The capability endpoint is `/api/stock_units/second-check-capabilities`.
Receipts are read from `/api/stock_units/second-check-operations/<operation_id>`.
Both require the existing SecondChecking API key. Keys remain configured through
the environment or private configuration.

## Verification

Run desktop checks with `python -m unittest discover -s tests -v`.
The server tests are in Web-Tools `tests/test_second_check_transactions.py` and
exercise the actual Flask routes and database models. They cover replay,
reassignment in both directions, stale confirmation, stale removal, commit
rollback, concurrent requests, optional MDM trigger failure and migration
upgrade/downgrade. A cross-checkout test uses this desktop transport against
those real endpoints and loses the first response after the server commits.

The default server test database is temporary SQLite. The suite can also use
the dedicated disposable MariaDB database on loopback port 33981 via
`SECOND_CHECK_TEST_MYSQL_URL`. It refuses other MySQL hosts, ports or database
names; the permitted database name is `second_check_sc01`. Never point this
suite at production: fixtures create and drop the test schema.

Local verification on 21 October 2026 passed 25 desktop tests, all 19
transaction tests against disposable MariaDB 11.4.12, and 29 related
Web-Tools regression tests. SQLite route checks and migration checks also
passed. Python compilation passed in both repositories. At that initial
verification the updated client had not been packaged or deployed, and no
production migration had been run. Later migration and build progress is
recorded below.

Follow-up: the migration was applied to the configured local `astro` database
on 21 October 2026 after a verified full backup. Revision `0b7c8d9e0f1a`, both
new tables, their keys and the Web-Tools schema preflight were verified. The
apps were not restarted or redeployed as part of that database operation.

SC01 did not complete SC04's test acceptance policy or SC16's operator
authentication redesign. The original SC03 trade field contract was superseded
by desktop trade removal. Saved order report readback remains under SC13.

## Walkthrough follow-up on 21 October 2026

The serial viewer now disables Remove and View Spec until an exact mapped
identifier is selected, and disables both during loading/removal. Empty and
failed lists have explicit messages. A failed load shows Unavailable rather
than leaving the loading indicator running. Pagination resets the selection
and disables navigation at its boundaries.

Recovered removal receipts are explicitly labelled as historical confirmations;
the list refreshes to obtain the current assignment. A rejected removal keeps
the row available for review, displays any operation ID, and performs no local
SQL mutation. Viewer workers return results through a queue processed by the
Tk thread, so closing the window during a load does not leave a worker calling
destroyed Tk controls.

All 36 desktop tests pass on Python 3.12 and 3.13. An isolated frozen executable
containing the 20 SC01/SC02 transport and real-Tk regression tests passed inside
the Windows VM. Its DB and HTTP boundaries are mocked: this proves packaged
regression behavior, not the real deployed server integration. The 19 actual
Flask transaction tests also passed with temporary SQLite and a freshly
initialized disposable MariaDB 11.4.12 database on loopback port 33981. The
disposable server was stopped after verification; no additional migration was
applied to `astro` during this follow-up.

An updated app test executable and source/artifact SHA256 manifest are staged
at `C:\Users\PCR\Documents\SecondChecking Review\sc01-sc02-build`.
It still displays 0.1.36 and is distinguished by the manifest, not a new public
release number. No credentials/configuration were copied into the build.
The VM's existing app and simulator were preserved. Pair this candidate with
the matching real Web-Tools test service before end-to-end acceptance and
coordinated rollout; the old simulator lacks SC01 capabilities and receipts.
