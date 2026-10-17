import hashlib
import importlib.util
import io
import os
import pathlib
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock

SOURCE = pathlib.Path(__file__).resolve().parents[2] / 'plugin/kritamcp/node_runtime.py'
SPEC = importlib.util.spec_from_file_location('node_runtime', SOURCE)
node_runtime = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(node_runtime)
KEY = 'darwin-arm64'


def archive(version='22.23.2', key=KEY, node=b'#!/bin/sh\necho v22\n', mode='w:gz'):
    buffer = io.BytesIO()
    if key.startswith('win-'):
        with zipfile.ZipFile(buffer, 'w') as bundle:
            bundle.writestr('node-v%s-%s/node.exe' % (version, key), node)
            bundle.writestr('node-v%s-%s/npm.cmd' % (version, key), b'@node npm')
        return buffer.getvalue()
    with tarfile.open(fileobj=buffer, mode=mode) as tar:
        info = tarfile.TarInfo('node-v%s-%s/bin/node' % (version, key)); info.size = len(node); info.mode = 0o755
        tar.addfile(info, io.BytesIO(node))
        link = tarfile.TarInfo('node-v%s-%s/bin/npm' % (version, key)); link.type = tarfile.SYMTYPE; link.linkname = 'node'
        tar.addfile(link)
    return buffer.getvalue()


class Response(io.BytesIO):
    def __init__(self, data): super().__init__(data); self.headers = {'Content-Length': str(len(data))}
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def spec_for(data, version='22.23.2', key=KEY):
    return {'version': version, 'archives': {key: {'file': node_runtime.archive_name(version, key), 'sha256': hashlib.sha256(data).hexdigest()}}}


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

    def test_each_platform_unpacks_its_own_archive_format(self):
        # Linux ships .tar.xz and Windows .zip with node.exe at the top; the runtime is found either way.
        for key, mode, executable in (('linux-x64', 'w:xz', 'bin/node'), ('win-x64', None, 'node.exe')):
            with self.subTest(key=key):
                data = archive(key=key, mode=mode); spec = spec_for(data, key=key); calls = []
                node = node_runtime.ensure(spec, self.root, opener=lambda url, timeout, calls=calls, data=data: calls.append(url) or Response(data), key=key)
                self.assertEqual(node, self.root / ('node-v22.23.2-' + key) / executable)
                self.assertTrue(node.is_file()); self.assertTrue(node_runtime.is_ready(spec, self.root, key))
                self.assertEqual(node_runtime.node_path(spec, self.root, key), node)
                self.assertEqual(calls, ['https://nodejs.org/dist/v22.23.2/' + node_runtime.archive_name('22.23.2', key)])

    def test_a_zip_that_escapes_its_folder_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as bundle: bundle.writestr('../outside.exe', b'x')
        data = buffer.getvalue(); spec = spec_for(data, key='win-x64')
        with self.assertRaisesRegex(ValueError, 'unsafe path'):
            node_runtime.ensure(spec, self.root, opener=lambda url, timeout: Response(data), key='win-x64')
        self.assertEqual(list(self.root.iterdir()), []); self.assertFalse((self.root.parent / 'outside.exe').exists())

    def test_platform_keys_and_per_os_roots(self):
        cases = {('Darwin', 'arm64'): 'darwin-arm64', ('Darwin', 'x86_64'): 'darwin-x64', ('Linux', 'x86_64'): 'linux-x64',
                 ('Linux', 'aarch64'): 'linux-arm64', ('Windows', 'AMD64'): 'win-x64', ('Windows', 'ARM64'): 'win-arm64'}
        for (system, machine), key in cases.items():
            self.assertEqual(node_runtime.platform_key(system, machine), key)
        for system, machine in (('FreeBSD', 'x86_64'), ('Linux', 'i686')):
            with self.assertRaises(ValueError): node_runtime.platform_key(system, machine)
        home = pathlib.Path('/home/artist')
        self.assertEqual(node_runtime.default_root('Darwin', {}, home), home / 'Library/Application Support/Creative Agent/runtimes')
        self.assertEqual(node_runtime.default_root('Linux', {}, home), home / '.local/share/creative-agent/runtimes')
        self.assertEqual(node_runtime.default_root('Linux', {'XDG_DATA_HOME': '/data'}, home), pathlib.Path('/data/creative-agent/runtimes'))
        self.assertEqual(node_runtime.default_root('Windows', {'LOCALAPPDATA': '/appdata'}, home), pathlib.Path('/appdata/Creative Agent/runtimes'))
        self.assertEqual(node_runtime.default_root('Windows', {}, home), home / 'AppData/Local/Creative Agent/runtimes')

    @unittest.skipIf(os.name == 'nt', 'the stand-in curl is a shell script')
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
        names = ['node-v22.23.2-%s%s' % (key, ext) for key, ext in (('darwin-arm64', '.tar.gz'), ('darwin-x64', '.tar.gz'),
                 ('linux-arm64', '.tar.xz'), ('linux-x64', '.tar.xz'), ('win-arm64', '.zip'), ('win-x64', '.zip'))]
        # SHASUMS256.txt also lists formats a release does not use (.tar.gz for Linux, .7z, .msi).
        text = ''.join('%02x  %s\n' % (i, name) for i, name in enumerate(names)) + 'ff  node-v22.23.2-linux-x64.tar.gz\n'
        spec = node_runtime.spec_from_shasums('22.23.2', text)
        self.assertEqual(sorted(spec['archives']), sorted(node_runtime.KEYS))
        self.assertEqual(spec['archives']['linux-x64'], {'file': 'node-v22.23.2-linux-x64.tar.xz', 'sha256': '03'})
        self.assertEqual(spec['archives']['win-x64'], {'file': 'node-v22.23.2-win-x64.zip', 'sha256': '05'})
        self.assertEqual(node_runtime.spec_from_shasums('22.23.2', text, keys=('darwin-x64',))['archives'].keys(), {'darwin-x64'})
        with self.assertRaises(ValueError): node_runtime.spec_from_shasums('22.23.2', 'aaa  other.tar.gz')


if __name__ == '__main__':
    unittest.main()
