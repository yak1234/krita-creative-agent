import hashlib
import importlib.util
import io
import os
import pathlib
import tarfile
import tempfile
import unittest
from unittest import mock

SOURCE = pathlib.Path(__file__).resolve().parents[2] / 'plugin/kritamcp/node_runtime.py'
SPEC = importlib.util.spec_from_file_location('node_runtime', SOURCE)
node_runtime = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(node_runtime)
KEY = 'darwin-arm64'


def archive(version='22.23.2', key=KEY, node=b'#!/bin/sh\necho v22\n'):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        info = tarfile.TarInfo('node-v%s-%s/bin/node' % (version, key)); info.size = len(node); info.mode = 0o755
        tar.addfile(info, io.BytesIO(node))
        link = tarfile.TarInfo('node-v%s-%s/bin/npm' % (version, key)); link.type = tarfile.SYMTYPE; link.linkname = 'node'
        tar.addfile(link)
    return buffer.getvalue()


class Response(io.BytesIO):
    def __init__(self, data): super().__init__(data); self.headers = {'Content-Length': str(len(data))}
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def spec_for(data, version='22.23.2'):
    return {'version': version, 'archives': {KEY: {'file': 'node-v%s-%s.tar.gz' % (version, KEY), 'sha256': hashlib.sha256(data).hexdigest()}}}


class NodeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        os.environ.pop(node_runtime.OVERRIDE, None)

    def tearDown(self):
        import shutil; shutil.rmtree(self.root, ignore_errors=True)

    def test_downloads_once_verifies_and_reuses(self):
        data = archive(); spec = spec_for(data); calls = []; progress = []
        opener = lambda url, timeout: calls.append(url) or Response(data)
        node = node_runtime.ensure(spec, self.root, progress=lambda d, t: progress.append((d, t)), opener=opener, key=KEY)
        self.assertTrue(node.is_file()); self.assertTrue((node.parent / 'npm').is_symlink(), "npm's symlink survives")
        self.assertEqual(calls, ['https://nodejs.org/dist/v22.23.2/node-v22.23.2-darwin-arm64.tar.gz'])
        self.assertEqual(progress[-1], (len(data), len(data)))
        self.assertTrue(node_runtime.is_ready(spec, self.root, KEY))
        self.assertEqual(node_runtime.ensure(spec, self.root, opener=opener, key=KEY), node)
        self.assertEqual(len(calls), 1, 'a verified runtime is not downloaded again')
        self.assertEqual([p.name for p in self.root.iterdir()], ['node-v22.23.2-darwin-arm64'], 'no temporary files left')

    def test_downloads_with_system_curl_ignoring_broken_ca_overrides(self):
        # Krita's Python has no CA bundle; the system curl (system trust store) downloads instead.
        data = archive(); spec = spec_for(data)
        payload = self.root / 'payload.tar.gz'; payload.write_bytes(data)
        fake = self.root / 'curl'
        fake.write_text('#!/bin/sh\n[ -n "$SSL_CERT_FILE" ] && { echo "broken CA override leaked" >&2; exit 77; }\n'
                        'while [ "$1" != "--output" ]; do shift; done; cp "%s" "$2"\n' % payload)
        fake.chmod(0o755)
        with mock.patch.object(node_runtime, 'CURL', str(fake)), mock.patch.dict(os.environ, {'SSL_CERT_FILE': '/nonexistent.pem'}):
            node = node_runtime.ensure(spec, self.root / 'runtimes', key=KEY)
        self.assertTrue(node.is_file()); self.assertTrue(node_runtime.is_ready(spec, self.root / 'runtimes', KEY))

    def test_checksum_mismatch_is_refused_and_leaves_nothing(self):
        spec = spec_for(archive()); tampered = archive(node=b'#!/bin/sh\necho evil\n')
        with self.assertRaisesRegex(ValueError, 'pinned checksum'):
            node_runtime.ensure(spec, self.root, opener=lambda url, timeout: Response(tampered), key=KEY)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertFalse(node_runtime.is_ready(spec, self.root, KEY))

    def test_override_and_pruning(self):
        override = self.root / 'my-node'; override.write_text('node')
        with mock.patch.dict(os.environ, {node_runtime.OVERRIDE: str(override)}):
            self.assertEqual(node_runtime.ensure({'version': '1.0.0', 'archives': {}}, self.root), override)
        for version in ('22.23.2', '24.1.0'): (self.root / ('node-v%s-%s' % (version, KEY))).mkdir()
        self.assertEqual(node_runtime.prune({'24.1.0'}, self.root), ['node-v22.23.2-darwin-arm64'])

    def test_spec_from_official_shasums(self):
        text = 'aaa  node-v22.23.2-darwin-arm64.tar.gz\nbbb  node-v22.23.2-darwin-x64.tar.gz\nccc  node-v22.23.2-linux-x64.tar.xz\n'
        spec = node_runtime.spec_from_shasums('22.23.2', text)
        self.assertEqual(spec['archives']['darwin-x64'], {'file': 'node-v22.23.2-darwin-x64.tar.gz', 'sha256': 'bbb'})
        with self.assertRaises(ValueError): node_runtime.spec_from_shasums('22.23.2', 'aaa  other.tar.gz')
        self.assertEqual(node_runtime.platform_key('Darwin', 'x86_64'), 'darwin-x64')
        with self.assertRaises(ValueError): node_runtime.platform_key('Linux', 'x86_64')


if __name__ == '__main__':
    unittest.main()
