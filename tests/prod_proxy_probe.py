"""Изолированный production proxy: python3 tests/prod_proxy_probe.py (nginx, openssl)."""
import http.client
import http.server
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
UID = 'synthetic-user@example.test'
NAME = 'v1.VGVzdCBVc2Vy'
TARGET = '/pl/course_instance/7/assessments'
FORGED = {
    'X-Forwarded-For': '192.0.2.123, 198.51.100.45',
    'X-Real-IP': '192.0.2.123',
    'Forwarded': 'for=192.0.2.123;proto=http',
    'X-Trust-Auth-Uid': 'forged@example.test',
    'X-Trust-Auth-Name': 'Forged',
    'X-Trust-Auth-Name-UTF8-B64': 'v1.Rm9yZ2Vk',
    'X-Trust-Auth-Uin': 'forged',
    'Cookie': 'GatewayLogin=synthetic; pl2_session=synthetic',
}


class Upstream(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/internal/handoff'):
            if self.headers.get('Authorization') != 'Bearer synthetic-test-token':
                self.send_error(403)
                return
            self.send_response(200)
            self.send_header('X-Verified-Uid', UID)
            self.send_header('X-Verified-Name-UTF8-B64', NAME)
            self.send_header('X-Verified-Target', TARGET)
            self.end_headers()
            return
        body = json.dumps({'path': self.path, 'headers': dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ProductionProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='pl-prod-proxy-')
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.addClassCleanup(upstream.server_close)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        cls.addClassCleanup(upstream.shutdown)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            cls.port = reservation.getsockname()[1]
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1', '-keyout', str(directory / 'server.key'),
            '-out', str(directory / 'server.crt'),
        ], check=True, capture_output=True)
        cls.context = ssl.create_default_context(cafile=str(directory / 'server.crt'))
        (directory / 'handoff-auth.conf').write_text(
            'proxy_set_header Authorization "Bearer synthetic-test-token";\n')
        config = (ROOT / 'proxy/nginx.prod.conf').read_text()
        # Меняем только адреса/файлы окружения; маршруты и proxy headers берём из production.
        for old, new in [
            ('worker_processes auto;', 'worker_processes 1;'),
            ('listen 443 ssl;', f'listen 127.0.0.1:{cls.port} ssl;'),
            ('/tls/', str(directory) + '/'),
            ('/etc/nginx/private/handoff-auth.conf', str(directory / 'handoff-auth.conf')),
            ('http://pl:3000', f'http://127.0.0.1:{upstream.server_port}'),
            ('http://gateway:18080', f'http://127.0.0.1:{upstream.server_port}'),
        ]:
            if old not in config:
                raise AssertionError(f'Не найден адрес/файл окружения: {old}')
            config = config.replace(old, new)
        temporary_paths = ''.join(
            f'  {name}_temp_path {directory}/{name};\n'
            for name in ['client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'])
        config = config.replace('http {\n', 'http {\n' + temporary_paths, 1)
        (directory / 'nginx.conf').write_text(config)
        command = ['nginx', '-p', str(directory) + '/', '-c', str(directory / 'nginx.conf'),
                   '-g', f'pid {directory}/nginx.pid; daemon off;']
        syntax = subprocess.run(command + ['-t'], capture_output=True, text=True)
        if syntax.returncode:
            raise AssertionError(syntax.stderr)
        log = (directory / 'nginx.log').open('w+')
        cls.addClassCleanup(log.close)
        process = subprocess.Popen(command, stdout=log, stderr=log)

        def stop():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        cls.addClassCleanup(stop)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                status, _ = cls.request('/healthz', {})
                if status == 200:
                    return
            except OSError:
                pass
            if process.poll() is not None:
                break
            time.sleep(0.02)
        log.seek(0)
        raise AssertionError('Nginx не запустился: ' + log.read())

    @classmethod
    def request(cls, path, headers):
        connection = http.client.HTTPSConnection(
            '127.0.0.1', cls.port, context=cls.context, timeout=5)
        try:
            connection.request('GET', path, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def observed(self, path):
        status, body = self.request(path, FORGED)
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        headers = {key.lower(): value for key, value in payload['headers'].items()}
        self.assertEqual(headers.get('x-forwarded-for'), '127.0.0.1')
        self.assertEqual(headers.get('x-real-ip'), '127.0.0.1')
        self.assertNotIn('forwarded', headers)
        self.assertEqual(headers.get('x-forwarded-proto'), 'https')
        return payload['path'], headers

    def test_public_native_locations_replace_forged_forwarding(self):
        for path in ['/pl/example?x=1', '/favicon.ico', '/assets/example.js', '/socket.io/?EIO=4']:
            with self.subTest(path=path):
                actual_path, headers = self.observed(path)
                self.assertEqual(actual_path, path)
                for name in ['uid', 'name', 'name-utf8-b64', 'uin']:
                    self.assertNotIn('x-trust-auth-' + name, headers)
                self.assertEqual(headers['cookie'], FORGED['Cookie'])

    def test_handoff_keeps_verified_identity_and_native_cookie(self):
        for prefix in ['/gateway/pl/', '/gateway/courses/synthetic/pl/']:
            with self.subTest(prefix=prefix):
                path, headers = self.observed(prefix + 'a' * 43)
                self.assertEqual(path, '/pl/shibcallback')
                self.assertEqual(headers.get('x-trust-auth-uid'), UID)
                self.assertEqual(headers.get('x-trust-auth-name-utf8-b64'), NAME)
                self.assertNotIn('x-trust-auth-name', headers)
                self.assertNotIn('x-trust-auth-uin', headers)
                self.assertEqual(headers.get('cookie'), 'pl2_pre_auth_url=' + TARGET)

    def test_private_and_callback_routes_remain_closed(self):
        for path, expected in [('/internal/handoff/test', 404), ('/__verified_handoff', 404),
                               ('/pl/shibcallback', 403), ('/pl/shibcallback/extra', 403)]:
            with self.subTest(path=path):
                self.assertEqual(self.request(path, FORGED)[0], expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
