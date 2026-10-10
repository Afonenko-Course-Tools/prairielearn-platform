# Platform versions and image publication

The tool contract is **1.0.1**. It adds native-readable JUnit tests/messages,
execution-limit messages and a bounded expected-outcome summary for submitted tests.
It preserves raw results, classification, score policies and containment limits.
Runtime images **1.0.0** were published from reviewed integrated source
`fc5a4d4e9d0795940b8cdf68e30e753ebfd27cec`.
The checked-in [runtime-image.json](../runtime-image.json) preserves that historical
receipt. [runtime-profiles.json](../runtime-profiles.json) identifies the current
runner/library hashes; `image: null` requires a newly published matching digest.
Publication records the actual reviewed source and both immutable OCI digests before
production acceptance. The following contracts are versioned independently:

| Interface | Current contract |
| --- | --- |
| `check-course.py inventory/verify` and `grading_job.py` | Tool 1.0.1 |
| Runtime registry, grading descriptors/jobs, check results, verification receipts, contract cases | `schemaVersion: 1`; closed owner schemas in `schemas/` |
| Resolved project check | Closed `project-check.schema.json`, versioned with tool 1.0.1; no redundant schemaVersion field |
| Gateway question/work results | `schemaVersion: 1`; closed owner schemas in `schemas/` |
| Gateway enrollment, assignment and work launch | Closed named schemas, versioned with tool 1.0.1; assignment `version` is the monotonic grant revision |
| Native course registry | `pl-courses-v1` |
| Image lock | `pl-images-v1`; `image` fields carry published deployment pins, local image IDs are diagnostic |
| Runtime profiles | `java25-junit-v1` implementation, `java25-mutation-v1` student tests |
| Java/JUnit | Actual Java release 25; pinned official JUnit console 1.14.1 and JSON simple 1.1.1 |

The runtime registry pins every library/source hash and the runner hash. Both
profiles share the same runner and libraries; the registry carries their exact hashes.
The production image must match those hashes, rather than reuse a preceding release pin.
A registry with `image: null` refuses production verification/staging.
`PL_LOCAL_IMAGE_ID` permits explicit candidate verification;
a local image ID cannot substitute for a published repository digest.

The Community bridge retains the reviewed assignment/enrollment/work/result
protocol. Complex cross-delivery migration remains deferred in a separate branch.
That branch is not part of this runtime image or release.

## Reviewed publication sequence

1. Independently review the exact PR head and both image sources, including
   `.github/workflows/publish-runtime.yml`. Complete the owner checks. Normally
   merge the PR into `main`, then confirm that the merged tree matches the reviewed
   tree and record the exact merged commit. Preserve deferred migration branches.
2. Dispatch **Publish reviewed Platform images** on that merged `main` only after
   confirming its current commit is the reviewed merge. Choose an unused version:

   ```sh
   gh workflow run publish-runtime.yml --ref main -f version=NEXT_UNUSED_VERSION \
     -f reviewed_commit=ACTUAL_MERGED_SHA
   ```

   Replace `ACTUAL_MERGED_SHA` with the actual 40-character merged commit and
   `NEXT_UNUSED_VERSION` with an unused `N.N.N` version. The
   workflow refuses any other branch or a checkout that differs from that commit.
   Version 1.0.0 already has published images; choose a new unused version for
   subsequent runtime changes. The workflow must exist on the default branch
   for manual dispatch.
   It uses its ephemeral `GITHUB_TOKEN` with `contents: read` and `packages: write`;
   the operator's GitHub CLI token does not need `write:packages`. SSH can push
   workflow changes without adding an OAuth workflow scope. The source/revision
   OCI labels associate both packages with this repository. Existing packages must
   grant this repository Actions access; an unrelated existing package cannot be
   overwritten by assuming token permissions.
3. The workflow rejects an existing version and fails closed if registry absence
   cannot be established. It builds both images from the exact checkout and pinned
   upstream bases, then runs the owner suite on actual JDK25 with the newly built
   Java image. Only after those checks does it push both images. It records actual
   `repository@sha256:...` values, exact source commit and version in
   `runtime-image.json`, and emits `published-runtime-profiles.json` with those
   actual Java digest pins. The artifact is named
   `platform-runtime-digests-VERSION`.
4. Download the successful run's artifact and verify `sourceCommit` against the
   reviewed merge. Preserve the receipt and published registry as release assets;
   an expiring Actions artifact alone is not a durable release. Replace the
   checked-in `runtime-profiles.json` with the emitted registry in a normal metadata
   commit. Keep runner/library hashes identical to the reviewed source. Review this
   pin commit before issuing the final source tag. Use the recorded Community
   digest as `PL_GATEWAY_IMAGE` with Compose `--no-build`.
5. Pull and inspect both actual published digests, verify package access from the
   target machine, and run the affected final native/container/Moodle smoke gates
   on those published pins. A source-based rebuild can have a different local image
   ID because it installs distribution packages and adds OCI provenance labels;
   the prior local candidate's ID is not the new publication's identity.
6. Tag the integrated, pinned release commit and publish the versioned source
   release together with `runtime-image.json` and the registry. Record source tag,
   image source commit, OCI digests, receipt hashes and actual integration outcomes.
   Course/downstream releases must use these observed pins.

The two image pushes are not atomic. If a failure publishes only one image, retain
its receipt/log and use a fresh version for a reviewed retry; do not replace or
reuse the partially published version. The workflow serializes one version within
this repository. GHCR tags are mutable registry aliases, so deployment and runtime
registry pins always use digests.

New GHCR packages are private by default. Publishing an image does not establish
public anonymous pull access. If public distribution is required, the package owner
must set and verify the desired visibility, then test an anonymous digest pull.
An auth/network/registry failure during the absence check remains a publication
blocker, not permission to bypass the existing-version guard.

See GitHub's primary instructions for
[manual workflow dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
and [Container registry authentication, repository access and visibility](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
