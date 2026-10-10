# Local proxy and course storage implementation

The next scope is the current loopback dev-PrairieLearn, after Java authoring
and native grading acceptance. Real Moodle and Proxmox remain later stages.

1. Complete corrected Java export/import and real browser grading; preserve
   actual source, builder and image refs and stable question UUIDs.
2. Validate `pl-courses-v1` registry before any Git/network mutation: unique ids
   and mounts, exact commits, credential-free HTTPS origins, pinned PL/grader.
   Stage each native delivery into `<storage>/<id>/<commit>` with a clean Git
   checkout and atomic publication. Repeated staging verifies existing content;
   switching registry retains previous versions. Emit a deterministic Compose
   mount override; mounts are read-only and do not silently create host paths.
3. Add a pinned Nginx dev proxy with a private local CA certificate for localhost
   and 127.0.0.1. Bind HTTPS only to loopback. Preserve PL paths and WebSockets,
   replace forwarding headers and remove all three trusted identity headers.
   Reject callback and gateway paths until the gateway is implemented; they
   cannot bypass into PL. Keep plain loopback dev access for local diagnostics.
4. Verify registry refusal cases, exact checkout/repeated staging/two namespaces,
   Nginx config, TLS verification using the CA, route/header/WS behavior and
   actual PL through proxy. Document actual sync separately from file staging.
   No Moodle login or production-auth claim is made by this dev proxy.
