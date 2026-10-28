# SC06 — qualify local MDM evidence

Implemented locally on 22 October 2026. No updated executable has been installed
in the VM or released. This change qualifies the local check; it does not add a
live tenant lookup.

## Result meaning

The desktop no longer infers `locked` or `not_locked` from the presence/absence of
Autopilot registry values. Local states are `local_indicators`,
`no_local_indicators`, `error`, `unsupported` and `unknown`. Every presentation
states **Tenant registration / enrolment: NOT VERIFIED**. A negative local result
is not coloured green as a clean-device decision. Legacy unqualified results are
shown as unknown, including in View Spec.

Microsoft documents the diagnostics registry as containing Autopilot profile
settings received from the deployment service, including tenant identifiers.
[Microsoft troubleshooting FAQ](https://learn.microsoft.com/en-us/autopilot/troubleshooting-faq).
Tenant association is part of service registration.
[Microsoft registration overview](https://learn.microsoft.com/en-us/autopilot/registration-overview).
The implementation deliberately treats local observations as insufficient to
establish current tenant registration, enrolment, release or a usable-device lock.

## Capture, review and persistence

- Read the 64-bit Windows Autopilot diagnostics registry. Record tenant ID/domain
  and correlation identifiers as observations, not verified tenant ownership.
  Domain/correlation-only evidence also counts as an indicator.
- Preserve missing-key, empty-key, access-error and partial-read distinctions.
  Partial reads cannot become a clean negative result. Record source, UTC capture
  time, observations and read errors. Unknown legacy data has no invented capture
  time.
- Automatic refresh is now a local read. It no longer runs `dsregcmd /sync` or
  `gpupdate /force`; policy refresh does not supply tenant verification.
- Assignment takes a fresh reading before final review, instead of uploading a
  cached footer value. The review includes the evidence source/time and explicit
  tenant uncertainty. Indicators, incomplete reads, errors and unknown/unsupported
  evidence require a recorded reason under the existing exception policy.
  A completed negative local read alone does not require an additional reason.
- Save structured `mdm` evidence in the existing report JSON, with
  `evidence_version: 1` and `tenant_verification: not_checked`. Scalar report/order
  fields retain qualified local state and explanatory details. No schema migration
  is needed. Existing post-commit server checks were not changed.
- Saved-result readback returns the evidence. The server validates its source,
  state, timestamp, observations, read errors and required review reason. It rejects
  tenant-verification claims in this local-evidence contract and inconsistent
  negative results. Legacy reports remain readable/accepted but are projected as
  unknown, never as tenant-clear evidence.

The capabilities endpoint advertises `mdm_evidence_version: 1`. Deploy the matching
desktop/server together; the desktop checks support before sending version 1
evidence. Retry intent ignores a changed capture timestamp alone while retaining
changes to the observations/state/errors as different evidence. The original
pending request remains intact for reconciliation.

## Verification

72 desktop tests passed on Python 3.12, including mocked registry cases for missing
and empty keys, 64-bit reads, domain/correlation-only identifiers, denied/partial
reads, malformed/legacy statuses, read-only refresh, fresh assignment capture and
retry identity. Actual hidden Tk footer controls display the source, capture time
and tenant uncertainty with no green negative verdict.

25 real Flask transaction tests passed against isolated SQLite. New coverage proves
evidence persistence/readback, rejection/rollback for false claims and invalid
evidence, required reasons, and safe handling of legacy negatives. All 73 desktop
and 195 Web-Tools tracked/new Python files compiled. Scoped whitespace checks
passed. No database migration was run.

This run does not prove tenant integration or physical-device acceptance. The VM
is not a known enrolled device. Before rollout, exercise a known enrolled laptop,
a released/clean comparison device, access-denied reads and offline conditions;
compare the qualified local observation against an authorised tenant-side check.
Keep the outcome distinct even if local and tenant results disagree. Paired VM
acceptance and coordinated deployment remain outstanding. SC07 is next.
