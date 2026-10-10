# Local development

The current dev-PrairieLearn uses a pinned image, development identities and a
loopback-only UI. Real Moodle and production authentication are later stages.

## Native course delivery and storage

Build from a clean source and builder checkout with `tools/build-course.py`.
The builder calls the course's exact installed owner exporter and records
source/builder commits, manifest hashes, content hashes and image refs.
`submission.mode: editor` in the owner binding provides a standard native text
editor. It sends accepted starter source as code, leaving full build files in
the authoring repository. Offline archives and VSCode workspaces are separate
scenarios. The builder does not add ZIPs or rewrite owner submission controls.

Commit generated native files into the public delivery repository, then choose
that exact commit in a `pl-courses-v1` registry:

```json
{"schema":"pl-courses-v1","courses":[{"id":"java-portal","repository":"https://github.com/BSU-RFCT-Afonenko-Courses/pl-course-java","commit":"<exact 40-hex commit>","mount":"/course"}]}
```

The example placeholder is deliberately rejected. Registry validation rejects
moving branches, duplicate IDs/mounts, credential-bearing URLs and missing image
pins before checkout. Stage into an existing private absolute directory:

```sh
python3 tools/check_registry.py /private/courses.json
python3 tools/stage_courses.py /private/courses.json \
  --storage /private/native-courses --compose-output /private/course-mounts.json
HOST_JOBS_DIR=/private/jobs DEV_TLS_DIR=/private/dev-tls \
  docker compose -p prairielearn-local -f compose/compose.yml \
  -f compose/compose.dev.yml -f /private/course-mounts.json \
  -f compose/compose.proxy-dev.yml up -d
```

Each checkout lives at `<storage>/<id>/<commit>`. Staging verifies Git origin,
HEAD, cleanliness, native metadata and provenance hashes, refuses symlinks and
unexpected payload, then publishes without replacing an existing directory.
Repeated staging verifies existing content; an upgrade retains prior versions.
Generated mounts are read-only and refuse absent host directories.

Staging files does not import a course. In the pinned PL dev UI open the navbar
and click **Load from disk**, then wait for **Success** and `Course sync successful`
for each mounted course. JSON changes need another sync; question HTML changes
are loaded on page navigation. Course/instance/assessment/question UUIDs remain
stable across rebuilds and sync. Course enrollment/publishing still need explicit
configuration; staff override does not prove Student ACL or Moodle login.

## HTTPS proxy

Create local-only TLS material once with:

```sh
sh tools/make-dev-tls.sh /private/dev-tls
curl --cacert /private/dev-tls/ca.crt https://localhost:8443/pl/
```

The CA and server keys stay outside Git. The tool refuses to overwrite an
existing directory and does not modify trust stores. To trust it on a test
computer, import **only `ca.crt`** using that computer's normal CA workflow.
The dev certificate covers localhost and 127.0.0.1; the final static server IP
will need its own certificate and configuration.

Nginx binds 127.0.0.1:8443, preserves /pl/ and /socket.io/ paths and supports
WebSocket upgrades. It replaces forwarding headers and strips all three
x-trust-auth-* identity headers. /gateway and /pl/shibcallback return 503 until
the gateway is implemented. Plain port 3000 is also loopback-only for debugging.
This override is development configuration, with PL development identities.

## Verification

```sh
JAVA_HOME=/usr/lib/jvm/java-25-openjdk \
PATH=/usr/lib/jvm/java-25-openjdk/bin:$PATH \
python3 -m unittest discover -s tests -v
DEV_TLS_DIR=/private/dev-tls docker compose -p pl-proxy-check \
  -f compose/compose.proxy-test.yml up -d
PL_PROXY_TEST_CA=/private/dev-tls/ca.crt \
python3 -m unittest discover -s tests -p test_proxy_live.py -v
DEV_TLS_DIR=/private/dev-tls docker compose -p pl-proxy-check \
  -f compose/compose.proxy-test.yml down
```

Storage tests use temporary Git repositories and a verified HTTPS loopback
server. Proxy integration uses a separate synthetic upstream, without the PL
DB, identities or Docker socket. Grading acceptance must also use real PL UI;
unit tests and health checks alone do not establish it.

The shared Java runner compiles its immutable official JUnit adapter once per job.
Each mutation variant still independently compiles trusted fixtures and submitted
tests into separate directories, then runs in a fresh JVM under the existing
sbuser/Landlock boundary. No compiled submitted artifacts are reused across APIs.
Each fresh execution JVM also uses level-one tiered compilation to reduce JUnit
startup cost. Compilation invokes the standard JDK javac main class directly,
with an explicit compiler-version preflight. This avoids the official image javac
launcher module-property mismatch when loading dynamic CDS archives. No warning
output is suppressed. The compiler JVM uses level-one tiered compilation and a job-private dynamic CDS
archive of JDK compiler classes. The first compiler invocation creates that archive
cold; later invocations load it. Annotation processing stays disabled, so submitted
code is parsed rather than executed by the compiler. The supervisor owns the archive
with mode0600 and compiled adapter/libraries with root-owned read-only files; all are
removed at job end. Host uses the same runner and creates its own cold archive.
No compiler process, adapter, or archive is reused across grading jobs. Outer30s,
inner compilation/execution limits, Java25 release, official source and signatures,
scoring policies and typed outcomes are unchanged. runnerCompilation duration is
zero for variants that reuse the adapter; the first successful variant records its
actual cold compilation cost.
