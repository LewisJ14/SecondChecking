# SC22 repeatable testing and portable baseline

Evidence date: 23 October 2026. Acceptance is in progress; this is not release approval.

27 October follow-up: the current full artifact passed
[155 accelerated worker lifecycle cases and normal exit/relaunch](sc22-worker-soak-acceptance.md).
The restored draft was verified by direct in-guest capture after discovering
stale VirtualBox framebuffer screenshots. Long-duration and physical bench
acceptance remain separate. Baseline/image statements below are historical.

## Baseline provenance

The original `SecondChecking-Test` VM remains unchanged. A full independent clone
was made from its `Ready-to-test` snapshot
`c2cf148c-0ef8-4f5a-9bb5-f4a0deb2dd29`. The export clone is
`SecondChecking-Baseline-Export`, UUID
`003b65f7-e71d-4828-a2eb-f6699929db42`, using VirtualBox 7.1.16r172425.

Resuming the snapshot's saved memory failed with a VirtualBox triple fault.
Cold booting the disposable clone succeeded. Its host shared folder and both
installation DVD references were removed. Its network adapter, clipboard and
drag-and-drop are disabled. Export uses a clean Windows shutdown, without saved RAM.

This is a Windows evaluation lab with synthetic data. Its default application
and `TestBackend.exe` simulator predate the SC01–SC21 changes. They are retained
as a reproducible historical fixture, not current server contract coverage.
The lab application login is `tester` / `test`; its default order is `test`.
Windows uses the separate `vmtester` account and existing private lab credentials.
The appliance contains synthetic lab credentials and stays in local review storage.
Evaluation activation/expiry must be checked before future reuse.

## Checks completed

The clone's standard, nonadministrator Windows session ran the exact SC21 review
executable at `C:\SC22Validation\main.exe`. Embedded build identity and packaged
health checks passed. SHA-256:
`e6d470538c383a89c77f76e7489e43b243a405a1570dec7fa6371a9368a5f1a0`.
Build ID: `e41677af-579d-411c-af54-1b33c03b6910`, version `0.1.36`.
This executable predates the new SC22 test tools; it is not a newly signed release.

After starting the fixed lab services, a read-only SQL probe confirmed the tester
and test order, loopback API/database configuration and expected application
password. Evidence is outside Git under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-evidence`.
`baseline-services.json` is the successful probe; `baseline.json` records the
earlier cold-boot probe before services started. Services do not start merely
because Windows has booted without an interactive login.

The real Web-Tools Flask route/auth/migration suites passed **49 tests**, using
temporary SQLite fixtures on the host. This includes the desktop retry/readback
path after a committed response is lost. The cross-checkout adapter now uses an
HTTPS URL consistent with SC21's transport guard; its in-process Flask adapter
does not exercise real TLS. The server's local `.venv` lacked pytest; the installed
system Python 3.13 runtime ran the suites successfully. Four existing Alembic
deprecation warnings remain.

## Redeployment procedure

The portable artifact is kept outside Git in
`C:\Users\PCR\Documents\SecondChecking Review\sc22-portable`.
The exported file is `SecondChecking-Lab-Baseline-2026-10-23.ova`,
10,257,840,640 bytes, SHA-256
`66ebdecbeb434607f18de1c910ac34bd9c239eeda1dd5376c49db7a60c70807d`.
All disk, NVRAM and OVF SHA-256 manifest entries passed verification, and
VirtualBox's import dry run passed. Independent boot evidence is recorded below.
Verify its SHA-256 and manifest before importing. The repository tool
`scripts/verify_vm_appliance.py` checks every payload without extracting files,
rejects unsafe paths and external payload/shared-folder dependencies, and writes
a JSON report. Integrity verification alone does not establish a working boot.

Import into a new VirtualBox VM with a fresh name and disk directory. Keep its
network adapter disabled and check that no host shared folders or installation
media have been attached. Cold boot, sign in with the private Windows lab account,
and start the lab through its existing launcher. For service-only checks run
`C:\SC22Validation\start-baseline.ps1`; then run `probe.ps1` in the same directory.
The existing launcher opens the historical application. The SC21 review executable
is staged separately; it must be paired with a matching isolated Web-Tools service
before testing current assignment workflows.

Take a powered-off snapshot before testing and restore that snapshot between runs.
Reimport the preserved appliance when a completely independent reset is needed;
the OS and lab dependencies are included. Neither process requires reinstalling
Windows. Avoid saved-memory baselines because of the observed resume failure.

## Remaining acceptance

Current status: **three broad groups remain** — signed release/update/rollback,
maintenance, and physical hardware/monitors. The
[maintenance checkpoint](sc22-maintenance-acceptance.md) passes preflight,
busy-dialog blocking, app-level decline, real UAC refusal and the approved
nonzero-exit path with a missing module. Draft contents/configuration and update
history are preserved for the approved attempt; successful installation/Sysprep
remain open.
The
[27 October update-readiness checkpoint](sc22-update-readiness.md) verifies real
unsigned worker rejection; the [signed VM matrix](sc22-signed-update-acceptance.md)
now passes eight signed scenarios and Tools recovery with an approved guest test
signer. Temporary guest trust/key and disposable installations were removed. Production signing and
hosted release acceptance remain open. The
[packaged TLS matrix](sc22-tls-acceptance.md) and
[coordinated workflow matrix](sc22-assignment-workflow-acceptance.md) are complete.
Production endpoint/certificate configuration and smoke tests remain rollout work.

Earlier 26 October status: there were **five remaining acceptance groups**, each containing
several checks. SC01–SC21 and VR01–VR08 are implemented locally. Native packaged
DPI samples now have correction evidence; mixed-monitor and physical checks
remain. The [report/session checkpoint](sc22-report-session-acceptance.md) advances
the first group without closing its other workflows.

- Run the current packaged GUI against the matching isolated Web-Tools deployment:
  login, lookup, all result policies, assignment, lost-response retry, conflicts,
  report readback and serial removal. The historical simulator cannot close this.
- Exercise actual service TLS, private CA handling and native SQL TLS.
- Review/commit source, run the hosted release workflow, and test a signed upgrade,
  failed update and rollback. No commit, push or release was made here.
- Verify elevation prompts and actual maintenance on a disposable suitable machine.
- Complete native Windows DPI/visual checks and the SC08–SC13 physical hardware
  checklist. No physical walkthrough or hardware pass is implied by guest CLI tests.

26 October TLS follow-up: [packaged service/private-CA/native SQL TLS acceptance](sc22-tls-acceptance.md)
is complete. **Three broad groups remain:** signed release/update/rollback,
maintenance, and physical hardware/monitors. Temporary TLS endpoints were stopped;
the original lab configuration and database startup were restored. Production
endpoint/certificate configuration and deployment smoke tests remain rollout work.

26 October follow-up: the coordinated synthetic packaged workflow group is now
complete; **four broad acceptance groups remain** (TLS, signed release/update and
rollback, maintenance, physical hardware/monitors). See the
[workflow matrix and exact artifact identities](sc22-assignment-workflow-acceptance.md).
The restored lab owner is `test`, with six reports, six assignment-history rows
and seven receipts for the primary device. Historical reports and the secondary
fixture are unchanged. The guest fault proxy is stopped; no new VM/OVA was made.

## Independent import result

The actual import completed as `SecondChecking-Redeploy-Check`, UUID
`73e9fa9f-4c19-405d-9e3b-88cbf84050bc`, with its own converted VDI disk UUID
`a246b673-ce03-48a9-8bd8-a1e47acf718e`. It cold-booted successfully. The imported
configuration retained disabled networking, clipboard and drag-and-drop, no shared
folders, and no installation media. Guest Additions became ready after Windows
booted; initial attempts before readiness were retried using `waitrunlevel system`.

The fixed lab services started inside the imported guest. Its fresh probe passed
every fixture check, including tester/order presence, expected application password,
loopback configuration, executable hashes and nonadministrator process identity.
The staged SC21 executable emitted a new build-identity report. A fresh health
request in a new guest directory returned success with nonce
`sc22-independent-import-73e9fa9f`; the exported result file was not reused.
Evidence files are `redeploy-baseline.json`, `redeploy-identity.json` and
`redeploy-health.json` in the external evidence directory. This proves the appliance
can be imported and run independently without reinstalling Windows or lab dependencies.

The imported VM was then shut down cleanly and given the powered-off reset snapshot
`SC22-Imported-Clean-Baseline`, UUID `5237ce6b-cf3c-443b-9832-7deab50cda4c`.
Both new VMs are off; the original VM remains running. A short redeployment README
is stored alongside the OVA. See also [portable evidence](sc22-portable-evidence.json).

Desktop validation: 244 tests passed, 85 tracked Python files compiled, source-index
policy passed for 138 files, actionlint passed, and whitespace checks passed.
All 192 tracked server Python files also compiled. The portable-image portion of
SC22 is complete; the acceptance items above remain open.

VirtualBox export/import command reference:
[Oracle VirtualBox 7.1 manual](https://docs.oracle.com/en/virtualization/virtualbox/7.1/user/vboxmanage.html).

## BatterySimulator lab addition — 23 October 2026

At the owner's request, BatterySimulator v1.1.0 x64 was installed in the original
`SecondChecking-Test` VM, after checkpoint
`b3df4c47-8f3e-405f-9066-cb4362ab8e54` (Before-BatterySimulator-2026-10-23).
This later installation is **not included in the OVA described above**.
The guest's Secure Boot was already off; test-signing was enabled in the guest
and its MSI installed the project's test certificate there. No host certificate
or driver setting was changed. MSI SHA-256:
`5c93194ad8a82769133a6dea28688db9e11f0f52e80e629b2911ce6257286752`.

Upstream's default SWD devices disappeared after reboot. Persistent ROOT devices
were created instead and explicitly bound using `pnputil /add-driver /install`.
After another reboot, `ROOT\DEVGEN\1` and `ROOT\DEVGEN\2` both reported device
error code 0 and appeared in Win32_Battery at 90% charge. BatteryQuery changed
the second battery to 75% independently; reboot restored the driver's defaults.
WMI exposed design/full capacity pairs of 110/100 mWh for each distinct instance.
The simulator deliberately supplies duplicate device names and serial numbers.

The installed BatteryInfoView helper's default `/scomma` export succeeded and
reported 90.9% health, but exported one selected battery. This is a new acceptance
case for SC08: verify that the current packaged collector captures every battery
without merging duplicate serial numbers, and saves/reads back each paired
capacity. This installation does not establish that app-level coverage, or
physical battery acceptance. Evidence and scripts are outside Git in
`C:\Users\PCR\Documents\SecondChecking Review\BatterySimulator-v1.1.0`.
A BatterySimulator Guide is on the guest desktop. VM guestcontrol operations
leave the host mouse and keyboard alone; the VM window remains available to watch.

Project instructions and release:
[BatterySimulator](https://github.com/forderud/BatterySimulator),
[v1.1.0](https://github.com/forderud/BatterySimulator/releases/tag/v1.1.0).

## Battery-enabled portable image

The owner subsequently requested a second OVA including BatterySimulator.
`SecondChecking-BatterySimulator-2026-10-23.ova` is saved in
`C:\Users\PCR\Documents\SecondChecking Review\sc22-battery-portable`.
It is 22,723,396,608 bytes, SHA-256
`0d7e509f4bfa32e566dbcf4e56bbc922cf0532b3e28f09c550f6c8cfdb7c06bd`.
The earlier OVA was retained initially, then removed in the owner-authorized
26 October cleanup described below. This later image includes the installed driver,
persistent batteries, desktop guide and the separately staged SC21 review executable.

Source snapshot: `c6df6fa1-b51f-4c02-b574-032f4b98c102`. Full export clone:
`26270665-2cbb-4332-99bb-8881ecc37498`. Saved memory was discarded only in
the clone, host shares/media detached, networking/clipboard/drag-and-drop disabled,
then the clone cold-booted, passed battery/defaults/health checks and shut down cleanly.

The complete SHA-256 manifest passed verification. An actual independent import
as `SecondChecking-Battery-Redeploy`, UUID `8fb18e49-ba7f-4bfa-8e04-c08386f76928`,
cold-booted with its own disk UUID `a422f053-a384-4626-91fc-6d8ab407a037`.
Both persistent battery devices had error code 0 and 90% charge. The loopback
synthetic lab defaults passed after starting services. The staged review executable
passed a fresh health request in a new directory, nonce
`battery-ova-independent-import-2026-10-23`. The imported VM was shut down cleanly
for a reset snapshot. `verification.json`, `SHA256SUMS.txt` and a README accompany
the OVA; detailed reports are in the external `sc22-battery-evidence` directory.

This export is larger because it captures the later Windows VM state. Read-only
comparison found filesystem use of 36.59 GiB in the current source versus 24.13 GiB
in the older baseline. Windows component-store logical totals were 17.391 versus
10.761 GiB, while lab files were only 0.588 versus 0.572 GiB. BatterySimulator's
installer is 176,128 bytes. Directory totals include hard links and cannot be
summed as unique disk use or reclaimable space; the full filesystem delta was not
attributed folder by folder. No Windows cleanup was performed. The source VM
remained available in its visible window throughout background export/import.

## Latest packaged visual review

The [23 October visual review](vm-visual-review-2026-10-23.md) exercises the staged
SC21 candidate against matching real service routes in a new isolated guest
database, with native 1080p, 4K and Surface-style resolution/DPI evidence. It adds
six follow-ups, including a P1 frozen-worker extraction leak which exhausted the
guest disk during the later review. This happened **after** the portable images
were exported and does not explain their earlier size difference. Verified
inactive review extractions were cleaned; the review app was closed to prevent
further growth. Neither OVA was rewritten. Fix the candidate lifecycle and repeat
bounded-disk/worker/DPI acceptance before release; portable-image verification
does not establish that candidate's application acceptance.

## Disposable image cleanup — 26 October 2026

The owner requested removal of unneeded test images after the host C: drive
filled (122,888,192 bytes free) and VirtualBox paused the working VM. Four
powered-off disposable VMs occupied approximately 110 GiB. Each used independent
disks under the review folder; none was the active working VM.

Removed through VirtualBox unregister/delete, including their disposable snapshots:

- SecondChecking-Baseline-Export, `003b65f7-e71d-4828-a2eb-f6699929db42`.
- SecondChecking-Redeploy-Check, `73e9fa9f-4c19-405d-9e3b-88cbf84050bc`.
- SecondChecking-Battery-Export, `26270665-2cbb-4332-99bb-8881ecc37498`.
- SecondChecking-Battery-Redeploy, `8fb18e49-ba7f-4bfa-8e04-c08386f76928`.

Before removing the last battery copies, a fresh full-file SHA-256 check of
`SecondChecking-BatterySimulator-2026-10-23.ova` matched the recorded
`0d7e509f4bfa32e566dbcf4e56bbc922cf0532b3e28f09c550f6c8cfdb7c06bd`.
The superseded `SecondChecking-Lab-Baseline-2026-10-23.ova` (10,257,840,640 bytes)
was then removed. Historical verification reports are preserved; their VM names
and snapshots above document prior verification and are no longer registered VMs.

Retained: the working `SecondChecking-Test` VM with its existing rollback snapshots,
the latest verified battery-simulator OVA, application builds and test evidence.
No OVA was rebuilt or rewritten. Host free space rose to about 136 GB and the
working VM resumed; its own C: drive had about 44 GB free. Host and guest disk
exhaustion are separate incidents.

For future testing, keep one working VM and one verified redeployment OVA.
Remove export clones and disposable import VMs when verification completes.
Before cloning/importing/exporting, check host free space against the expected
disk/archive size with operating headroom; do not retain duplicate full images
by default. Review working-VM snapshots separately before consolidating them.
