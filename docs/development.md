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

For a fresh laptop, start with [the portable local TLS quickstart](local-tls.md).

Use one private CA for the local sites and Moodle proxy, with the same absolute
`DEV_TLS_DIR` in every relevant proxy configuration. Ports do not affect the
certificate identity. Python 3.9+ and OpenSSL 3+ are required; browser stores also need
NSS `certutil` (`nss` on Arch, `libnss3-tools` on Debian).

Create material, or verify/reuse the existing directory:

```sh
sh tools/make-dev-tls.sh /private/dev-tls
python3 tools/dev-tls.py check --directory /private/dev-tls
curl --cacert /private/dev-tls/ca.crt https://localhost:8443/pl/
```

The shell command now wraps `ensure`: repeating it keeps the CA, server key and
unexpired matching leaf unchanged. CA identity is never silently rotated. The
private parent directory must already exist and the output must be outside Git.
The material directory requires mode0700; keys require owner-only permissions.
Existing legacy flat `ca.crt`, `ca.key`, `server.crt`, `server.key` directories are
accepted. Missing/partial files, mismatched keys, invalid CA, unsafe permissions,
symlink aliases and invalid SANs fail without replacing active material.

`localhost` and `127.0.0.1` are always SANs. Add a static VM IP or local names with
repeatable options, using the same full list on every check/ensure:

```sh
python3 tools/dev-tls.py ensure --directory /private/dev-tls \
  --ip 192.168.50.20 --dns moodle.local \
  --expect-ca-sha256 '<verified existing CA SHA256 fingerprint>'
python3 tools/dev-tls.py check --directory /private/dev-tls \
  --ip 192.168.50.20 --dns moodle.local \
  --expect-ca-sha256 '<verified existing CA SHA256 fingerprint>'
```

Replace the illustrative IP/name and fingerprint with the configured values.
DNS is optional: a private LAN VM can use its static IP in an IP SAN. Obtain the
CA fingerprint through `openssl x509 -in /private/dev-tls/ca.crt -noout -sha256
-fingerprint` and verify it before establishing trust. Colons/case are accepted
by `--expect-ca-sha256`. If a pinned CA is missing, ensure refuses to create a new
one. Retain the existing CA/key; a deliberate CA replacement uses a new private
directory and a separate explicit trust rollout.

`ensure` renews the leaf when SANs change, the leaf is expired/not yet valid, or it
expires within 30 days (`--renew-before-days`; leaf lifetime defaults to 365 days).
It validates a staged certificate, reuses the server key, then atomically renames
only `server.crt`. Readers therefore retain a matching cert/key pair. Fresh
creation publishes the complete validated directory atomically. A signing failure
leaves existing active material unchanged. A process lock serializes ensure calls.
JSON reports `action`, CA/leaf SHA256 fingerprints, SANs, validity dates and
`reloadRequired`. It never installs trust, executes sudo or reloads services.

### Explicit computer and browser trust

Install only the public `ca.crt`. A CA grants trust for certificates it signs, so
keep `ca.key` private. System trust and browser databases are separate targets.
The commands default to `plan`; `check` is read-only and exits nonzero unless every
selected store trusts this exact CA. Installation needs explicit `--action
install`. Existing matching aliases/anchors are reused by fingerprint; conflicting
identities under the tool's own anchor name are not overwritten.

```sh
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store system --system auto --action plan
sudo python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store system --system auto --action install
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store system --system auto --action check
curl https://localhost:8443/pl/
```

Run the installation explicitly with `pkexec /usr/bin/python3 ...` if the computer
uses graphical administrator authentication. The tool prints an administrator
follow-up when permission is missing; it does not prompt or escalate itself.
Arch/CachyOS uses `/etc/ca-certificates/trust-source/anchors` and
`update-ca-trust extract`; Debian/Ubuntu uses `/usr/local/share/ca-certificates` and
`update-ca-certificates`. The check verifies the generated system CA bundle,
not just the presence of a copied anchor. `--system-root /absolute/offline-root`
only stages an anchor and reports **staged**, never trusted, until that OS's bundle
is updated; it never runs the host updater for an offline root.

Close the relevant browsers, then install for the intended user's existing NSS
store or Firefox profiles **as that user**, not under sudo:

```sh
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store nss --nss-db /home/USER/.pki/nssdb --action plan
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store nss --nss-db /home/USER/.pki/nssdb --action install
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store nss --nss-db /home/USER/.pki/nssdb --action check
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store firefox --firefox-root /home/USER/.mozilla/firefox --action plan
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store firefox --firefox-root /home/USER/.mozilla/firefox --action install
python3 tools/dev-tls.py trust --directory /private/dev-tls \
  --store firefox --firefox-root /home/USER/.mozilla/firefox --action check
```

Replace USER with the actual account. Firefox discovery reads that root's
`profiles.ini`; it never creates missing profiles or certificate databases. If a
listed profile has no `cert9.db`, choose the actual initialized profile explicitly
with `--store nss --nss-db /home/USER/.mozilla/firefox/PROFILE`. Repeat `--nss-db` to
select several stores. Every selected database is preflighted before installation.
SSL-only CA trust uses `C,,`; email and code-signing trust are omitted. Browser
trust checks examine certificate identity and SSL trust flags. Restart existing
browser processes after installation and open the actual Moodle/PL URL; an NSS
check alone does not establish that an already-running browser has reloaded trust.
The CLI does not change browser policies or bypass TLS errors.

Moodle/PHP, Node and other runtime clients may use their own CA configuration.
Configure their normal CA bundle to include the public local CA alongside their
usual roots, then restart that client as required by its deployment. Browser trust
does not configure a container's PHP. Keep peer/hostname verification enabled.

### Repeatable startup and leaf renewal

Run the same `ensure` command with the pinned CA and full SAN list before starting
or updating the local stack. Run it periodically (for example, an administrator's
monthly systemd timer) so the 30-day window renews the leaf before expiry. Trust
installation is a one-time explicit step per computer/browser profile; leaf renewal
under the same CA does not require reimporting trust.

After `action=renewed`, validate and reload **each** proxy using this TLS directory.
The existing directory bind mounts make the atomic new leaf visible to Nginx:

```sh
DEV_TLS_DIR=/private/dev-tls docker compose -p prairielearn-local \
  -f compose/compose.yml -f compose/compose.dev.yml -f compose/compose.proxy-dev.yml \
  exec -T proxy nginx -t
DEV_TLS_DIR=/private/dev-tls docker compose -p prairielearn-local \
  -f compose/compose.yml -f compose/compose.dev.yml -f compose/compose.proxy-dev.yml \
  exec -T proxy nginx -s reload
```

Use the deployment's actual project, compose files and proxy service; include
its course mounts/other overrides as needed. A local systemd oneshot can run the
fixed `ensure` command, followed by those explicit `nginx -t` and reload commands;
its timer schedules certificate maintenance, not CA recreation/trust installation.
No schedule is installed by these tools. If renewal fails, stop the sequence and
keep the running proxy/certificate; inspect the reported cause. Confirm the served
certificate and normal-trust HTTPS after a reload. No `curl -k`, disabled peer
verification or ignored certificate errors are part of this workflow.

Primary references: [OpenSSL x509](https://docs.openssl.org/master/man1/openssl-x509/),
[Arch update-ca-trust](https://man.archlinux.org/man/update-ca-trust.8),
[Debian update-ca-certificates](https://manpages.debian.org/bookworm/ca-certificates/update-ca-certificates.8.en.html),
and [NSS certutil](https://nss-crypto.org/reference/security/nss/legacy/tools/certutil/index.html).

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
