# SC22 update readiness and signature guards — 27 October 2026

Later follow-up: the [signed VM matrix](sc22-signed-update-acceptance.md) passed
eight real signed scenarios plus Tools rollback. The approved guest signer's
trust and private key were removed after tests. Unsigned-only statements below describe the
earlier readiness checkpoint.

The update/release group advanced but remains open. No publisher signing
certificate or signing pipeline is configured. Neither host nor guest has an
available CurrentUser code-signing certificate. No certificate/trust-store change,
commit, tag, push, hosted workflow, publication or actual signed upgrade ran.

## Completed

- All **30 update tests** and **14 release-identity tests** pass. These retain
  their documented mocked positive publisher/launch boundaries.
- The source-tracking gate initially found `tests/test_live_dpi.py` untracked.
  Its exact contents matched the preceding 269-test artifact's source manifest.
  That one existing regression file was added to Git's index; all other staged
  and unstaged changes were preserved. The gate now passes with 140 tracked files,
  and all tracked Python compiles. Nothing was committed.
- A full 0.1.37 **lab-only version fixture** was built from a separate copy of the
  exact 0.1.36 review source. Only `src/version.py` differs in the copied inputs.
  The repository remains at 0.1.36; no Git tag was created. The fixture is dirty,
  review-only and explicitly marked never to publish.
- The actual full windowed baseline and candidate both passed fresh packaged
  identity and nonce/version/import/asset health checks inside the VM.
- Six real worker rejection cases passed without mocks: missing publisher pin,
  unsigned installer, corrupt installer bytes, wrong worker path, wrong baseline
  version, and an unsigned restore attempt. Each exited 1, recorded `blocked`,
  created no handoff and preserved the target, synthetic config and draft.
  These reject before installation; they do not establish successful rollback.

The normal app stayed open in the VM. Its executable and private configuration
digests are unchanged. The rejection tests used a separate installation folder,
with hard links for immutable fixture copies to avoid unnecessary disk use.
Redundant worker/candidate links and the deliberately corrupt copy were removed
after each owned process exited. No VM image, snapshot or OVA was created.

## Exact fixtures and evidence

Baseline: review build `107dcb03-fbf8-42e7-8aef-920e5175c8ad`, version 0.1.36,
SHA-256 `b46774983149682a1b71e4030ac17b681090a540a4f702fc23bb40cbcbdf15cb`.

Candidate: lab-only build `302b4a90-8cab-4715-9819-a53d45dabec1`, version 0.1.37,
SHA-256 `0ed1f8c01236818492286d5c655595060617a602ee99c009171f6516f19434e1`.

External evidence and harness sources:
`C:\Users\PCR\Documents\SecondChecking Review\sc22-updates-2026-10-27`.
`guard-results.json` records eight packaged checks. The candidate build record
retains its complete input manifest; the builder verifies the source snapshot
before making its isolated version change.

## Required signing decision

Follow-up: the user approved a temporary VM-only signer and manually confirmed
Windows' trust warning. Eight signed scenarios and Tools recovery passed.
The user confirmed Windows' removal dialog; the temporary trust, private key and
disposable VM installations are removed. No host trust changed. See the signed
matrix for exact results and scope.

Windows Authenticode must return `Valid` and match the independently configured
publisher fingerprint for both baseline and candidate. The current unsigned
copies cannot satisfy that boundary. It will not be mocked or disabled.

A concrete `sign-fixtures.ps1` script is prepared outside the repository and
syntax-checked, but **has not run**. With explicit user approval it would create
a two-day, non-exportable test signing key in the VM user's `My` store, add only
its public test certificate to that VM user's `Root` store, and sign only the two
disposable copies. The pin would be scoped to test processes. Its cleanup mode
removes only the marked test certificate and private key. It cannot run on this
host without the prepared guest lab marker, and refuses signing without its
explicit approval switch.

That option enables real Windows signature/installation/recovery tests in the
offline VM; it cannot establish production publisher trust or hosted release
acceptance. Alternatively use the intended publisher certificate/provider.
No production key, PFX or password should be placed in this repository or chat.

## Remaining acceptance

Three broad groups still remain: signed release/update/rollback, maintenance,
and physical hardware/monitors. The signing decision above is the next dependency
for the VM upgrade/recovery matrix. Review/commit and exact tagged hosted CI,
production signing, and deployment-specific compatibility remain separate gates.
