#!/usr/bin/env python3
"""Maintain a private local CA/leaf pair; trust installation is always explicit."""
import argparse
import configparser
import contextlib
try:
    import fcntl
except ImportError:  # Unsupported native Windows can still display CLI help.
    fcntl = None
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile


class TLSError(Exception):
    pass


def execute(*args, allow_failure=False):
    try:
        p = subprocess.run([str(x) for x in args], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TLSError(str(e)) from e
    if p.returncode and not allow_failure:
        raise TLSError(p.stderr.decode(errors='replace').strip() or 'Command failed: ' + str(args[0]))
    return p


def openssl(*args, **kwargs):
    return execute('openssl', *args, **kwargs)


def absolute_path(value):
    p = Path(value)
    if not p.is_absolute():
        raise TLSError('Use an absolute path')
    # Reject symlink aliases before resolving; a renewal must address one identity.
    for q in (p, *p.parents):
        if q.is_symlink():
            raise TLSError('Symlink paths are not accepted: ' + str(q))
    return p.resolve(strict=False)


def outside_git(p):
    for q in (p, *p.parents):
        if (q / '.git').is_file() or (q / '.git/HEAD').is_file():
            raise TLSError('TLS material must be outside every Git checkout: ' + str(p))


def fingerprint(cert):
    return hashlib.sha256(openssl('x509', '-in', cert, '-outform', 'DER').stdout).hexdigest()


def pin_identity(cert, expected):
    actual = fingerprint(cert)
    if expected:
        pin = expected.replace(':', '').lower()
        if not re.fullmatch('[0-9a-f]{64}', pin) or pin != actual:
            raise TLSError('CA SHA256 identity mismatch; refusing rotation or trust installation')
    return actual


def public_key(path, private=False):
    if private:
        return openssl('pkey', '-in', path, '-pubout', '-outform', 'DER').stdout
    pub = openssl('x509', '-in', path, '-pubkey', '-noout').stdout
    with tempfile.TemporaryDirectory(prefix='local-tls-public-') as tmp:
        pem = Path(tmp) / 'public.pem'
        pem.write_bytes(pub)
        return openssl('pkey', '-pubin', '-in', pem, '-outform', 'DER').stdout


def valid_ca(cert, expected=None):
    if not cert.is_file() or cert.is_symlink():
        raise TLSError('Missing regular CA certificate: ' + str(cert))
    if not re.fullmatch(rb'\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*', cert.read_bytes()):
        raise TLSError('Expected one public PEM CA certificate without private keys or other payload')
    actual = pin_identity(cert, expected)
    constraints = openssl('x509', '-in', cert, '-noout', '-ext', 'basicConstraints').stdout.decode()
    usage = openssl('x509', '-in', cert, '-noout', '-ext', 'keyUsage').stdout.decode()
    identity = openssl('x509', '-in', cert, '-noout', '-subject', '-issuer', '-nameopt', 'RFC2253').stdout.decode().splitlines()
    if 'CA:TRUE' not in constraints or 'Certificate Sign' not in usage:
        raise TLSError('Certificate is not a signing CA')
    if len(identity) != 2 or identity[0].removeprefix('subject=') != identity[1].removeprefix('issuer='):
        raise TLSError('Expected a self-signed local CA')
    openssl('verify', '-CAfile', cert, '-check_ss_sig', cert)
    return actual


def secure_material(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise TLSError('TLS directory must be a regular private directory')
    if directory.stat().st_mode & 0o077:
        raise TLSError('TLS directory must have mode 0700')
    for name in ('ca.crt', 'ca.key', 'server.crt', 'server.key'):
        p = directory / name
        if not p.is_file() or p.is_symlink():
            raise TLSError('Partial TLS material: missing regular ' + name + '; restore the intended material, do not rotate the CA')
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o022 or (name.endswith('.key') and mode & 0o077):
            raise TLSError(name + ' has unsafe permissions; keys require mode 0600')
        if p.stat().st_uid != os.geteuid() and os.geteuid() != 0:
            raise TLSError('TLS files must be owned by the invoking user')


def sans(args):
    dns = {'localhost'}
    ips = {'127.0.0.1'}
    for value in args.dns:
        if not re.fullmatch(r'(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value):
            raise TLSError('Invalid DNS SAN: ' + repr(value))
        if any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', x) for x in value.split('.')):
            raise TLSError('Invalid DNS SAN: ' + repr(value))
        dns.add(value.lower())
    for value in args.ip:
        try:
            ips.add(str(ipaddress.ip_address(value)))
        except ValueError as e:
            raise TLSError('Invalid IP SAN: ' + repr(value)) from e
    return sorted('DNS:' + x for x in dns) + sorted('IP:' + x for x in ips)


def certificate_sans(cert):
    value = openssl('x509', '-in', cert, '-noout', '-ext', 'subjectAltName').stdout.decode()
    found = []
    for entry in ''.join(value.splitlines()[1:]).split(','):
        entry = entry.strip()
        if entry.startswith('DNS:'):
            found.append(entry)
        elif entry.startswith('IP Address:'):
            found.append('IP:' + str(ipaddress.ip_address(entry.removeprefix('IP Address:'))))
        elif entry:
            raise TLSError('Unexpected SAN type in existing leaf: ' + entry)
    return sorted(found)


def verify_pair(directory, expected=None):
    secure_material(directory)
    identity = valid_ca(directory / 'ca.crt', expected)
    for prefix in ('ca', 'server'):
        if public_key(directory / (prefix + '.key'), True) != public_key(directory / (prefix + '.crt')):
            raise TLSError(prefix + ' certificate/key mismatch; active material is unchanged')
    # Validate the signature and purpose independently of leaf expiry. An expired
    # but authentic leaf may be renewed; invalid CA validity is rejected above.
    openssl('verify', '-CAfile', directory / 'ca.crt', '-purpose', 'sslserver', '-no_check_time', directory / 'server.crt')
    return identity


def leaf_needed(directory, wanted, days):
    cert = directory / 'server.crt'
    reasons = []
    if certificate_sans(cert) != sorted(wanted):
        reasons.append('SAN changed')
    if openssl('x509', '-in', cert, '-checkend', days * 86400, '-noout', allow_failure=True).returncode:
        reasons.append('leaf expires within renewal window')
    if openssl('verify', '-CAfile', directory / 'ca.crt', '-purpose', 'sslserver', cert, allow_failure=True).returncode:
        reasons.append('leaf is not currently valid')
    return reasons


def sign_leaf(directory, key, output, wanted, days):
    with tempfile.TemporaryDirectory(prefix='.leaf-stage-', dir=directory) as tmp:
        tmp = Path(tmp)
        csr, ext = tmp / 'server.csr', tmp / 'server.ext'
        ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=' + ','.join(wanted) + '\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
        openssl('req', '-new', '-key', key, '-out', csr, '-subj', '/CN=localhost')
        # Random serial avoids touching the persistent CA serial during a failure.
        openssl('x509', '-req', '-in', csr, '-CA', directory / 'ca.crt', '-CAkey', directory / 'ca.key',
                '-set_serial', '0x' + secrets.token_hex(20), '-days', days, '-sha256', '-extfile', ext, '-out', output)
    openssl('verify', '-CAfile', directory / 'ca.crt', '-purpose', 'sslserver', output)
    if public_key(key, True) != public_key(output) or certificate_sans(output) != sorted(wanted):
        raise TLSError('Staged leaf failed key/SAN validation')


def fsync_file(p):
    with p.open('rb') as f:
        os.fsync(f.fileno())


def fsync_dir(p):
    fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(directory):
    lock = directory.parent / ('.' + directory.name + '.tls.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.geteuid():
            raise TLSError('TLS lock belongs to another user')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def maintain(args):
    directory = absolute_path(args.directory)
    if directory == Path('/'):
        raise TLSError('Use a private material directory, not the filesystem root')
    outside_git(directory)
    wanted = sans(args)
    if not 1 <= args.leaf_days <= 3650 or not 0 <= args.renew_before_days < args.leaf_days:
        raise TLSError('Require 0 <= renew-before-days < leaf-days <= 3650')
    if not directory.parent.is_dir():
        raise TLSError('Create the private parent directory first')
    if args.command == 'check':
        identity = verify_pair(directory, args.expect_ca_sha256)
        reasons = leaf_needed(directory, wanted, args.renew_before_days)
        if reasons:
            raise TLSError('Renewal required: ' + '; '.join(reasons) + '; run ensure with the same SANs')
        return report(directory, identity, 'unchanged', wanted)
    with locked(directory):
        if directory.exists():
            identity = verify_pair(directory, args.expect_ca_sha256)
            reasons = leaf_needed(directory, wanted, args.renew_before_days)
            action = 'unchanged'
            if reasons:
                # Reuse the leaf key, so one atomic certificate rename preserves
                # a matching cert/key pair even for concurrent readers.
                with tempfile.TemporaryDirectory(prefix='.renew-', dir=directory) as tmp:
                    staged = Path(tmp) / 'server.crt'
                    sign_leaf(directory, directory / 'server.key', staged, wanted, args.leaf_days)
                    fsync_file(staged)
                    os.replace(staged, directory / 'server.crt')
                    fsync_dir(directory)
                action = 'renewed'
        else:
            if args.expect_ca_sha256:
                raise TLSError('Pinned CA is absent; restore it instead of creating a different CA')
            with tempfile.TemporaryDirectory(prefix='.' + directory.name + '.stage-', dir=directory.parent) as tmp:
                stage = Path(tmp) / 'material'
                stage.mkdir(mode=0o700)
                openssl('req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '3650',
                        '-keyout', stage / 'ca.key', '-out', stage / 'ca.crt', '-subj', '/CN=PrairieLearn local development CA',
                        '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0', '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-addext', 'subjectKeyIdentifier=hash')
                openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', stage / 'server.key')
                sign_leaf(stage, stage / 'server.key', stage / 'server.crt', wanted, args.leaf_days)
                identity = verify_pair(stage)
                for path in stage.iterdir():
                    fsync_file(path)
                fsync_dir(stage)
                os.rename(stage, directory)
                fsync_dir(directory.parent)
                action = 'created'
        return report(directory, identity, action, wanted)


def report(directory, identity, action, wanted):
    return {'status': 'valid', 'action': action, 'directory': str(directory), 'caSha256': identity,
            'leafSha256': fingerprint(directory / 'server.crt'), 'sans': wanted,
            'dates': openssl('x509', '-in', directory / 'server.crt', '-noout', '-dates').stdout.decode().splitlines(),
            'trustInstalledAutomatically': False,
            'reloadRequired': action == 'renewed',
            'nextStep': 'If renewed, reload each proxy using this directory after nginx -t; CA trust is unchanged.'}


def atomic_public_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.ca-', dir=destination.parent, delete=False) as tmp:
        staged = Path(tmp.name)
        try:
            tmp.write(source.read_bytes())
            tmp.flush()
            os.fsync(tmp.fileno())
            staged.chmod(0o644)
            os.replace(staged, destination)
            fsync_dir(destination.parent)
        finally:
            staged.unlink(missing_ok=True)


def system_store(args, cert, identity):
    root = absolute_path(args.system_root)
    if root == Path('/') and not sys.platform.startswith('linux'):
        raise TLSError('Automatic system trust supports Linux Arch/Debian; use the documented macOS/Windows trust workflow')
    family = args.system
    if family == 'auto':
        release = root / 'etc/os-release'
        text = release.read_text().lower() if release.is_file() else ''
        if 'arch' in text or 'cachyos' in text or 'manjaro' in text:
            family = 'arch'
        elif 'debian' in text or 'ubuntu' in text:
            family = 'debian'
        else:
            raise TLSError('Select --system arch or --system debian explicitly')
    if family == 'arch':
        anchor = root / 'etc/ca-certificates/trust-source/anchors/prairielearn-local-ca.crt'
        bundle = root / 'etc/ssl/cert.pem'
        update = ['update-ca-trust', 'extract']
    else:
        anchor = root / 'usr/local/share/ca-certificates/prairielearn-local-ca.crt'
        bundle = root / 'etc/ssl/certs/ca-certificates.crt'
        update = ['update-ca-certificates']
    absolute_path(anchor)
    if root != Path('/'):
        outside_git(root)
    installed = anchor.exists()
    if installed and fingerprint(anchor) != identity:
        raise TLSError('Existing system trust anchor has another identity; refusing replacement')
    if not installed and anchor.parent.is_dir():
        for candidate in sorted(anchor.parent.iterdir()):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            try:
                if fingerprint(candidate) == identity:
                    anchor, installed = candidate, True
                    break
            except TLSError:
                continue
    trusted = installed and bundle.is_file() and not openssl('verify', '-CAfile', bundle, cert, allow_failure=True).returncode
    result = {'store': 'system', 'system': family, 'anchor': str(anchor), 'bundle': str(bundle), 'trusted': bool(trusted),
              'status': 'trusted' if trusted else 'not-trusted', 'updateCommand': update,
              'installCommand': ['sudo', 'python3', str(Path(__file__).resolve()), 'trust', '--directory', args.directory, '--store', 'system', '--system', family, '--system-root', str(root), '--action', 'install',
                                 *(['--expect-ca-sha256', args.expect_ca_sha256] if args.expect_ca_sha256 else [])]}
    if args.action == 'install' and not trusted:
        if root == Path('/') and os.geteuid() != 0:
            raise TLSError('System trust needs administrator rights. Run explicitly: ' + shlex.join(['sudo', 'python3', str(Path(__file__).resolve()), *sys.argv[1:]]) + '\nAlternatively use pkexec instead of sudo.')
        if root == Path('/') and not shutil.which(update[0]):
            raise TLSError('Missing system CA updater: ' + update[0])
        if not installed:
            atomic_public_copy(cert, anchor)
        if root == Path('/'):
            execute(*update)
            trusted = bundle.is_file() and not openssl('verify', '-CAfile', bundle, cert, allow_failure=True).returncode
            if not trusted:
                raise TLSError('System updater ran but CA is not trusted; inspect its bundle')
            result.update(trusted=True, status='trusted')
        else:
            result.update(status='staged', trusted=False,
                          nextStep='Offline root only: run the updater inside that OS; no host updater was executed.')
    return result


def nss_directories(args):
    if args.store == 'nss':
        if not args.nss_db:
            raise TLSError('Pass explicit --nss-db directories for the intended browser user')
        return [absolute_path(x) for x in args.nss_db]
    if not args.firefox_root:
        raise TLSError('Pass explicit --firefox-root for the intended user; close Firefox before installing')
    root = absolute_path(args.firefox_root)
    config = configparser.ConfigParser()
    config.read(root / 'profiles.ini')
    dirs = []
    for section in config.sections():
        if section.startswith('Profile') and config.has_option(section, 'Path'):
            raw = config.get(section, 'Path')
            p = root / raw if config.get(section, 'IsRelative', fallback='1') == '1' else Path(raw)
            dirs.append(absolute_path(p))
    if not dirs:
        raise TLSError('No Firefox profiles found; use its actual profiles.ini or explicit --store nss --nss-db')
    return list(dict.fromkeys(dirs))


def nss_store(args, cert, identity, directory):
    if not (directory / 'cert9.db').is_file():
        raise TLSError('Existing NSS cert9.db required; refusing to create a browser profile: ' + str(directory))
    db = 'sql:' + str(directory)
    nickname = 'PrairieLearn local CA ' + identity
    entries = []
    for line in execute('certutil', '-L', '-d', db).stdout.decode().splitlines():
        match = re.fullmatch(r'(.+?)\s+([A-Za-z]*,[A-Za-z]*,[A-Za-z]*)\s*', line)
        if match:
            entries.append((match.group(1), match.group(2)))
    trusted, found = False, False
    with tempfile.TemporaryDirectory(prefix='local-tls-nss-cert-') as tmp:
        copy = Path(tmp) / 'ca.crt'
        for alias, attributes in entries:
            exported = execute('certutil', '-L', '-d', db, '-n', alias, '-a')
            copy.write_bytes(exported.stdout)
            actual = fingerprint(copy)
            if alias == nickname and actual != identity:
                raise TLSError('NSS nickname identity mismatch; refusing replacement')
            if actual == identity:
                candidate_trusted = 'C' in attributes.split(',')[0]
                if not found or candidate_trusted:
                    nickname, found, trusted = alias, True, candidate_trusted
                if trusted:
                    break
    result = {'store': args.store, 'directory': str(directory), 'nickname': nickname, 'trusted': trusted,
              'status': 'trusted' if trusted else 'not-trusted'}
    if args.action == 'install' and not trusted:
        if any(os.path.lexists(directory / name) for name in ('.parentlock', 'parent.lock')):
            raise TLSError('Close Firefox before modifying its certificate database: ' + str(directory))
        # SSL CA trust only. Reuse an operator's existing alias by fingerprint.
        if found:
            execute('certutil', '-M', '-d', db, '-n', nickname, '-t', 'C,,')
        else:
            execute('certutil', '-A', '-d', db, '-n', nickname, '-t', 'C,,', '-i', cert)
        result = nss_store(argparse.Namespace(**{**vars(args), 'action': 'check'}), cert, identity, directory)
        if not result['trusted']:
            raise TLSError('NSS import did not establish SSL CA trust')
    return result


def trust(args):
    directory = absolute_path(args.directory)
    source = directory / 'ca.crt'
    if not source.is_file() or source.is_symlink():
        raise TLSError('Missing regular CA certificate: ' + str(source))
    # Use one immutable public-certificate snapshot for validation and every
    # store operation, including a privileged system invocation.
    with tempfile.TemporaryDirectory(prefix='local-tls-trust-') as tmp:
        cert = Path(tmp) / 'ca.crt'
        cert.write_bytes(source.read_bytes())
        identity = valid_ca(cert, args.expect_ca_sha256)
        if args.store == 'system':
            stores = [system_store(args, cert, identity)]
        else:
            directories = nss_directories(args)
            # Preflight every selected profile before changing any one of them.
            for db in directories:
                absolute_path(db / 'cert9.db')
                if not (db / 'cert9.db').is_file():
                    raise TLSError('Existing NSS cert9.db required: ' + str(db))
                state = nss_store(argparse.Namespace(**{**vars(args), 'action': 'plan'}), cert, identity, db)
                if args.action == 'install' and not state['trusted'] and any(os.path.lexists(db / name) for name in ('.parentlock', 'parent.lock')):
                    raise TLSError('Close Firefox before modifying its certificate database: ' + str(db))
            stores = [nss_store(args, cert, identity, db) for db in directories]
    result = {'action': args.action, 'caSha256': identity, 'stores': stores,
              'status': 'trusted' if all(s['trusted'] for s in stores) else 'not-trusted'}
    if args.action == 'check' and result['status'] != 'trusted':
        print(json.dumps(result, indent=2))
        raise TLSError('CA is not trusted in every selected store; run explicit trust --action install')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('ensure', 'check', 'trust'):
        p = sub.add_parser(name)
        p.add_argument('--directory', required=True, help='absolute private directory outside Git')
        p.add_argument('--expect-ca-sha256', help='pin an existing CA identity; colon-separated fingerprints accepted')
        if name != 'trust':
            p.add_argument('--dns', action='append', default=[], help='additional DNS SAN; localhost always included')
            p.add_argument('--ip', action='append', default=[], help='additional IPv4/IPv6 SAN; 127.0.0.1 always included')
            p.add_argument('--leaf-days', type=int, default=365)
            p.add_argument('--renew-before-days', type=int, default=30)
        else:
            p.add_argument('--store', choices=['system', 'nss', 'firefox'], required=True)
            p.add_argument('--action', choices=['plan', 'check', 'install'], default='plan')
            p.add_argument('--system', choices=['auto', 'arch', 'debian'], default='auto')
            p.add_argument('--system-root', default='/', help='offline staging root; non-/ never invokes the host updater')
            p.add_argument('--nss-db', action='append', default=[])
            p.add_argument('--firefox-root')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if not sys.platform.startswith('linux') or fcntl is None or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
            raise TLSError('Local certificate maintenance requires the supported Linux development host; student-browser trust is a separate client workflow')
        version = openssl('version').stdout.decode()
        if not re.match(r'OpenSSL [3-9]\.', version):
            raise TLSError('OpenSSL 3 or newer is required; put that openssl executable on PATH')
        result = trust(args) if args.command == 'trust' else maintain(args)
        print(json.dumps(result, indent=2))
        return 0
    except (TLSError, OSError, ValueError, configparser.Error) as e:
        print('TLS: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
