# Community bridge

The Platform bridge runs inside the pinned Community image on a separate private
listener. Its source is based on Community commit
`92584fe426ececb84bc2d09de9975c7056c0c5f6`, image digest
`60c675a42055a430f9ad7298c7dfd2f37119aa471f806e21e2c929de28435f63`.
It imports native compiled enrollment/student-label models. Gateway has no database
credentials and never supplies SQL, native label IDs, or PrairieLearn staff roles.
The service uses native system authorization for its narrowly scoped mutations;
it does not assign any privileges to the Moodle teacher or Student.

Run the image with private config/token and read-only validated deliveries.
`compose/compose.gateway.yml` has no bridge host port. The public proxy must include
`proxy/nginx.gateway.conf`; the existing verified handoff callback remains a separate
identity path. Keep PL's HTTP and bridge listeners inaccessible from public clients.
The bearer token is a server credential of at least 32 characters, mounted as a secret.
Browser cookies and trusted identity headers do not authenticate bridge calls.
The bridge rehashes each configured delivery and every inventoried file at startup.
Private settings contain bindings from a delivery directory to a native instance ID;
the UUID in exported instance metadata must match that native instance.

`PUT /internal/gateway/assignments/{id}` accepts the closed request schema in
`schemas/gateway-assignment.schema.json`. Gateway sends only approved/assigned access,
or an explicit revocation (`newWork: null`). It must never call this for pending
requests. A first assignment has version 1 and null oldWork. Every replacement uses
version N+1 with oldWork equal to the previous newWork; identical retries reconcile
native ACL again. Stale/conflicting versions and identity changes fail. An assignment
journal row, enrollment, audit events and native label removal/addition commit in one
Postgres transaction. A per-user/instance advisory lock serializes changes; a unique
constraint prevents a second assignment ID from silently taking the same slot.
All other labels managed by the configured instance are revoked. Unrelated labels
remain. Native blocked enrollments cannot be bypassed.

`GET /internal/gateway/results?assignmentId=ID&version=N` requires the current active
assignment and native joined enrollment with its manifest label. It returns the
closed schema in `schemas/gateway-results.schema.json`; only manifest question IDs
are returned, with the latest attempt by number/ID (not the gradebook best score).
The SQL adapter lives in `bridge/native.sql`; dynamic client SQL is impossible.
Team assessments are excluded. Attempts created before the current assignment grant are excluded, including when a work is assigned again; idempotent retries preserve the activation time. A prior Homework attempt cannot be silently reused for a new grant. Such a workflow needs an explicit reviewed native reset/new-attempt policy before it can produce a new grade. Missing/ungraded questions have no completed credit.
Native question score_percent is normalized to 0..1; points/maxPoints remain visible.
Only exact score 1 on a completed required question contributes to completion.
Optional questions and two partial answers cannot satisfy pass-two-of-three.

The Platform journal persists in the PL database. It is not Gateway's workflow/outbox
store. Cross-delivery reassignment currently fails explicitly: deployment must reconcile
old managed ACL with a reviewed delivery-migration procedure before changing the binding.
Automatic privilege promotion, public write APIs and arbitrary assessment reads are absent.

Verification:

```
node tests/bridge/policy.test.mjs
PL_GATEWAY_BRIDGE_URL=http://private-pl:3001 \
PL_GATEWAY_TOKEN_FILE=/private/token \
PL_GATEWAY_DELIVERY=/private/native/delivery.json \
python3 -m unittest discover -s tests -p test_gateway_acl.py -v
```

The localhost-only patch permits a null cookieDomain in production solely when hostname equals localhost. This emits host-only cookies. Other production host/domain checks and encryption-key validation remain in force; devMode stays false. The patch script refuses a changed upstream guard rather than guessing.

Actual verified Moodle Student sessions passed native list/direct URL/reassignment and real built-in grading in the isolated fixture; production Gateway workflow/AGS integration remains a separate release gate. See the private release report for evidence. A healthy listener or synthetic score row alone cannot satisfy those gates.
