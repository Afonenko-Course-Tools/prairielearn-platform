"""Проверка HTTPS Location настоящим nginx без TLS/LTI-данных и Docker."""
import http.client
import http.server
import pathlib
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).parents[1]


@unittest.skipUnless(shutil.which('nginx'), 'Для интеграционной проверки нужен nginx')
class GatewayHTTPSRedirect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []

        class Upstream(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                cls.requests.append((self.command, self.path, body))
                target = ('https://moodle.example/authorize?state=opaque'
                          if self.path.endswith('/lti/login') else
                          'http://' + self.headers['Host'] + self.path.partition('?')[0] +
                          '/' + ('?' + self.path.partition('?')[2] if '?' in self.path else ''))
                self.send_response(307)
                self.send_header('Location', target)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *args):
                pass

        cls.upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.upstream.server_close)
        cls.addClassCleanup(cls.upstream.shutdown)
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        directory = pathlib.Path(cls.directory.name)
        source = (ROOT / 'proxy/nginx.prod.conf').read_text()
        start = source.index('    location /gateway/ {')
        end = source.index('\n    }', start) + len('\n    }')
        location = source[start:end].replace('http://gateway:18080',
                                            'http://127.0.0.1:' + str(cls.upstream.server_port))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        config = directory / 'nginx.conf'
        config.write_text('worker_processes 1;\npid ' + str(directory / 'nginx.pid') + ';\n'
                          'error_log ' + str(directory / 'error.log') + ';\n'
                          'events {}\nhttp { access_log off; ' +
                          ''.join(name + '_temp_path ' + str(directory / name) + '; ' for name in
                                  ['client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi']) +
                          'server { listen 127.0.0.1:' +
                          str(cls.port) + ';\n' + location + '\n} }\n')
        command = [shutil.which('nginx'), '-p', str(directory), '-c', str(config)]
        checked = subprocess.run(command + ['-t'], capture_output=True, timeout=5)
        if checked.returncode:
            raise AssertionError(checked.stderr.decode())
        cls.nginx = subprocess.Popen(command + ['-g', 'daemon off;'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def stop():
            cls.nginx.terminate()
            cls.nginx.wait(timeout=5)

        cls.addClassCleanup(stop)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=.2):
                    return
            except OSError:
                time.sleep(.05)
        raise AssertionError('nginx не открыл локальный тестовый порт')

    def request(self, method, path, host, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers={
                'Host': host, 'X-Forwarded-Proto': 'http',
                'Forwarded': 'proto=http;host=evil.example'})
            response = connection.getresponse()
            response.read()
            return response.status, response.getheader('Location')
        finally:
            connection.close()

    def test_https_redirect_preserves_host_method_query_and_form_bytes(self):
        for host in ['courses.example', 'other.example:8443']:
            for course in ['java', 'system-practice']:
                for method in ['GET', 'POST']:
                    with self.subTest(host=host, course=course, method=method):
                        path = '/gateway/courses/' + course + '?a=%2F&b=one&b=two'
                        body = b'id_token=synthetic%2Bbytes&state=unchanged' if method == 'POST' else b''
                        status, location = self.request(method, path, host, body)
                        self.assertEqual(status, 307)
                        self.assertEqual(location, 'https://' + host + path.replace('?', '/?', 1))
                        self.assertEqual(self.requests[-1], (method, path, body))

    def test_external_https_login_redirect_is_unchanged(self):
        self.assertEqual(self.request('POST', '/gateway/courses/java/lti/login',
                                      'courses.example', b'state=synthetic'),
                         (307, 'https://moodle.example/authorize?state=opaque'))


if __name__ == '__main__':
    unittest.main()
