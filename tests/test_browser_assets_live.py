"""Проверка ресурсов настоящей страницы через внешний HTTPS reverse proxy."""
from __future__ import annotations

from email.message import Message
import os
import ssl
import unittest
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookies import SimpleCookie

class AssetLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for name in ('href', 'src'):
            path = values.get(name, '')
            if path is not None and path.startswith('/assets/'):
                self.paths.add(path)

@unittest.skipUnless(os.environ.get('PL_BROWSER_TEST_URL') and os.environ.get('PL_BROWSER_TEST_CA'),
                     'Нужны HTTPS стенд и доверенный CA для браузерной проверки')
class BrowserAssetsIntegration(unittest.TestCase):
    def request(self, path: str) -> tuple[int | None, str, bytes, Message[str, str]]:
        context = ssl.create_default_context(cafile=os.environ['PL_BROWSER_TEST_CA'])
        url = os.environ['PL_BROWSER_TEST_URL'].rstrip('/') + path
        try:
            response = urllib.request.urlopen(url, context=context, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers.get_content_type(), response.read(), response.headers

    def test_native_page_styles_and_scripts_reach_browser(self) -> None:
        status, content_type, body, _ = self.request('/pl/login')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'text/html')
        links = AssetLinks()
        links.feed(body.decode())
        self.assertGreater(len(links.paths), 5)
        for path in sorted(links.paths):
            with self.subTest(path=path):
                status, content_type, body, _ = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                suffix = urllib.parse.urlsplit(path).path
                if suffix.endswith('.css'):
                    self.assertEqual(content_type, 'text/css')
                elif suffix.endswith('.js'):
                    self.assertIn(content_type, ('application/javascript', 'text/javascript'))

    def test_native_https_session_cookies_are_browser_compatible(self) -> None:
        status, _, _, headers = self.request('/pl/login')
        self.assertEqual(status, 200)
        cookies = SimpleCookie()
        for value in headers.get_all('Set-Cookie', []):
            cookies.load(value)
        for name in ('prairielearn_session', 'pl2_session'):
            with self.subTest(name=name):
                self.assertTrue(name in cookies, name + " отсутствует в Set-Cookie")
                self.assertTrue(cookies[name]['secure'], name + ' требует Secure через HTTPS')
                self.assertTrue(cookies[name]['httponly'])

    def test_native_favicon_reaches_browser(self) -> None:
        status, content_type, body, _ = self.request('/favicon.ico')
        self.assertEqual(status, 200)
        self.assertIn(content_type, ('image/x-icon', 'image/vnd.microsoft.icon'))
        self.assertTrue(body)

    def test_logo_and_gateway_root_open_native_platform(self) -> None:
        for path in ('/', '/gateway', '/gateway/'):
            with self.subTest(path=path):
                status, content_type, body, _ = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, 'text/html')
                self.assertIn(b'PrairieLearn', body)
