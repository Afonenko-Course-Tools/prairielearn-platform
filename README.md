# PrairieLearn platform

Shared platform for native PrairieLearn courses, with a Java 25 grader.
Implementation is in progress; no deployment or authentication acceptance is claimed.

Java courses require JDK 25 or newer. The reference grader uses a pinned JDK 25.
Runtime credentials, identities, jobs and OpenTofu state belong outside this checkout.
The current pilot excludes backup and restore workflows.

Local verification:

```sh
JAVA_HOME=/usr/lib/jvm/java-25-openjdk PATH=/usr/lib/jvm/java-25-openjdk/bin:$PATH python3 -m unittest discover -s tests -v
```

Build a native course from a clean source checkout:

```sh
python3 tools/build-course.py --source /path/to/source \
  --config /path/to/source/prairielearn/export.json \
  --output /path/to/fresh-delivery
```

The `pl-source-v1` config selects one native book, explicit work bindings and a
native shell. The builder calls its installed owner exporter, rejects unsafe
paths, symlinks, conflicting questions, missing assessment QIDs and UUID
collisions, then publishes the complete tree and content hashes. It preserves
native scoring policy exactly as authored. Existing outputs are rejected.
Provenance records source/builder commits, source manifests, image locks and
whether the builder checkout was dirty; accepted deliveries use clean commits.

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

The Java grader contract lists allowed `sourceFiles`, trusted `mainClass`,
and nonempty `requiredMethods` records (`className`, `methodName`, JVM method
`descriptor`, and boolean `static`). Missing or incompatible public methods are
invalid submissions. Trusted tests return normally on success, exit 1 for a
student failure and exit 2 for an internal failure. The runner requires evidence
that tests returned, preventing premature `System.exit(0)` from earning credit.
This is not a security boundary against adversarial code in the same JVM; stronger
exam integrity requires a separate process protocol for trusted checks.
