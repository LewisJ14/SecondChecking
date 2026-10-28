# SC17 — windowed helper communication and packaged scripts

Implemented locally on 22 October 2026. The matching released executable, clean-VM
and physical/OS-update acceptance remain pending. No host Windows updates, provider/
module installation, registry mutation or certificate-store maintenance was performed.

## Helper result contract

Updater, local MDM refresh and Windows Update completion now use private per-job
request/result files. The early main.py --app-helper dispatch runs before desktop
controller imports and does not start a GUI. The parent invokes its own executable
when frozen and the explicit source main.py path when running Python. Standard
streams are redirected away and are not part of the contract.

Each request has a random UUID. An atomic JSON result names helper_version 1, the
same request UUID, helper kind, explicit ok/error outcome and validated payload.
Missing/invalid/oversized/wrong-version/wrong-job results and failed worker exits
cannot become successful no-update/clear/completed messages. Update results retain
the explicit up_to_date/update_available distinction and running-version check.
MDM retains qualified local evidence and tenant_verification=not_checked; refresh
failure becomes an explicit local evidence error rather than a device-clear claim.

Owned jobs reuse SC11 Windows process-tree lifetime/timeout handling. Completed
helpers receive a short exit/cleanup grace so one-file bootloaders can remove their
extraction directories; hangs/crashes/timeouts are killed/reaped and owned IPC files
are cleaned up. Updater limit is 60 seconds; MDM 30 seconds. Application helpers
run on workers, leaving UI event handling available. Legacy console flags still
print JSON for source/manual use; the GUI no longer consumes those streams.

## Windows Update asset and result

main.spec now embeds src/Script.ps1 at the bundle root. One resolver selects the
source script or frozen _MEIPASS asset and rejects a missing script. There is no
shared TEMP/Script.ps1 copy and no nested Start-Process shell whose exit code hides
the child result. The worker uses an argument-list PowerShell -File invocation,
NonInteractive mode, the existing administrator requirement and a 30-minute limit.
PowerShell stopping errors produce a nonzero exit. The outer owned process-tree
limit is 1830 seconds. The UI reports completion only after the actual child returns
zero; it asks the operator to check update history. This does not certify that every
Windows update installed or that a reboot is unnecessary. Normal app closure is
blocked while this maintenance is active.

SC16 server authorization runs before the maintenance helper starts. Existing
provider/module installation policy and Windows elevation/transport boundaries
remain SC21 acceptance. The script was parsed and its runner mocked during tests;
it was not executed on the host. Routine app-update checks no longer invoke the
legacy root-certificate refresh function; root-store maintenance is not an update
check side effect.

## Verification

Source checks cover absent streams, explicit update states, qualified MDM, malformed/
wrong/empty/error replies, source dispatch without GUI, separate frozen commands/UUIDs,
timeout cleanup, child exit failures, source/frozen/missing assets, real exit-code
handling, PowerShell parser-only validation and GUI consumption of file results.
163 desktop tests passed and all 99 desktop Python files compiled. The real
windowed one-file probe passed nine scenarios with standard streams explicitly
removed; Windows PE subsystem 2 was verified. Binary/source hashes, tool versions
and results are recorded in [the evidence manifest](sc17-helper-evidence.json).
The executable and build files are retained under SecondChecking Review/sc17-build.
Build warnings for WMI escape sequences and a Windows API-set DLL were non-fatal
on this host; a clean VM remains necessary.

The frozen probe uses a separate one-file/windowed test entry point with production
helper/asset/lifetime code. All network, registry and maintenance outcomes are
fixtures in that test entry point; production main.py has no fixture switch.
It checks real self-spawned children with absent standard streams, newer/no-update,
local MDM, mocked maintenance completion, errors, no output, malformed/mismatched
results and a killed hang. It is not the final main executable or physical/VM proof.
The initial probe incorrectly assumed redirected windowed children must have None
streams; DEVNULL handles can create streams. The final probe explicitly removes
them to test the required worst case without relying on that assumption.

Remaining: build the matching release under SC19; repeat these cases with the exact
main executable in the VM; check clean-machine script presence, unavailable provider/
module/network, real UAC/Windows Update exit/timeout and physical local MDM evidence.
SC18 retains update artifact validation, install safety and rollback.
