# SC22 tested-commit release handoff — 27 October 2026

The release workflow now passes the exact tested commit from its verification
job to its build job. Previously both jobs independently checked out the release
tag. Moving that tag between jobs could build source that had not passed the
verification job, despite each checkout individually matching its current tag.

The verification job records and validates its full HEAD SHA as a job output.
The dependent build checks out that SHA, retaining the separate clean build
checkout. The existing release source guard still requires the fetched tag to
identify HEAD, so a tag moved before the build checkout fails that guard rather
than silently selecting new source. Publication still checks the remote commit.

The regression uses a disposable real Git repository: an annotated tag initially
matches the tested commit, moves to a second commit, and is rejected when the
build stays on the original SHA. Source-policy checking is mocked in this fixture;
Git commits, tag resolution and the production source-state guard run for real.
No tag, commit or Git configuration in the product repository is changed.

The 15 release-identity tests pass, the workflow passes actionlint, all tracked
Python compiles and the source gate passes with 140 tracked files. The baseline
desktop suite passed all 275 tests in 108 seconds; it was started before adding
this regression. The subsequent targeted run passed all 15 release tests, including
the new case. No new application build is needed for this workflow/test change,
and the VM application remains the preceding review artifact.

This is local verification. The exact-tag hosted workflow, production publisher
signing and release review remain open. Nothing was committed, tagged, pushed,
uploaded or published in the product repository. No VM or OVA was created.

GitHub documents [job output handoffs](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/pass-job-outputs)
and checkout's [SHA ref support](https://github.com/actions/checkout/blob/v4/README.md).
