# Local TLS on a new laptop

Each development laptop creates its own private local CA. Repeated setup on that
laptop reuses that CA and renews only its leaf certificate when necessary. Do not
copy another developer's `ca.key` or `server.key`; this guide needs no existing
runtime directory, machine-specific path, account or source commit.

The supported and verified local development host is **CachyOS / Arch Linux**.
Use Python **3.9 or newer**, **OpenSSL 3 or newer**, NSS `certutil` (Arch package
`nss`) for browser trust, and the Docker/Compose dependencies of the local stack.
The CLI's Debian/Ubuntu trust-store paths are also tested with offline fixtures;
that does not claim a deployed runtime test on those distributions.

This guide makes the local setup reproducible on another CachyOS laptop. Student
browsers on Linux, Windows and macOS are a separate client workflow; development
bootstrap here does not install software or private keys on students' computers.

From a fresh Platform checkout, choose an absolute private path **outside Git**.
This example lives in your own home directory. Keep it on a filesystem that
enforces owner-only key permissions:

```sh
TASK_PRIVATE="$HOME/.local/share/prairielearn-dev"
install -d -m 700 "$TASK_PRIVATE"
export DEV_TLS_DIR="$TASK_PRIVATE/dev-tls"
sh tools/make-dev-tls.sh "$DEV_TLS_DIR"
python3 tools/dev-tls.py check --directory "$DEV_TLS_DIR"
openssl x509 -in "$DEV_TLS_DIR/ca.crt" -noout -sha256 -fingerprint
```

`make-dev-tls.sh` is a one-command certificate bootstrap and maintenance wrapper.
Run it again to verify/reuse the same identity before Compose starts. It defaults
to localhost and 127.0.0.1, so one certificate covers the local Moodle, Gateway and
PrairieLearn proxy URLs on different ports. Keep `DEV_TLS_DIR` consistent across
all proxy overrides. Compose needs its other private jobs/course settings too;
certificate setup does not generate identities or start services.

Pin the verified public CA fingerprint for routine startup/renewal:

```sh
TASK_CA_SHA256="$(openssl x509 -in "$DEV_TLS_DIR/ca.crt" -noout -sha256 -fingerprint | cut -d= -f2)"
sh tools/make-dev-tls.sh "$DEV_TLS_DIR" --expect-ca-sha256 "$TASK_CA_SHA256"
python3 tools/dev-tls.py check --directory "$DEV_TLS_DIR" \
  --expect-ca-sha256 "$TASK_CA_SHA256"
```

Persist that public fingerprint in the laptop's private configuration. Deriving it
again each time is inspection, not a safeguard against unexpected CA replacement.
A fingerprint pin with missing/different CA fails instead of rotating identity.
No trust store, service or browser policy is changed by certificate setup.

## Trust once for this computer and browser user

Review the fingerprint above. On supported Linux:

```sh
python3 tools/dev-tls.py trust --directory "$DEV_TLS_DIR" \
  --store system --system auto --action plan
sudo python3 tools/dev-tls.py trust --directory "$DEV_TLS_DIR" \
  --store system --system auto --action install --expect-ca-sha256 "$TASK_CA_SHA256"
python3 tools/dev-tls.py trust --directory "$DEV_TLS_DIR" \
  --store system --system auto --action check --expect-ca-sha256 "$TASK_CA_SHA256"
```

If your laptop uses graphical administrator authentication, use `pkexec
/usr/bin/python3` instead of `sudo python3`, from the checkout's absolute tool
path. The CLI does not escalate itself. System check verifies the generated OS CA
bundle. It reuses an existing same-certificate anchor under an operator's filename.

Close the browser before installing into its existing database. Use your actual
absolute user/profile paths. For example, a shared Linux NSS database:

```sh
if [ -d "$HOME/.pki/nssdb" ]; then
  TASK_NSS_DB="$HOME/.pki/nssdb"
else
  TASK_NSS_DB="$HOME/.local/share/pki/nssdb"
fi
python3 tools/dev-tls.py trust --directory "$DEV_TLS_DIR" \
  --store nss --nss-db "$TASK_NSS_DB" --action plan
python3 tools/dev-tls.py trust --directory "$DEV_TLS_DIR" \
  --store nss --nss-db "$TASK_NSS_DB" --action install --expect-ca-sha256 "$TASK_CA_SHA256"
python3 tools/dev-tls.py trust --directory "$DEV_TLS_DIR" \
  --store nss --nss-db "$TASK_NSS_DB" --action check --expect-ca-sha256 "$TASK_CA_SHA256"
```

Firefox may use a different database. Set `--store firefox --firefox-root
"$HOME/.mozilla/firefox"` to read its `profiles.ini`, or select only initialized
profiles by running a separate `--store nss --nss-db /absolute/profile` command for each. Missing
`cert9.db` is reported and never created; initialize your intended browser profile
normally or choose its actual initialized database. Trust is SSL-only (`C,,`).
Matching certificates are reused by fingerprint regardless of their existing NSS
nickname. Run browser commands as the browser user, without sudo.

Restart the browser and open the real local URLs. An existing process may retain
old trust state even after a successful store check. After proxy startup, ordinary
`curl https://localhost:8443/pl/` should verify TLS using OS trust. Use the actual
Moodle/PL port configured in your deployment, then test the browser too. Explicit
`curl --cacert "$DEV_TLS_DIR/ca.crt" ...` is useful to distinguish server-chain
problems from missing OS trust; it does not prove browser/system trust.

## Repeated maintenance and another network address

At each local startup, repeat the same wrapper command with the pinned CA and
complete SAN list. A periodic administrator maintenance task can run that command
before the default 30-day renewal window ends. No scheduler or Codex heartbeat is
created by this workflow. If the JSON says `action=renewed`, run `nginx -t` and an
explicit graceful reload for every proxy sharing the TLS directory, then verify
normal-trust HTTPS. The [development guide](development.md#repeatable-startup-and-leaf-renewal)
has Compose examples. Trust does not need reinstalling when only the leaf renews.

To use a laptop/VM static LAN IP, add explicit `--ip YOUR_STATIC_IP` to every
ensure/check command; localhost/127.0.0.1 remain included. `--dns` is optional and
only works when that name resolves appropriately. No DNS is needed for an IP SAN.
This local laptop CA is separate from a later institutional LAN CA. Future server
trust policy and Proxmox deployment are separate operator decisions. Never disable
peer/hostname verification to accommodate an address change.

Tests, using synthetic private material and temporary real NSS/system roots:

```sh
python3 -m unittest discover -s tests -p test_dev_tls.py -v
sh -n tools/make-dev-tls.sh
```

See the [LAN/Proxmox deployment guide](proxmox-lan-tls.md), [Moodle PHP TLS client setup](https://github.com/Afonenko-Course-Tools/moodle-prairielearn-gateway/pull/1), and [student Windows/macOS/Linux guide](https://github.com/BSU-RFCT-Afonenko-Courses/Java/pull/8).
