"""bridge_guard.py: the bridge (a local web server Toska adds to Krita so the agent can paint) answers only the artist's
own programs. A web page in the artist's browser can reach 127.0.0.1 too: its requests carry Origin (or Sec-Fetch-Site)
and are refused, as is any request addressed to another host name (DNS rebinding). The companion, the MCP server, the
test driver and scripts send neither and address 127.0.0.1 or localhost, so nothing of theirs changes."""
import importlib.util
import pathlib
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('bridge_guard_under_test', PLUGIN / 'bridge_guard.py')
bridge_guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge_guard)
refusal = bridge_guard.refusal


class OwnProgramsTests(unittest.TestCase):
    def test_the_companion_mcp_server_and_scripts_are_answered(self):
        for host in ('127.0.0.1:5679', 'localhost:5679', '[::1]:5679', 'LOCALHOST:5679'):
            self.assertIsNone(refusal({'Host': host, 'Content-Type': 'application/json'}, 5679), host)

    def test_a_request_without_a_host_header_is_answered(self):
        self.assertIsNone(refusal({}, 5679), 'HTTP/1.0 clients may leave it out')

    def test_a_direct_typed_address_in_the_browser_is_answered(self):
        self.assertIsNone(refusal({'Host': '127.0.0.1:5679', 'Sec-Fetch-Site': 'none'}, 5679), 'the artist typing the address')


class BrowserTests(unittest.TestCase):
    def test_a_web_page_is_refused(self):
        self.assertIn('browser', refusal({'Host': '127.0.0.1:5679', 'Origin': 'https://example.com'}, 5679))

    def test_even_a_null_or_local_origin_is_refused(self):
        for origin in ('null', 'http://127.0.0.1:5679', 'http://localhost:8000'):
            self.assertIsNotNone(refusal({'Host': '127.0.0.1:5679', 'Origin': origin}, 5679), origin)

    def test_a_cross_site_fetch_without_origin_is_refused(self):
        for site in ('cross-site', 'same-site', 'same-origin'):
            self.assertIsNotNone(refusal({'Host': '127.0.0.1:5679', 'Sec-Fetch-Site': site}, 5679), site)

    def test_another_host_name_is_refused(self):
        for host in ('evil.example:5679', 'my-mac.local:5679', '192.168.1.20:5679', '127.0.0.1:80', '127.0.0.1', 'localhost.evil.example:5679'):
            self.assertIn('address', refusal({'Host': host}, 5679), host)


if __name__ == '__main__':
    unittest.main()
