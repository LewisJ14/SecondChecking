# SC02 exact serial identifiers

Implemented locally on 21 October 2026. No database migration is required.

The serial viewer now decodes each database identifier once, before storing
its rows. Text, UTF-8 bytes, byte arrays and memory views retain the exact
characters, including leading zeros. It does not convert an identifier to a
number or silently discard undecodable bytes. Missing, empty, numeric or
malformed values stop that result set from becoming selectable and show an
actionable error. A numeric database value cannot recover zeros already lost
upstream, so it is rejected rather than guessed.

Both View Spec and Remove use an exact identifier mapped to the Treeview item
ID. They never read an identifier back from display values, which Tk can
convert to integers. The mapping is rebuilt whenever a page is displayed.
Database rows have stable ordering, and a refresh after removal keeps the page
number within the remaining results.

SC01 already introduced the item mapping for server-owned removal; this work
finishes strict database decoding and verifies both actions across pagination.
It does not rewrite serials in existing records or change the server's serial
matching policy.

## Verification

`python -m unittest discover -s tests -v` passes all 31 desktop tests.
The new tests use real hidden Tk widgets and fake database/API boundaries.
They check View Spec query parameters, dialog identity and removal parameters
for `001234`, `000000`, `0`, mixed identifiers and very long numeric strings.
They also cover byte-valued identifiers, malformed bytes and changing pages
before an action. No production records are modified by these tests.

Python compilation and whitespace checks passed at initial verification.
The follow-up below records the later test build; deployment is still pending.

## Walkthrough follow-up on 21 October 2026

Selection-dependent actions, disabled loading/removal states and explicit
empty/error messages now protect the exact identifier mapping in the actual
viewer. Changing pages invalidates the old selection. Rejected removal keeps
the exact selected row and never writes assignment SQL locally. A recovered
receipt is labelled as historical rather than a current-state guarantee.

The expanded desktop suite passes 36 tests on Python 3.12 and 3.13. The 20
SC01/SC02 tests also passed as a frozen executable in the Windows VM, including
leading zeros, database bytes, pagination, invalid identifiers, empty/failed
lists, rejected/recovered removals and closing during background loading.
These tests use real hidden Tk widgets with mocked database/API boundaries.

A new main executable was built using Python 3.12.0 and PyInstaller 6.3.0.
The unreleased artifacts and hash manifest are in
`C:\Users\PCR\Documents\SecondChecking Review\sc01-sc02-build`.
They were not deployed or installed over the VM's older app. Full main-app
acceptance against the matching real Web-Tools service remains outstanding;
the earlier lab simulator cannot validate SC01's protocol.
