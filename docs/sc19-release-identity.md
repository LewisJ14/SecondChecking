# SC19 release workflow and artifact identity

Implemented locally on 22 October 2026. The shared pipeline builds and prepares identifiable artifacts; no tag/version was changed, no release was uploaded, and no review executable was deployed. The unsigned review artifact is version 0.1.36 with its own build UUID and source fingerprints. Actual GitHub-runner and signed/VM acceptance remain pending.

## Changes

Previously the release workflow imported `version` from the repository root even though it lives under `src`, used an unsuitable release-upload action, and built after release publication. The PowerShell publisher could increment the version while skipping compilation, rename an older executable with that new version, delete a release or clobber its assets, and ignore native-command failures. The Python uploader had the same unidentified-artifact reuse problem. The compile script copied private local configuration and logs, removed previous build output, and could stop a running application to replace it.

`compile.ps1`, `publish-release.ps1` and `scripts/upload_update.py` now route through `scripts/release_package.py`. The compiler uses a fresh output directory outside the checkout, without deleting existing artifacts, killing applications or copying user-managed runtime files. The spec explicitly includes the required public audio/tool/script assets and generated identity. It does not sweep the assets directory for local files. `runtime-files.json` is a legacy file and is no longer used to copy private configuration/logs.

The pipeline parses the version declaration without executing the module. A release requires an exact `v<major.minor.patch>` tag, a clean checkout, tracked build inputs and HEAD matching the tag. Review builds explicitly opt into local changes and remain marked `review_only`, even if their tree happens to be clean. They cannot pass publication verification. There is no automatic version increment or tag creation.

Every build records a UUID, timestamp, version, tag, base commit, dirty/review status, Python version, installed distribution versions and SHA-256 fingerprints of Python source/tests/release scripts, packaging inputs and required assets. Runtime configuration, logs and private environment values are excluded. Source identity is checked before and after packaging. Direct dependencies must match `requirements.txt`; transitive versions are recorded, not fully locked. This records provenance; it is not an independent attestation or a claim of byte-for-byte reproducible builds.

The identity is embedded in the one-file executable. A numeric Windows version resource is generated from the same version. Before accepting a build, the tool reads the identity back from the archive and checks its Windows file version and windowed PE subsystem. A GUI title shows the build/review identifier beside the app version. The private `--build-info <output.json>` entry writes identity before importing the controller, configuration or hardware code; source mode cannot claim a packaged identity.

Preparation checks current source/tag/review status against the build record and embedded identity. It copies the identified executable under the matching versioned name and calculates `update.json` and `build-manifest.json` from the final bytes. A changed executable is accepted only with the configured, valid pinned Authenticode signature; this permits external signing after build without accepting an unrelated executable. Final signed builds must keep the same embedded identity and Windows version. Signing credentials and a production certificate/provider remain unconfigured. Unsigned builds use SC18's manual release-page flow.

Publication is explicit and creates a new **draft**. The tool rechecks source and all prepared metadata, hash/size, embedded identity and release notes, then checks the remote tag's commit. Existing releases stop the operation. There is no release deletion, tag movement or asset clobbering. GitHub CLI failure propagates as failure rather than a successful-release message. Draft publication to users is a separate release decision after acceptance.

The workflow now builds an exact tag on push or manual dispatch. Tests run in a separate checkout/job so their runtime log writes cannot contaminate the build checkout. It fetches tags, uses Python 3.12 and pinned direct dependencies, retains prepared artifacts and creates a draft only for a tag push or explicit dispatch upload. Release-write permission is scoped to the build job; input values pass via environment variables. Native Python failures are checked explicitly. It does not trigger from a published release.

## Verification and limits

The 14 targeted provenance tests cover nonexecuting version parsing; invalid versions; wrong tag/commit; dirty/review source; input hashing and private-file exclusion; source changes during packaging; JSON identity round trips; isolated output reuse refusal; exact artifact hashes; stale identity; unsigned post-build changes; tampered artifacts/manifests/notes; permanent review publication refusal; wrong remote tags; existing releases; draft upload arguments; and headless identity validation. GitHub upload boundaries are mocked; no test modifies GitHub.

The full desktop regression suite also exposed a pre-existing process ownership race under build load: a native helper could spawn a descendant between `Popen` and Windows Job assignment. Workers now start suspended, attach to their owned Job, then resume. The descendant termination test deliberately delays assignment while its fixture would otherwise spawn immediately. This makes the lifecycle regression deterministic rather than increasing a wait to hide the race. These changes also apply to SC17/SC18 owned helper processes; historical frozen evidence for those items retains its original source hashes.

A complete windowed `main.exe` was built with the new spec. The build gate reads its embedded identity and Windows version, and preparation verifies its final bytes. Archive inspection checks that required assets/identity are present and private config/log/draft files are absent. This host runs without an elevated token, while the existing main application still requires administrator privileges. The executable was therefore inspected without launching it or requesting UAC; initial GUI/login and `--build-info` execution on the exact main artifact remain VM acceptance work under SC21/SC22. The source identity-report boundary has a test, but that does not establish successful packaged startup.

The first build gate correctly rejected an in-memory tuple versus JSON-list identity mismatch; dependencies now use a JSON-stable shape, covered by a round-trip regression. That earlier output has no accepted build record and must not be used. The accepted artifact and source fingerprints are recorded in [the evidence manifest](sc19-release-evidence.json), with final test/compile/linter counts. Nonfatal existing WMI/numpy/API-set build warnings remain in the isolated PyInstaller warning log.

## Before release

The [27 October tested-commit follow-up](sc22-release-commit-handoff.md) fixes the
cross-job tag movement gap: the build consumes the verification job's exact SHA,
while the existing source guard rejects a tag that now identifies another commit.
The release-identity suite now contains 15 tests. Hosted acceptance remains open.

1. Complete SC20 source tracking so generated/private runtime artifacts do not obstruct a clean release checkout. Commit the reviewed source through the normal review process, choose the next version, and create/push its matching tag only when ready.
2. Run the workflow on that exact tag and inspect the draft and downloaded artifact hashes. The local tests and actionlint check do not prove a successful hosted workflow or authenticated GitHub upload.
3. Configure an independently trusted publisher and external signing process. Build, sign, then prepare using `--artifact` and the configured certificate fingerprint. Complete SC18's valid signed upgrade/failure/rollback VM matrix and matching service/schema checks.
4. Complete SC21 transport/privilege work and SC22 clean-VM/physical acceptance. Confirm the actual packaged `--build-info` report, visible version/build label, login and public asset availability before publishing the draft.

No database migration is introduced. SC20 source tracking and service boundaries is the next numbered item.

## Reference contracts

Implementation was checked against [PyInstaller 6.3 spec documentation](https://pyinstaller.org/en/v6.3.0/spec-files.html), [GitHub release event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#release), and the [GitHub CLI create](https://cli.github.com/manual/gh_release_create) and [upload](https://cli.github.com/manual/gh_release_upload) contracts. Windows worker ownership follows the documented [suspended process creation flag](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags). Workflow validation uses the upstream [actionlint 1.7.12 release](https://github.com/rhysd/actionlint/releases/tag/v1.7.12), with its downloaded archive checked against the upstream SHA-256 list.
