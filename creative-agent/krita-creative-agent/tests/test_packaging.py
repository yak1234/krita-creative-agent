"""Installer tests use only throwaway destinations; never the real Krita profile."""
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('creative_installer', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)


def write_bundle(directory, content='current plugin', managed=False):
    files = {**({} if managed else {'runtime/bin/node': 'runtime fixture', 'runtime/LICENSE': 'license fixture'}),
             'companion/src/main.mjs': 'export const version="1.0.0";',
             'plugin/kritamcp/creative_docker.py': content, 'plugin/kritamcp.desktop': '[Desktop Entry]',
             'install.py': 'installer fixture'}
    hashes = {}
    for name, text in files.items():
        file = directory / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text(text)
        hashes[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    build_id = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    info = {'version': '1.0.0', 'protocol_version': 2, 'build_id': build_id, 'platform': 'darwin',
            'architecture': {'arm64':'arm64','aarch64':'arm64','x86_64':'x64'}[platform.machine()]}
    for name in ('companion/build-info.json', 'plugin/kritamcp/build-info.json'):
        file = directory / name; file.write_text(json.dumps(info)); hashes[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    key = 'darwin-' + {'arm64':'arm64','aarch64':'arm64','x86_64':'x64'}[platform.machine()]
    extra = {'architecture': 'any', 'node_runtime': {'version': '22.23.2', 'archives': {key: {'file': 'node-v22.23.2-%s.tar.gz' % key, 'sha256': 'a' * 64}}}} if managed else {}
    (directory / 'release-manifest.json').write_text(json.dumps({**info, **extra, 'files': hashes}))
    return info


class ManagedRuntimePackagingTests(unittest.TestCase):
    def test_managed_release_installs_without_a_runtime_and_points_at_the_shared_one(self):
        with tempfile.TemporaryDirectory(prefix='creative-install-test-') as folder:
            root = Path(folder); bundle = root / 'bundle'; bundle.mkdir(); write_bundle(bundle, managed=True)
            project = root / 'Art'; project.mkdir(); releases = root / 'Creative Agent/releases'
            with patch.object(installer.platform, 'system', return_value='Darwin'):
                result = installer.install(bundle, root / 'pykrita', releases, project)
            settings = json.loads((root / 'pykrita/kritamcp/creative-agent-config.json').read_text())
            self.assertEqual(Path(settings['node']).parent.parent.parent, (root / 'Creative Agent/runtimes').resolve())
            self.assertEqual(settings['node_runtime']['version'], '22.23.2')
            self.assertFalse((Path(result['release']) / 'runtime').exists())


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='creative-install-test-')
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'bundle'; self.bundle.mkdir()
        self.info = write_bundle(self.bundle)
        self.project = self.root / 'Art project'; self.project.mkdir()
        self.painting = self.project / 'painting.kra'; self.painting.write_bytes(b'unsaved work safe fixture')
        self.destination = self.root / 'Krita profile/pykrita'
        self.runtime = self.root / 'Application Support/Creative Agent/releases'
    def tearDown(self): self.temporary.cleanup()
    def run_install(self):
        with patch.object(installer.platform, 'system', return_value='Darwin'):
            return installer.install(self.bundle, self.destination, self.runtime, self.project)
    def test_fresh_install_is_relocatable_and_does_not_modify_artwork(self):
        result = self.run_install()
        config = json.loads((self.destination / 'kritamcp/creative-agent-config.json').read_text())
        self.assertTrue(Path(config['node']).is_file()); self.assertTrue(Path(config['companion']).is_file())
        self.assertTrue(Path(config['node']).is_relative_to(self.runtime.resolve()))
        self.assertEqual(config['project_root'], str(self.project.resolve()))
        # Records live beside the releases, not in the artwork folder (storage-layout).
        self.assertEqual(config['data_dir'], str(self.runtime.resolve().parent / 'data'))
        self.assertEqual(config['output'], config['data_dir'])
        self.assertFalse(Path(config['data_dir']).is_relative_to(self.project.resolve()))
        self.assertNotIn('python', config); self.assertNotIn('api_key', config)
        self.assertEqual(list(self.project.iterdir()), [self.painting])
        self.assertFalse(result['live_verified']); self.assertTrue(result['reload_required'])
        self.assertEqual(self.painting.read_bytes(), b'unsaved work safe fixture')
    def test_update_preserves_backup_and_legacy_records_and_reuses_intact_runtime(self):
        (self.destination / 'kritamcp').mkdir(parents=True)
        (self.destination / 'kritamcp/old.txt').write_text('old plugin')
        old = {'output': str(self.root / 'legacy-output'), 'bridge_url':'http://127.0.0.1:5679', 'api_key':'do-not-copy'}
        (self.destination / 'kritamcp/creative-agent-config.json').write_text(json.dumps(old))
        result = self.run_install()
        config = json.loads((self.destination / 'kritamcp/creative-agent-config.json').read_text())
        self.assertEqual(config['legacy_output'], old['output']); self.assertEqual(config['bridge_url'], old['bridge_url'])
        self.assertNotIn('api_key', config)
        self.assertEqual((Path(result['backup']) / 'kritamcp/old.txt').read_text(), 'old plugin')
        self.assertFalse((self.destination / 'kritamcp/old.txt').exists())
        second = self.run_install(); self.assertEqual(second['release'], result['release'])
    def test_modified_bundle_rejected_before_touching_profile(self):
        (self.bundle / 'companion/src/main.mjs').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'): self.run_install()
        self.assertFalse(self.destination.exists()); self.assertFalse(self.runtime.exists())
    def test_unlisted_file_and_unsafe_identifier_are_rejected(self):
        (self.bundle / 'hidden-auth.json').write_text('private')
        with self.assertRaisesRegex(ValueError, 'inventory'): self.run_install()
        (self.bundle / 'hidden-auth.json').unlink()
        file = self.bundle / 'release-manifest.json'; manifest = json.loads(file.read_text())
        manifest['build_id'] = '../../outside'; file.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'identifier'): self.run_install()
    def test_modified_installed_runtime_is_not_silently_reused(self):
        result = self.run_install()
        (Path(result['release']) / 'companion/src/main.mjs').write_text('changed runtime')
        with self.assertRaisesRegex(ValueError, 'runtime was modified'): self.run_install()
    def test_failed_plugin_swap_rolls_back_previous_plugin(self):
        (self.destination / 'kritamcp').mkdir(parents=True)
        (self.destination / 'kritamcp/old.txt').write_text('old plugin')
        (self.destination / 'kritamcp.desktop').write_text('old desktop')
        original = Path.rename
        def failing_rename(source, destination):
            if source.name == 'kritamcp.desktop' and source.parent.name.startswith('.creative-install-'):
                raise OSError('simulated swap failure')
            return original(source, destination)
        with patch.object(Path, 'rename', failing_rename):
            with self.assertRaisesRegex(OSError, 'simulated'): self.run_install()
        self.assertEqual((self.destination / 'kritamcp/old.txt').read_text(), 'old plugin')
        self.assertEqual((self.destination / 'kritamcp.desktop').read_text(), 'old desktop')


class ForkTargetTests(unittest.TestCase):
    """--krita fork: the Qt6 fork (its own settings folder) gets the plugin in its own pykrita, its own bridge port, and
    its own records folder (a companion locks its records folder, and both apps may run at once)."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='creative-install-test-')
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'bundle'; self.bundle.mkdir(); write_bundle(self.bundle)
        self.project = self.root / 'Art'; self.project.mkdir()
        self.runtime = self.root / 'Creative Agent/releases'
        self.destination = self.root / 'KritaAgent/krita/pykrita'
    def tearDown(self): self.temporary.cleanup()
    def run_install(self, krita):
        with patch.object(installer.platform, 'system', return_value='Darwin'):
            return installer.install(self.bundle, self.destination, self.runtime, self.project, krita=krita)
    def config(self):
        return json.loads((self.destination / 'kritamcp/creative-agent-config.json').read_text())

    def test_stock_is_unchanged_by_default(self):
        self.run_install('stock')
        config = self.config()
        self.assertEqual(config['bridge_url'], 'http://127.0.0.1:5678')
        self.assertEqual(config['data_dir'], str(self.runtime.resolve().parent / 'data'))

    def test_fork_gets_its_own_port_and_records_and_shares_releases(self):
        result = self.run_install('fork')
        config = self.config()
        self.assertEqual(config['bridge_url'], 'http://127.0.0.1:5679')
        self.assertEqual(config['data_dir'], str(self.runtime.resolve().parent / 'KritaAgent/data'))
        self.assertEqual(config['output'], config['data_dir'])
        self.assertTrue(config['cache_dir'].endswith('/Creative Agent/KritaAgent'), config['cache_dir'])
        self.assertTrue(Path(result['release']).is_relative_to(self.runtime.resolve()))

    def test_fork_starts_from_the_stock_settings_without_overwriting_its_own(self):
        stock = self.runtime.parent / 'data'; (stock / 'capabilities').mkdir(parents=True)
        for name in ('execution-settings.json', 'model-connections.json', 'capabilities/model-capabilities.json'):
            (stock / name).write_text('stock ' + name)
        (stock / 'records.sqlite').write_text('stock records')
        own = self.runtime.parent / 'KritaAgent/data'; own.mkdir(parents=True)
        (own / 'execution-settings.json').write_text('fork settings')
        self.run_install('fork')
        self.assertEqual((own / 'execution-settings.json').read_text(), 'fork settings')
        self.assertEqual((own / 'model-connections.json').read_text(), 'stock model-connections.json')
        self.assertEqual((own / 'capabilities/model-capabilities.json').read_text(), 'stock capabilities/model-capabilities.json')
        self.assertFalse((own / 'records.sqlite').exists(), 'chats and records stay with each app')
        self.assertEqual((stock / 'execution-settings.json').read_text(), 'stock execution-settings.json')

    def test_unknown_target_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Krita'): self.run_install('other')
        self.assertFalse(self.destination.exists())

    def test_fork_folders_follow_qt_app_data_on_each_os(self):
        home = Path('/home/artist')
        self.assertEqual(installer.default_locations('Darwin', {}, home, krita='fork')['destination'],
                         home / 'Library/Application Support/KritaAgent/krita/pykrita')
        self.assertEqual(installer.default_locations('Linux', {}, home, krita='fork')['destination'], home / '.local/share/KritaAgent/krita/pykrita')
        self.assertEqual(installer.default_locations('Windows', {'APPDATA': '/roaming', 'LOCALAPPDATA': '/local'}, home, krita='fork')['destination'],
                         Path('/roaming/KritaAgent/krita/pykrita'))
        # Releases and runtimes are shared: they are immutable and named by build.
        self.assertEqual(installer.default_locations('Darwin', {}, home, krita='fork')['runtime_destination'],
                         installer.default_locations('Darwin', {}, home)['runtime_destination'])
        self.assertEqual(installer.default_locations('Darwin', {}, home)['destination'], home / 'Library/Application Support/krita/pykrita')


class PlatformTests(unittest.TestCase):
    def test_keys_node_file_and_folders_match_the_javascript_installer(self):
        self.assertEqual(installer.runtime_key('Windows', 'AMD64'), 'win-x64'); self.assertEqual(installer.runtime_key('Linux', 'aarch64'), 'linux-arm64')
        self.assertEqual(installer.runtime_key('Darwin', 'arm64'), 'darwin-arm64'); self.assertIsNone(installer.runtime_key('Linux', 'i686'))
        self.assertEqual(installer.node_file('Windows'), 'node.exe'); self.assertEqual(installer.node_file('Linux'), 'bin/node')
        home = Path('/home/artist')
        self.assertEqual(installer.default_locations('Linux', {}, home)['runtime_destination'], home / '.local/share/creative-agent/releases')
        self.assertEqual(installer.default_locations('Linux', {}, home)['destination'], home / '.local/share/krita/pykrita')
        windows = installer.default_locations('Windows', {'APPDATA': '/roaming', 'LOCALAPPDATA': '/local'}, home)
        self.assertEqual(windows['destination'], Path('/roaming/krita/pykrita')); self.assertEqual(windows['runtime_destination'], Path('/local/Creative Agent/releases'))


class ShadowTests(unittest.TestCase):
    def test_a_plugin_in_the_forks_folder_would_hide_the_packaged_apps_own(self):
        if platform.system() != 'Darwin': self.skipTest('the packaged app is macOS only')
        with tempfile.TemporaryDirectory() as root:
            home, applications = Path(root) / 'home', Path(root) / 'Applications'
            fork = installer.default_locations(home=home, krita='fork')['destination']
            self.assertIsNone(installer.shadowed_bundled_plugin(fork, 'fork', home, [applications]), 'no packaged app installed')
            (applications / 'Toska.app').mkdir(parents=True)
            self.assertEqual(installer.shadowed_bundled_plugin(fork, 'fork', home, [applications]), applications / 'Toska.app')
            (applications / 'Toska.app').rmdir()
            (applications / 'Krita Agent.app').mkdir()
            self.assertEqual(installer.shadowed_bundled_plugin(fork, 'fork', home, [applications]), applications / 'Krita Agent.app',
                             'an app still under its old name carries the plugin too')
            (applications / 'Krita Agent.app').rmdir()
            (applications / 'Toska.app').mkdir()
            self.assertIsNone(installer.shadowed_bundled_plugin(fork, 'stock', home, [applications]), 'stock Krita has no packaged plugin')
            self.assertIsNone(installer.shadowed_bundled_plugin(Path(root) / 'elsewhere', 'fork', home, [applications]))
            with self.assertRaises(ValueError) as raised:
                installer.install(Path(root) / 'bundle', fork, Path(root) / 'releases', Path(root), krita='fork', home=home, applications=[applications])
            self.assertIn('carries the plugin', str(raised.exception))
            self.assertFalse(fork.exists(), 'nothing was created')


if __name__ == '__main__': unittest.main()
