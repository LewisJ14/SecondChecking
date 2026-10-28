# SC22 repeated frozen-worker and restart checks — 27 October 2026

Owner decision after this checkpoint: skip the proposed hours-long stability
run. It is not pending or scheduled. The [physical bench checklist](sc22-physical-bench-checklist.md)
defines the remaining hands-on checks. Statements below about the limits of
accelerated testing remain applicable.

The current full review artifact passed 155 accelerated lifecycle cases after
six warm-up workers, followed by normal GUI exit, relaunch, sign-in and draft
restoration. This is a bounded cycle test, not an hours-long or physical bench
soak. No product source changed and no new build was produced.

## Artifact and harness

Full review build `73ce3899-7694-4e1b-8217-46d41f87cd5e`, version 0.1.36,
SHA-256 `c9d9276561bd8908fe3cfe737fd6712eba1f9953dd8a38fc3c969279b9f1b9de`.
The actual frozen executable supplies all worker code and reuses the running
app's extraction. The copied production launcher source matches its embedded
manifest: SHA-256
`7cee9ec42838ed15981109ae48107e79f0a2c98f34020a508fd0699bbfa8249d`.

The external parent harness runs guest Python 3.13.2; the frozen workers and
separately exercised full GUI use bundled Python 3.12.0. The harness validates
real worker replies, ownership and cleanup, but does not replace the packaged
GUI parent's entire callback/lifecycle acceptance. It does not mock native
worker results or launch maintenance, activation, product-key or update actions.

## Results

The worker phase completed in 71.58 seconds:

| Cases | Count | Observation |
| --- | ---: | --- |
| Live battery | 15 | Complete replies |
| Audio enumeration | 15 | Complete replies; device usability is not asserted |
| USB enumeration | 15 | Complete replies; insertion/removal is not simulated |
| Local MDM evidence | 15 | Matching request IDs; no local indicators, tenant verification not checked |
| WLAN query | 15 | Real error replies from the VM's WLAN environment; no artificial timeout |
| Unknown-kind control | 15 | Expected error replies |
| Immediate camera-worker cancellation | 60 | Owned processes and directories removed; camera usability is not tested |
| Independent startup deadline | 5 | Short timeout while independently unpacking; owned runtime removed |

Every completed or cancelled job removed its owned directory. Original app
process identities stayed unchanged during the cycle phase. The active parent
extraction count remained one and the owned test work directory ended empty.

Harness handles were 142 after warm-up and 146 at the end; cycle samples ranged
142–145. Threads ended at their baseline of three, with cycle samples 3–5.
Harness resident memory increased by 499,712 bytes (about 0.48 MiB), within the
predeclared 32 MiB bound. The GUI process resident memory decreased slightly.
These bounded observations do not prove the absence of a long-duration leak.

Normal GUI close then left **zero app processes and zero parent extractions**,
without forced termination or manual runtime deletion. Relaunching the same
artifact created one extraction. Tester signed in through the normal app flow,
searched `test` and visibly restored the existing local draft. Both new app
processes have non-elevated tokens.

## Preservation and capture tooling

Before/after public database snapshots match: six reports, six assignment-history
rows, seven receipts, the `test` reservation and the unchanged secondary fixture.
Configuration and normalized draft contents match the preceding checkpoint.
Update history remains at 13 entries. The guest stayed offline. The user's
requested CurrentUser RemoteSigned setting remains configured, and the existing
administrator PowerShell console was left untouched.

VirtualBox's framebuffer screenshot command returned obsolete frames, including
an older build that was no longer running. Process/session checks confirmed the
app and console were in the same Windows session. Those framebuffer images are
not evidence of the current relaunch. Direct in-guest GDI capture shows the
current `73ce3899` window and restored draft in `reopened-test-loaded.png`.
Future visual checks should use direct guest capture and cross-check the title
against the live window state. The guest pointer-focus wrapper also failed on
its off-screen cursor movement; ordinary input to the already active test app
worked without that wrapper. Neither issue is classified as an application bug.

## Evidence and remaining acceptance

External evidence/harness:
`C:\Users\PCR\Documents\SecondChecking Review\sc22-worker-soak-2026-10-27`.
This includes source, complete case/resource samples, `normal-exit.json`, the
direct guest capture, database snapshots, `final-state.json` and
`verification.json` (all required checks pass). No private configuration or
credentials were exported. No VM image, snapshot, OVA or release was created.

The preceding full product suite remains 277 passing tests; it was not rerun for
this external harness/documentation-only checkpoint. The hours-long run is
skipped at the owner's request; physical peripherals and mixed monitors remain open. Other outstanding
SC22 work includes installation of an actually offered Windows update,
alternate-admin/Sysprep, production signing and exact-tag hosted release acceptance.
