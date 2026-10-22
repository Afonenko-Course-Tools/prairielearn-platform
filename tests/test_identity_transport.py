"""Проверки generated src/dist и strict decoder; loadUser здесь mock, не DB proof."""
import hashlib
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('gateway_name_patch', ROOT / 'images/prairielearn/patch-gateway-name.py')
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


class NativeNamePatch(unittest.TestCase):
    def original(self, kind):
        return (ROOT / 'tests/fixtures' / ('gateway-name-base.' + ('ts' if kind == 'src' else 'js'))).read_text()

    def test_pinned_hashes_generated_body_and_no_uid_sql_change(self):
        for kind in ['src', 'dist']:
            source = self.original(kind)
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), PATCH.BASE_HASHES[kind])
            result = PATCH.patch(source, kind)
            decoder = PATCH.DECODER if kind == 'dist' else PATCH.DECODER.replace('function decodeGatewayVerifiedName(value)', 'function decodeGatewayVerifiedName(value: unknown): string', 1)
            self.assertIn(decoder, result)
            self.assertEqual(result.replace(decoder + '\n', '', 1).replace(PATCH.NEW_NAME_READ, PATCH.NAME_READ, 1), source)
            with self.assertRaises(ValueError): PATCH.patch(result, kind)
            with self.assertRaises(ValueError): PATCH.patch(source + '\n# drift', kind)

    def test_both_pinned_inputs_validated_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            src, dist = pathlib.Path(directory) / 'callback.ts', pathlib.Path(directory) / 'callback.js'
            src.write_text(self.original('src')); dist.write_text('drift')
            before = src.read_bytes()
            with self.assertRaises(ValueError): PATCH.patch_files(src, dist)
            self.assertEqual(src.read_bytes(), before)
            self.assertEqual(dist.read_text(), 'drift')

    def test_actual_patched_callback_both_generated_forms_with_mock_load_user(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind, suffix in [('src', 'ts'), ('dist', 'js')]:
                path = pathlib.Path(directory) / ('callback.' + suffix)
                path.write_text(PATCH.patch(self.original(kind), kind))
                result = subprocess.run(['node', '--experimental-vm-modules', 'tests/bridge/gateway-name.handler.mjs', str(path)], cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('"checks":32', result.stdout)

    def test_proxy_public_routes_strip_both_names_and_handoff_uses_verified_wire(self):
        source = (ROOT / 'proxy/nginx.prod.conf').read_text()
        self.assertIn('auth_request_set $verified_name_utf8_b64 $upstream_http_x_verified_name_utf8_b64;', source)
        self.assertIn('proxy_set_header X-Trust-Auth-Name-UTF8-B64 $verified_name_utf8_b64;', source)
        self.assertNotIn('proxy_set_header X-Trust-Auth-Name $verified_name;', source)
        self.assertEqual(source.count('proxy_set_header X-Trust-Auth-Name "";'), source.count('proxy_pass http://pl:3000;') + 1)
        self.assertEqual(source.count('proxy_set_header X-Trust-Auth-Name-UTF8-B64 "";'), source.count('proxy_pass http://pl:3000;'))
        headers = (ROOT / 'proxy/pl-headers.conf').read_text()
        self.assertIn('proxy_set_header X-Trust-Auth-Name-UTF8-B64 "";', headers)


if __name__ == '__main__':
    unittest.main()
