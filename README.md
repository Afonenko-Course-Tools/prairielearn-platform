# PrairieLearn platform

Shared platform for native PrairieLearn courses, with a Java 25 grader.
The candidate provides local verification, a private Community Gateway bridge and
portable development TLS. Published release pins remain a separate acceptance gate.

Java courses require JDK 25 or newer. The reference grader uses a pinned JDK 25.
Runtime credentials, identities, jobs and OpenTofu state belong outside this checkout.
The current pilot excludes backup and restore workflows.

Local verification:

```sh
JAVA_HOME=/usr/lib/jvm/java-25-openjdk PATH=/usr/lib/jvm/java-25-openjdk/bin:$PATH python3 -m unittest discover -s tests -v
```

Build an immutable native candidate with the installed full exporter:

```sh
python3 tools/build-course.py --source /path/to/clean/source --book tasks \
  --instance pilot --output /path/to/fresh-delivery
python3 tools/check-course.py inventory --manifest /private/checks.json \
  --scope declared --output /private/inventory.json
JAVA_HOME=/usr/lib/jvm/java-25-openjdk PATH=/usr/lib/jvm/java-25-openjdk/bin:$PATH \
  python3 tools/check-course.py verify --manifest /private/checks.json \
  --snapshot /path/to/source --scope declared --ready-only --backend host \
  --output /private/host-report.json
```

Declared checks include only opted-in profiles. Incomplete projects stay visible in
inventory; explicit verification refuses them. `--ready-only` is a diagnostic
selection available only in declared scope. Delivery verification additionally
requires `--delivery /path/to/native/delivery.json`; it compares the exported
starter, trusted sources, and normalized grading descriptor to the source snapshot.
Container verification is authoritative and uses offline 0.9 CPU/512 MiB jobs.
The canonical scenario inventory includes starter, every named reference and every
declared contract case; optional reference absence is recorded in the receipt.
`--scenario` subsets produce partial diagnostic receipts and cannot satisfy staging.
The exporter binds this inventory with delivery.verificationInventoryHash.
Receipts bind every question to its runtime, exact image and the dependency closure
reported by the executing runner; staging rechecks all bindings against the native
question descriptors and current published runtime registry.
For an explicit local image candidate, set `PL_LOCAL_IMAGE_ID` to an actual Docker
image ID. Local IDs cannot satisfy the staging gate for a published image digest.

`runtime-profiles.json` pins the official Java25 base, official JUnit1.14.1/JSON
libraries and unchanged upstream grader sources. Host preflight checks every bundle
hash and actual JDK25. Both backends execute the same explicit JUnit runner and
retain raw outcomes independently of weighted/all-pass/contract-group/threshold
policy. Trusted and student compilation failures have separate classifications;
zero/disabled trusted execution and missing reports are infrastructure failures.
Student-tests profiles isolate each mutation fixture in its own classpath.

Exit0 means declared expectations matched; exit1 is a project/result defect; exit2
means prerequisites or infrastructure prevented complete verification. Ordinary
starter behavior failures alone do not imply a failed verification receipt.
Staging requires a successful complete delivery receipt from the container,
matching delivery/source/inventory hashes and immutable published runtime digests.
Private checks, references, runtime identities and secrets stay outside native/site
payloads. Native import and actual Moodle results need independent live evidence.

Local stack:

```sh
HOST_JOBS_DIR=/absolute/private/jobs \
COURSE1_DIR=/absolute/course-a COURSE2_DIR=/absolute/course-b \
docker compose --project-name prairielearn-local \
  -f compose/compose.yml -f compose/compose.local.yml up -d
```

The local development UI listens on `127.0.0.1:3000`. The PL service receives the
host Docker socket to create isolated grading containers; grading containers do
not receive the socket. Development authentication proves no Moodle identity.
Real native Java import and browser grading have passed locally: compile-invalid keeps three attempts, wrong answer/timeout consume attempts, and a correct third attempt receives 1/1. These tests used the synthetic Dev User with staff override; Student ACL and Moodle login remain pending.

Exact course storage and the local HTTPS proxy are described in [development.md](docs/development.md).

The jobs directory must exist on the Docker host and use an absolute path.
Compose refuses a missing bind source; the entrypoint refuses relative paths.

The Java grading descriptor is `tests/grading-job.json`, schemaVersion1, with
explicit sourceFiles/testFiles, mode, runtime, java, limits, scoring and discovery.
The platform owns the JUnit entrypoint; courses supply trusted suites or declared
mutation fixtures, and never a grading main. Standard PL `/grade/results/results.json`
is retained. Host verification is diagnostic: its JDK25 patch build can differ from
the pinned production container and the receipt records exact toolchain evidence.

Container execution preserves the official root supervisor, unprivileged sbuser,
Landlock and root-owned read-only compiled classpath. Actual tests verify denied
proc reads/trusted writes and unprivileged child processes. Host execution is
explicitly diagnostic. These tested boundaries do not prove containment against
all adversarial reflection within the same JVM.

The private Community assignment/results bridge is documented in
[community-gateway-bridge.md](docs/community-gateway-bridge.md). It uses native
enrollment/label models and actual Student sessions. Its published image pin and
bounded spike evidence are recorded separately from final Gateway/AGS release acceptance.

## Local TLS and future LAN deployment

Use the [repeatable CachyOS certificate quickstart](docs/local-tls.md) on each development laptop. It creates that laptop’s own CA, reuses it on subsequent starts, renews the server certificate, and checks system/NSS trust explicitly. The [Proxmox LAN guide](docs/proxmox-lan-tls.md) covers a static VM IP without DNS and separates the VM HTTPS proxy from the hypervisor management certificate. [Moodle PHP trust setup](https://github.com/Afonenko-Course-Tools/moodle-prairielearn-gateway/pull/1) and [student Windows/macOS/Linux instructions](https://github.com/BSU-RFCT-Afonenko-Courses/Java/pull/8) live in their owner repositories.

Versioned contracts and the reviewed image publication procedure are in
[releasing.md](docs/releasing.md). Runtime images **1.0.0** were published from
`fc5a4d4e9d0795940b8cdf68e30e753ebfd27cec`; [runtime-image.json](runtime-image.json)
records that historical publication. Tool 1.0.1 exposes official JUnit test feedback
and execution-limit messages to the native submission panel, and summarizes expected
mutation outcomes. Raw results and grading policies remain unchanged. The current
`runtime-profiles.json` identifies the exact runner/library hashes; an `image: null`
requires a matching newly published digest before production verification or staging.
`images.lock.json` retains the last published deployment pins. Final release acceptance
uses source and registry receipts for the same runtime; local image IDs are diagnostic.
