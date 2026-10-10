"""Exercise the real TLS CLI with synthetic OpenSSL material and trust stores."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tools/dev-tls.py'


def run(*args):
    return subprocess.run([str(x) for x in args], text=True, capture_output=True)


class DevTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory(prefix='platform-tls-fixture-')
        cls.material = Path(cls.base.name) / 'tls'
        p = run('sh', ROOT / 'tools/make-dev-tls.sh', cls.material)
        if p.returncode:
            raise RuntimeError(p.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='platform tls test ')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'private tls'
        shutil.copytree(self.material, self.directory)
        self.directory.chmod(0o700)

    def cli(self, command, *args):
        return run('python3', CLI, command, '--directory', self.directory, *args)

    def ok(self, p):
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def hashes(self):
        return {n: hashlib.sha256((self.directory / n).read_bytes()).hexdigest()
                for n in ('ca.crt', 'ca.key', 'server.crt', 'server.key')}

    def test_existing_shell_entrypoint_reuses_same_ca_and_leaf(self):
        # A repeat setup must not reject valid material or rotate its identity.
        before = self.hashes()
        p = run('sh', ROOT / 'tools/make-dev-tls.sh', self.directory)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.hashes(), before)

    def test_fresh_creation_is_private_outside_git_and_verifies_ip(self):
        shutil.rmtree(self.directory)
        report = self.ok(self.cli('ensure', '--ip', '192.168.50.20'))
        self.assertEqual(report['action'], 'created')
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        for name in ('ca.key', 'server.key'):
            self.assertEqual((self.directory / name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(run('openssl', 'verify', '-CAfile', self.directory / 'ca.crt',
                             '-verify_ip', '192.168.50.20', self.directory / 'server.crt').returncode, 0)
        self.assertEqual(self.ok(self.cli('check', '--ip', '192.168.50.20'))['status'], 'valid')

    def test_san_change_renews_only_leaf_and_repeated_ensure_is_noop(self):
        before = self.hashes()
        report = self.ok(self.cli('ensure', '--ip', '192.168.50.20'))
        after = self.hashes()
        self.assertEqual(report['action'], 'renewed')
        for key in ('ca.crt', 'ca.key', 'server.key'):
            self.assertEqual(after[key], before[key])
        self.assertNotEqual(after['server.crt'], before['server.crt'])
        self.ok(self.cli('ensure', '--ip', '192.168.50.20'))
        self.assertEqual(self.hashes(), after)

    def test_near_expiry_renews_leaf_without_ca_or_key_rotation(self):
        ext = self.directory / 'server.ext'
        csr = self.directory / 'server.csr'
        self.assertEqual(run('openssl', 'req', '-new', '-key', self.directory / 'server.key',
                            '-out', csr, '-subj', '/CN=localhost').returncode, 0)
        ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n')
        self.assertEqual(run('openssl', 'x509', '-req', '-in', csr, '-CA', self.directory / 'ca.crt',
                            '-CAkey', self.directory / 'ca.key', '-set_serial', '12345', '-days', '1',
                            '-extfile', ext, '-out', self.directory / 'server.crt').returncode, 0)
        before = self.hashes()
        self.assertNotEqual(self.cli('check').returncode, 0)
        self.assertEqual(self.ok(self.cli('ensure'))['action'], 'renewed')
        after = self.hashes()
        self.assertNotEqual(after['server.crt'], before['server.crt'])
        self.assertEqual({k:v for k,v in after.items() if k != 'server.crt'},
                         {k:v for k,v in before.items() if k != 'server.crt'})

    def test_partial_and_mismatched_material_fail_closed(self):
        before = self.hashes()
        original = (self.directory / 'server.key').read_bytes()
        (self.directory / 'server.key').write_bytes((self.directory / 'ca.key').read_bytes())
        p = self.cli('ensure', '--ip', '192.168.50.20')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('key', p.stderr.lower())
        self.assertEqual(self.hashes()['server.crt'], before['server.crt'])
        (self.directory / 'server.key').write_bytes(original)
        (self.directory / 'server.crt').unlink()
        self.assertNotEqual(self.cli('ensure').returncode, 0)
        self.assertFalse((self.directory / 'server.crt').exists())
        self.assertEqual(self.hashes_except_leaf()['ca.crt'], before['ca.crt'])

    def hashes_except_leaf(self):
        return {n: hashlib.sha256((self.directory / n).read_bytes()).hexdigest()
                for n in ('ca.crt', 'ca.key', 'server.key')}

    def test_identity_pin_and_key_permissions_fail_without_writes(self):
        before = self.hashes()
        p = self.cli('ensure', '--expect-ca-sha256', '0' * 64)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.hashes(), before)
        (self.directory / 'ca.key').chmod(0o644)
        self.assertNotEqual(self.cli('ensure').returncode, 0)
        self.assertEqual(self.hashes(), before)

    def test_invalid_san_and_git_output_are_rejected(self):
        before = self.hashes()
        self.assertNotEqual(self.cli('ensure', '--dns', 'localhost\nCA:TRUE').returncode, 0)
        self.assertNotEqual(self.cli('ensure', '--ip', 'not-an-ip').returncode, 0)
        self.assertEqual(self.hashes(), before)
        p = run('python3', CLI, 'ensure', '--directory', ROOT / 'tls-test-forbidden')
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((ROOT / 'tls-test-forbidden').exists())

    def test_damaged_signing_key_preserves_active_leaf_and_key(self):
        # Preflight must reject a damaged signer before touching the active leaf.
        before = self.hashes()
        (self.directory / 'ca.key').write_text('not a key\n')
        self.assertNotEqual(self.cli('ensure', '--ip', '192.168.50.20').returncode, 0)
        self.assertEqual(self.hashes()['server.crt'], before['server.crt'])
        self.assertEqual(self.hashes()['server.key'], before['server.key'])

    def test_readers_keep_old_valid_leaf_during_atomic_replacement(self):
        before = self.hashes()
        with (self.directory / 'server.crt').open('rb') as old:
            old_bytes = old.read()
            self.ok(self.cli('ensure', '--ip', '192.168.50.21'))
            old.seek(0)
            self.assertEqual(old.read(), old_bytes)
        self.assertEqual(self.hashes()['server.key'], before['server.key'])
        self.assertNotEqual(self.hashes()['server.crt'], before['server.crt'])

    def test_ca_key_mismatch_and_symlink_directory_fail_closed(self):
        before = self.hashes()
        (self.directory / 'ca.key').write_bytes((self.directory / 'server.key').read_bytes())
        self.assertNotEqual(self.cli('ensure').returncode, 0)
        self.assertEqual(self.hashes()['ca.crt'], before['ca.crt'])
        link = Path(self.temp.name) / 'alias'
        link.symlink_to(self.directory, target_is_directory=True)
        p = run('python3', CLI, 'ensure', '--directory', link)
        self.assertNotEqual(p.returncode, 0)

    def test_system_parent_symlink_is_rejected_before_copy(self):
        root = Path(self.temp.name) / 'system root'
        elsewhere = Path(self.temp.name) / 'elsewhere'
        root.mkdir(); elsewhere.mkdir()
        (root / 'etc').symlink_to(elsewhere, target_is_directory=True)
        p = self.cli('trust', '--action', 'install', '--store', 'system', '--system', 'arch', '--system-root', str(root))
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_debian_offline_anchor_is_checked_against_real_bundle(self):
        root = Path(self.temp.name) / 'debian root'
        root.mkdir()
        args = ('--store', 'system', '--system', 'debian', '--system-root', str(root))
        self.ok(self.cli('trust', '--action', 'install', *args))
        anchor = root / 'usr/local/share/ca-certificates/prairielearn-local-ca.crt'
        self.assertEqual(anchor.read_bytes(), (self.directory / 'ca.crt').read_bytes())
        bundle = root / 'etc/ssl/certs/ca-certificates.crt'
        bundle.parent.mkdir(parents=True)
        bundle.write_bytes(anchor.read_bytes())
        self.ok(self.cli('trust', '--action', 'check', *args))

    @unittest.skipUnless(shutil.which('certutil'), 'NSS certutil required')
    def test_nss_install_and_check_real_database_are_idempotent(self):
        db = Path(self.temp.name) / 'browser profile'
        db.mkdir()
        self.assertEqual(run('certutil', '-N', '-d', 'sql:' + str(db), '--empty-password').returncode, 0)
        args = ('--store', 'nss', '--nss-db', str(db))
        self.assertNotEqual(self.cli('trust', '--action', 'check', *args).returncode, 0)
        self.ok(self.cli('trust', '--action', 'plan', *args))
        self.assertNotEqual(self.cli('trust', '--action', 'check', *args).returncode, 0)
        self.ok(self.cli('trust', '--action', 'install', *args))
        checked = self.ok(self.cli('trust', '--action', 'check', *args))
        self.assertTrue(checked['stores'][0]['trusted'])
        before = (db / 'cert9.db').read_bytes()
        self.ok(self.cli('trust', '--action', 'install', *args))
        self.assertEqual((db / 'cert9.db').read_bytes(), before)

    @unittest.skipUnless(shutil.which('certutil'), 'NSS certutil required')
    def test_firefox_profiles_are_explicit_and_missing_db_is_not_created(self):
        root = Path(self.temp.name) / 'firefox'
        profile = root / 'profile.default'
        profile.mkdir(parents=True)
        (root / 'profiles.ini').write_text('[Profile0]\nName=default\nIsRelative=1\nPath=profile.default\n')
        self.assertNotEqual(self.cli('trust', '--store', 'firefox', '--firefox-root', str(root), '--action', 'install').returncode, 0)
        self.assertFalse((profile / 'cert9.db').exists())
        self.assertEqual(run('certutil', '-N', '-d', 'sql:' + str(profile), '--empty-password').returncode, 0)
        self.ok(self.cli('trust', '--store', 'firefox', '--firefox-root', str(root), '--action', 'install'))
        self.ok(self.cli('trust', '--store', 'firefox', '--firefox-root', str(root), '--action', 'check'))

    @unittest.skipUnless(shutil.which('certutil'), 'NSS certutil required')
    def test_nss_existing_operator_alias_is_reused_by_fingerprint(self):
        db = Path(self.temp.name) / 'existing browser'
        db.mkdir()
        self.assertEqual(run('certutil', '-N', '-d', 'sql:' + str(db), '--empty-password').returncode, 0)
        self.assertEqual(run('certutil', '-A', '-d', 'sql:' + str(db), '-n', 'Existing operator CA', '-t', 'C,,', '-i', self.directory / 'ca.crt').returncode, 0)
        args = ('--store', 'nss', '--nss-db', str(db))
        before = (db / 'cert9.db').read_bytes()
        result = self.ok(self.cli('trust', '--action', 'check', *args))
        self.assertEqual(result['stores'][0]['nickname'], 'Existing operator CA')
        self.ok(self.cli('trust', '--action', 'install', *args))
        self.assertEqual((db / 'cert9.db').read_bytes(), before)

    def test_existing_system_alias_anchor_is_reused_without_duplicate(self):
        root = Path(self.temp.name) / 'existing system'
        anchors = root / 'etc/ca-certificates/trust-source/anchors'
        anchors.mkdir(parents=True)
        (anchors / 'operator-custom-ca.crt').write_bytes((self.directory / 'ca.crt').read_bytes())
        bundle = root / 'etc/ssl/cert.pem'
        bundle.parent.mkdir(parents=True)
        bundle.write_bytes((self.directory / 'ca.crt').read_bytes())
        args = ('--store', 'system', '--system', 'arch', '--system-root', str(root))
        self.ok(self.cli('trust', '--action', 'check', *args))
        self.ok(self.cli('trust', '--action', 'install', *args))
        self.assertEqual([x.name for x in anchors.iterdir()], ['operator-custom-ca.crt'])

    def test_filesystem_root_is_rejected_as_material_before_lock(self):
        p = run('python3', CLI, 'ensure', '--directory', '/')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('private material directory', p.stderr)

    def test_ca_file_with_private_key_is_rejected_before_public_trust_copy(self):
        root = Path(self.temp.name) / 'offline trust'
        root.mkdir()
        with (self.directory / 'ca.crt').open('ab') as f:
            f.write((self.directory / 'ca.key').read_bytes())
        p = self.cli('trust', '--store', 'system', '--system', 'arch', '--system-root', str(root), '--action', 'install')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(list(root.iterdir()), [])

    def test_default_system_root_plan_is_read_only_and_accepts_root(self):
        # A plan must work with the real default root without installing anything.
        canonical = Path('/etc/ca-certificates/trust-source/anchors/prairielearn-local-ca.crt')
        if canonical.exists():
            self.skipTest('Host has a canonical anchor; conflicting-identity behavior is tested on an offline root')
        report = self.ok(self.cli('trust', '--store', 'system', '--system', 'arch', '--action', 'plan'))
        self.assertEqual(report['action'], 'plan')
        self.assertEqual(report['stores'][0]['bundle'], '/etc/ssl/cert.pem')
        self.assertFalse(canonical.exists())

    def test_system_plan_and_offline_root_do_not_mutate_host(self):
        root = Path(self.temp.name) / 'offline root'
        root.mkdir()
        args = ('--store', 'system', '--system', 'arch', '--system-root', str(root))
        self.ok(self.cli('trust', '--action', 'plan', *args))
        self.assertEqual(list(root.iterdir()), [])
        staged = self.ok(self.cli('trust', '--action', 'install', *args))
        self.assertEqual(staged['stores'][0]['status'], 'staged')
        self.assertFalse(staged['stores'][0]['trusted'])
        anchor = root / 'etc/ca-certificates/trust-source/anchors/prairielearn-local-ca.crt'
        self.assertEqual(anchor.read_bytes(), (self.directory / 'ca.crt').read_bytes())
        self.assertNotEqual(self.cli('trust', '--action', 'check', *args).returncode, 0)
        bundle = root / 'etc/ssl/cert.pem'
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_bytes(anchor.read_bytes())
        self.ok(self.cli('trust', '--action', 'check', *args))
        anchor.write_bytes(b'conflicting existing identity\n')
        self.assertNotEqual(self.cli('trust', '--action', 'install', *args).returncode, 0)
        self.assertEqual(anchor.read_bytes(), b'conflicting existing identity\n')
