# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""bundled_release.py: the companion that ships inside the app is verified and copied out on first use. Fake releases in a
temporary folder (removed afterwards); nothing near the artist's files."""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import time
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('bundled_release_under_test', PLUGIN / 'bundled_release.py')
bundled_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundled_release)

BUILD_ID = hashlib.sha256(b'build').hexdigest()
BUILD_ID_2 = hashlib.sha256(b'build2').hexdigest()


def make_release(root, extra_files=None, build_id=BUILD_ID, built_at='2026-10-19T12:00:00Z', manifest_extra=None):
    """A release as build-release.py makes it (companion/ plus plugin files, a manifest listing all of them), in the folder the
    packaged app keeps it: Resources/creative-agent-bundle, with the packager's bundle-info.json."""
    bundled = pathlib.Path(root) / 'Resources' / 'creative-agent-bundle'
    files = {'companion/src/main.mjs': 'console.log(1)\n', 'companion/package.json': '{}\n', 'companion/skills/a.md': 'skill',
             'plugin/kritamcp/__init__.py': 'x', **(extra_files or {})}
    manifest_files = {}
    for name, text in files.items():
        if name.startswith('companion/'):
            path = bundled / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        manifest_files[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = {'version': '1.0.0', 'protocol_version': 2, 'build_id': build_id,
                'node_runtime': {'version': '22.23.2', 'archives': {}}, 'files': manifest_files, **(manifest_extra or {})}
    (bundled / 'release-manifest.json').write_text(json.dumps(manifest))
    (bundled / 'bundle-info.json').write_text(json.dumps({'built_at': built_at}))
    return bundled, manifest


class BundledReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.bundled, self.manifest = make_release(self.root)
        self.app_data = self.root / 'home' / 'Library' / 'Application Support' / 'KritaAgent'
        self.runtimes = self.root / 'home' / 'Library' / 'Application Support' / 'Creative Agent' / 'runtimes'
        self.node = self.runtimes / 'node-v22.23.2-darwin-arm64' / 'bin' / 'node'
        self.config_file = self.app_data / 'creative-agent-config.json'

    def install(self, **kwargs):
        return bundled_release.ensure_installed(self.bundled, self.app_data, self.runtimes, self.node, **kwargs)

    def release(self, build_id=None):
        return self.app_data / 'creative-agent' / (build_id or self.manifest['build_id'])

    def replace_release(self, build_id, built_at, **kwargs):
        shutil.rmtree(self.bundled.parent)
        self.bundled, self.manifest = make_release(self.root, build_id=build_id, built_at=built_at, **kwargs)

    # -- where the bundle is (M1, M2)
    def test_it_finds_the_bundle_beside_the_plugin_only_in_a_packaged_app(self):
        plugin = self.root / 'Resources' / 'krita' / 'pykrita' / 'kritamcp'
        plugin.mkdir(parents=True)
        self.assertEqual(bundled_release.bundled_dir(plugin), self.bundled.resolve())
        dev = self.root / 'checkout' / 'kritamcp'                                       # a dev layout: nothing beside it
        dev.mkdir(parents=True)
        self.assertIsNone(bundled_release.bundled_dir(dev))
        # the AppData folder of build copies has another name, so a dev layout can never mistake it for the bundle
        (self.root / 'x' / 'creative-agent' / 'companion').mkdir(parents=True)
        (self.root / 'x' / 'creative-agent' / 'release-manifest.json').write_text('{}')
        (self.root / 'x' / 'a' / 'b' / 'kritamcp').mkdir(parents=True)
        self.assertIsNone(bundled_release.bundled_dir(self.root / 'x' / 'a' / 'b' / 'kritamcp'))

    def test_a_shallow_plugin_path_is_none_not_an_error(self):
        self.assertIsNone(bundled_release.bundled_dir('/kritamcp'))
        self.assertIsNone(bundled_release.bundled_dir(pathlib.Path('/')))

    # -- which config (I1)
    def test_the_plugin_folder_config_wins_in_a_dev_layout_and_the_app_data_one_serves_the_bundle(self):
        plugin = self.root / 'checkout' / 'kritamcp'
        plugin.mkdir(parents=True)
        self.app_data.mkdir(parents=True)
        (self.app_data / bundled_release.CONFIG_NAME).write_text('{}')
        self.assertEqual(bundled_release.resolve_config(plugin, self.app_data), str(self.app_data / bundled_release.CONFIG_NAME),
                         'no plugin-folder config (the packaged app): the AppData one')
        (plugin / bundled_release.CONFIG_NAME).write_text('{}')
        self.assertEqual(bundled_release.resolve_config(plugin, self.app_data), str(plugin / bundled_release.CONFIG_NAME),
                         'dev fork and install.py --krita fork write one next to the plugin: it wins')
        (self.app_data / bundled_release.CONFIG_NAME).unlink()
        (plugin / bundled_release.CONFIG_NAME).unlink()
        self.assertEqual(bundled_release.resolve_config(plugin, self.app_data), str(plugin / bundled_release.CONFIG_NAME),
                         'neither: the plugin folder, where an installer would write it')
        self.assertEqual(bundled_release.resolve_config(plugin, None), str(plugin / bundled_release.CONFIG_NAME), 'stock Krita')

    # -- first use
    def test_first_use_copies_the_companion_and_writes_the_config(self):
        config = self.install()
        self.assertEqual(config, self.config_file)
        self.assertEqual((self.release() / 'companion' / 'src' / 'main.mjs').read_text(), 'console.log(1)\n')
        self.assertTrue((self.release() / 'release-manifest.json').is_file())
        self.assertTrue((self.release() / bundled_release.COMPLETE).is_file())
        self.assertFalse((self.release() / 'plugin').exists())                       # only the companion is copied out
        settings = json.loads(config.read_text())
        self.assertEqual(settings['companion'], str(self.release() / 'companion' / 'src' / 'main.mjs'))
        self.assertEqual(settings['node_runtimes'], str(self.runtimes))
        self.assertEqual(settings['node_runtime']['version'], '22.23.2')
        self.assertTrue(os.path.isabs(settings['paintings_dir']))
        self.assertTrue(pathlib.Path(settings['paintings_dir']).is_dir())
        self.assertEqual(settings['bridge_url'], 'http://127.0.0.1:5679')
        self.assertEqual(settings['build_id'], self.manifest['build_id'])
        self.assertEqual(settings['built_at'], '2026-10-19T12:00:00Z')
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in (self.app_data / 'creative-agent').iterdir()], [self.manifest['build_id']])   # no temporary folder left

    def test_it_is_idempotent_and_an_existing_complete_install_is_left_alone(self):
        self.install()
        (self.release() / 'companion' / 'src' / 'main.mjs').write_text('local edit')
        before = self.config_file.stat().st_mtime_ns
        self.install()
        self.assertEqual((self.release() / 'companion' / 'src' / 'main.mjs').read_text(), 'local edit')
        self.assertEqual(self.config_file.stat().st_mtime_ns, before)

    def test_the_bundle_is_hashed_only_when_installing(self):
        calls = []
        original = bundled_release.verify_companion
        bundled_release.verify_companion = lambda *a, **k: (calls.append(1), original(*a, **k))[1]
        try:
            self.install()
            self.install()
            self.install()
        finally:
            bundled_release.verify_companion = original
        self.assertEqual(len(calls), 1, 'verified once, when copying; a later Start press reads the manifest only')

    def test_a_tampered_file_extra_file_or_manifest_is_refused_and_nothing_is_installed(self):
        (self.bundled / 'companion' / 'src' / 'main.mjs').write_text('tampered')
        with self.assertRaises(bundled_release.BundledReleaseError):
            self.install()
        self.assertFalse((self.app_data / 'creative-agent').exists() and any((self.app_data / 'creative-agent').iterdir()))
        self.assertFalse(self.config_file.exists())
        (self.bundled / 'companion' / 'src' / 'main.mjs').write_text('console.log(1)\n')
        (self.bundled / 'companion' / 'extra.js').write_text('x')                        # not in the manifest
        with self.assertRaises(bundled_release.BundledReleaseError):
            self.install()
        (self.bundled / 'companion' / 'extra.js').unlink()
        (self.bundled / 'release-manifest.json').write_text('{not json')
        with self.assertRaises(bundled_release.BundledReleaseError):
            self.install()

    def test_a_manifest_entry_that_climbs_out_of_the_companion_folder_is_refused(self):
        (self.root / 'secret.txt').write_text('outside')
        manifest = json.loads((self.bundled / 'release-manifest.json').read_text())
        manifest['files']['companion/../../../secret.txt'] = hashlib.sha256(b'outside').hexdigest()
        (self.bundled / 'release-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(bundled_release.BundledReleaseError):
            self.install()
        self.assertFalse(self.config_file.exists())

    def test_a_link_in_the_companion_is_refused(self):
        os.symlink('/etc/hosts', self.bundled / 'companion' / 'link')
        with self.assertRaises(bundled_release.BundledReleaseError):
            self.install()

    def test_a_crash_while_copying_leaves_no_half_install(self):
        original = bundled_release.shutil.copytree
        def broken(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('disk full')
        bundled_release.shutil.copytree = broken
        try:
            with self.assertRaises(OSError):
                self.install()
        finally:
            bundled_release.shutil.copytree = original
        self.assertEqual(list((self.app_data / 'creative-agent').iterdir()), [])
        self.assertFalse(self.config_file.exists())
        self.install()                                                                    # and the next start works
        self.assertTrue((self.release() / 'companion' / 'src' / 'main.mjs').is_file())

    # -- a broken or stale copy, old builds (I3)
    def test_a_copy_without_its_completion_marker_is_broken_and_replaced(self):
        broken = self.release()
        (broken / 'companion' / 'src').mkdir(parents=True)
        (broken / 'companion' / 'src' / 'main.mjs').write_text('half a file')
        self.install()
        self.assertEqual((self.release() / 'companion' / 'src' / 'main.mjs').read_text(), 'console.log(1)\n')
        self.assertTrue((self.release() / bundled_release.COMPLETE).is_file())

    def test_old_build_copies_and_leftovers_are_pruned_but_never_the_one_in_use_or_data(self):
        old = self.app_data / 'creative-agent' / hashlib.sha256(b'old').hexdigest()
        (old / 'companion').mkdir(parents=True)
        (old / 'companion' / 'x').write_text('x')
        (self.app_data / 'creative-agent' / 'data').mkdir()
        (self.app_data / 'creative-agent' / 'data' / 'chats.json').write_text('keep')
        stale = self.app_data / 'creative-agent' / '.release-abc'
        stale.mkdir()
        recent = self.app_data / 'creative-agent' / '.release-fresh'
        recent.mkdir()
        old_config_temp = self.app_data / '.config-xyz'
        old_config_temp.write_text('x')
        day_ago = time.time() - 2 * 86400
        for path in (stale, old_config_temp):
            os.utime(path, (day_ago, day_ago))
        self.install()
        names = sorted(p.name for p in (self.app_data / 'creative-agent').iterdir())
        self.assertEqual(names, sorted(['data', '.release-fresh', self.manifest['build_id']]))   # old build and the day-old stage are gone
        self.assertEqual((self.app_data / 'creative-agent' / 'data' / 'chats.json').read_text(), 'keep')
        self.assertFalse(old_config_temp.exists())
        self.assertTrue(self.release().is_dir())

    def test_a_build_folder_an_unmanaged_config_still_points_at_is_not_pruned(self):
        old = self.app_data / 'creative-agent' / hashlib.sha256(b'old').hexdigest()
        (old / 'companion' / 'src').mkdir(parents=True)
        (old / 'companion' / 'src' / 'main.mjs').write_text('theirs')
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps({'companion': str(old / 'companion' / 'src' / 'main.mjs')}))
        self.install()
        self.assertTrue(old.is_dir())

    # -- the config (I2, I4, M4)
    def test_a_config_the_artist_or_the_installer_made_is_not_replaced(self):
        self.app_data.mkdir(parents=True)
        self.config_file.write_text(json.dumps({'companion': '/their/main.mjs', 'build_id': 'old'}))
        self.install()
        self.assertEqual(json.loads(self.config_file.read_text())['companion'], '/their/main.mjs')

    def test_an_unreadable_config_is_left_alone_and_reported_by_name(self):
        self.app_data.mkdir(parents=True)
        self.config_file.write_text(json.dumps({'companion': '/their/main.mjs'}))
        self.config_file.chmod(0)
        try:
            with self.assertRaises(bundled_release.BundledReleaseError) as raised:
                self.install()
            self.assertIn('creative-agent-config.json', str(raised.exception))
        finally:
            self.config_file.chmod(0o600)
        self.assertEqual(json.loads(self.config_file.read_text())['companion'], '/their/main.mjs')   # not overwritten

    def test_a_corrupt_or_empty_config_gets_a_message_that_names_the_file(self):
        self.app_data.mkdir(parents=True)
        for text in ('', '{not json', '[1, 2]'):
            self.config_file.write_text(text)
            with self.assertRaises(bundled_release.BundledReleaseError) as raised:
                bundled_release.load_config(self.config_file)
            self.assertIn('creative-agent-config.json', str(raised.exception))
        self.config_file.write_text('{"companion": "x"}')
        self.assertEqual(bundled_release.load_config(self.config_file), {'companion': 'x'})
        with self.assertRaises(bundled_release.BundledReleaseError) as raised:
            bundled_release.load_config(self.app_data / 'nothing-here.json')
        self.assertIn('nothing-here.json', str(raised.exception))

    def test_a_newer_build_updates_what_it_owns_and_keeps_everything_else(self):
        self.install()
        settings = json.loads(self.config_file.read_text())
        settings.update({'paintings_dir': '/Volumes/Art/paintings', 'project_root': '/Volumes/Art/paintings', 'bridge_url': 'http://127.0.0.1:6000',
                         'model_idle_timeout_ms': 5, 'something_new': {'a': 1}})
        self.config_file.write_text(json.dumps(settings))
        self.replace_release(BUILD_ID_2, '2026-11-01T00:00:00Z')
        self.install()
        updated = json.loads(self.config_file.read_text())
        self.assertEqual(updated['build_id'], BUILD_ID_2)
        self.assertIn(BUILD_ID_2, updated['companion'])
        self.assertEqual(updated['built_at'], '2026-11-01T00:00:00Z')
        self.assertEqual(updated['paintings_dir'], '/Volumes/Art/paintings')
        self.assertEqual(updated['bridge_url'], 'http://127.0.0.1:6000')
        self.assertEqual(updated['something_new'], {'a': 1})                              # unknown keys survive
        self.assertEqual(updated['model_idle_timeout_ms'], 5)
        self.assertFalse(self.release(BUILD_ID).exists(), 'the superseded build copy is pruned')

    def test_an_older_app_opened_after_a_newer_one_does_not_flip_the_config_back(self):
        self.replace_release(BUILD_ID_2, '2026-11-01T00:00:00Z')
        self.install()
        before = self.config_file.read_text()
        newer_mtime = self.config_file.stat().st_mtime_ns
        self.replace_release(BUILD_ID, '2026-10-19T12:00:00Z')                           # the older app starts
        self.install()
        self.assertEqual(self.config_file.read_text(), before)
        self.assertEqual(self.config_file.stat().st_mtime_ns, newer_mtime)
        self.assertTrue(self.release(BUILD_ID_2).is_dir(), 'the newer copy it points at is kept')

    def test_a_config_from_before_build_times_is_treated_as_older(self):
        self.install()
        settings = json.loads(self.config_file.read_text())
        del settings['built_at']
        self.config_file.write_text(json.dumps(settings))
        self.replace_release(BUILD_ID_2, '2020-01-01T00:00:00Z')
        self.install()
        self.assertEqual(json.loads(self.config_file.read_text())['build_id'], BUILD_ID_2)

    def test_the_paintings_folder_can_be_given_and_is_made(self):
        folder = self.root / 'paintings here'
        config = self.install(paintings_dir=folder)
        self.assertEqual(json.loads(config.read_text())['paintings_dir'], str(folder))
        self.assertTrue(folder.is_dir())


class StaleProfileCopyTests(unittest.TestCase):
    """An old kritamcp in the profile (installed by the old installer) kept its data folder outside <AppData>. When the app
    writes its first config, that data is COPIED over; and the panel can say what happened. Temporary folders only."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.bundled, self.manifest = make_release(self.root)
        self.app_data = self.root / 'home' / 'Library' / 'Application Support' / 'KritaAgent'
        self.runtimes = self.root / 'runtimes'
        self.old_data = self.root / 'home' / 'Library' / 'Application Support' / 'Creative Agent' / 'KritaAgent' / 'data'
        self.new_data = self.app_data / 'creative-agent' / 'data'
        self.config_file = self.app_data / 'creative-agent-config.json'

    def make_old_data(self):
        for name, text in {'chats/one.json': '{"title": "Sky"}', 'models/endpoints.json': '{"x": 1}', 'records.sqlite': 'SQLITE',
                           'capabilities.json': '{}', 'companion.lock': '1234', 'active-session.json': '{"s": 1}',
                           'chats/deep/companion.lock': 'x'}.items():
            path = self.old_data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def old_config(self, where, data_dir=None):
        (where).mkdir(parents=True, exist_ok=True)
        (where / bundled_release.CONFIG_NAME).write_text(json.dumps({'data_dir': str(data_dir or self.old_data), 'companion': '/old/main.mjs'}))

    def shadowed(self, name='pykrita-shadowed-2026-10-20'):
        return self.app_data / 'krita' / name / 'kritamcp'

    def install(self):
        return bundled_release.ensure_installed(self.bundled, self.app_data, self.runtimes, self.runtimes / 'node')

    def tree(self, root):
        return {str(p.relative_to(root)): p.read_text() for p in sorted(pathlib.Path(root).rglob('*')) if p.is_file()}

    def test_the_data_of_the_moved_copy_is_copied_not_moved_and_the_runtime_files_are_skipped(self):
        self.make_old_data()
        self.old_config(self.shadowed())
        before = self.tree(self.old_data)
        self.install()
        self.assertEqual(self.tree(self.old_data), before)                       # the original is exactly as it was
        copied = self.tree(self.new_data)
        self.assertEqual(copied, {k: v for k, v in before.items() if not k.endswith(('companion.lock', 'active-session.json'))})
        self.assertEqual(json.loads(self.config_file.read_text())['data_dir'], str(self.new_data))
        note = bundled_release.carried_data_note(self.app_data)
        self.assertEqual((note['result'], note['from'], note['to']), ('copied', str(self.old_data), str(self.new_data)))
        self.assertEqual(sorted(p.name for p in (self.app_data / 'creative-agent').iterdir()),
                         sorted([self.manifest['build_id'], 'data', bundled_release.CARRIED_NOTE]))        # no staging folder left

    def test_the_old_config_still_in_the_profile_folder_is_used_too_and_the_live_one_wins(self):
        self.make_old_data()
        other = self.root / 'other' / 'data'
        (other / 'chats').mkdir(parents=True)
        (other / 'chats' / 'x.json').write_text('older')
        self.old_config(self.shadowed(), other)
        self.old_config(self.app_data / 'krita' / 'pykrita' / 'kritamcp')
        self.install()
        self.assertIn('chats/one.json', self.tree(self.new_data))

    def test_the_newest_moved_copy_with_a_data_folder_that_exists_is_chosen(self):
        self.make_old_data()
        self.old_config(self.shadowed('pykrita-shadowed-2026-10-01'), self.root / 'gone')
        self.old_config(self.shadowed('pykrita-shadowed-2026-10-02'))
        os.utime(self.shadowed('pykrita-shadowed-2026-10-02') / bundled_release.CONFIG_NAME, (2e9, 2e9))
        self.install()
        self.assertIn('records.sqlite', self.tree(self.new_data))

    def test_nothing_is_copied_when_the_new_data_exists_or_there_is_no_old_data_or_the_config_is_not_new(self):
        self.make_old_data()
        self.old_config(self.shadowed())
        self.new_data.mkdir(parents=True)
        (self.new_data / 'mine.json').write_text('new')
        self.install()
        self.assertEqual(self.tree(self.new_data), {'mine.json': 'new'})                      # never merged into, never replaced
        self.assertIsNone(bundled_release.carried_data_note(self.app_data))
        shutil.rmtree(self.app_data)
        shutil.rmtree(self.old_data)                                                          # the old data is gone
        self.old_config(self.shadowed())
        self.install()
        self.assertFalse(self.new_data.exists())
        self.assertIsNone(bundled_release.carried_data_note(self.app_data))

    def test_a_second_start_with_a_config_already_written_copies_nothing_more(self):
        self.make_old_data()
        self.old_config(self.shadowed())
        self.install()
        (self.old_data / 'chats' / 'two.json').write_text('later')
        self.install()
        self.assertNotIn('chats/two.json', self.tree(self.new_data))

    def test_damaged_or_odd_old_configs_are_ignored(self):
        self.make_old_data()
        (self.shadowed()).mkdir(parents=True)
        (self.shadowed() / bundled_release.CONFIG_NAME).write_text('{nope')
        for value in (None, 7, '', [], {}):
            folder = self.shadowed('pykrita-shadowed-2026-10-1%d' % len(str(value)))
            folder.mkdir(parents=True, exist_ok=True)
            (folder / bundled_release.CONFIG_NAME).write_text(json.dumps({'data_dir': value}))
        self.install()                                                                        # does not raise
        self.assertFalse(self.new_data.exists())

    def test_the_old_data_folder_being_the_new_one_or_a_file_is_not_copied(self):
        self.new_data.parent.mkdir(parents=True, exist_ok=True)
        self.old_config(self.shadowed(), self.new_data)
        self.install()
        self.assertFalse(self.new_data.exists())
        file = self.root / 'a-file'
        file.write_text('x')
        self.old_config(self.shadowed('pykrita-shadowed-2026-10-21'), file)
        self.install()
        self.assertFalse(self.new_data.exists())

    def test_a_failing_copy_leaves_no_half_data_and_the_install_still_works(self):
        self.make_old_data()
        self.old_config(self.shadowed())
        original = shutil.copytree
        def broken(source, *args, **kwargs):
            if pathlib.Path(source) != self.old_data:
                return original(source, *args, **kwargs)
            raise shutil.Error([('a', 'b', 'disk full')])
        shutil.copytree = broken
        try:
            config = self.install()
        finally:
            shutil.copytree = original
        self.assertTrue(config.is_file())
        self.assertFalse(self.new_data.exists())
        self.assertEqual([p.name for p in (self.app_data / 'creative-agent').iterdir() if p.name.startswith('.data-copy-')], [])
        note = bundled_release.carried_data_note(self.app_data)
        self.assertEqual(note['result'], 'failed')
        self.assertTrue(self.old_data.is_dir())

    # -- review fixes: a bounded, plausible source
    def home(self):
        return self.root / 'home'

    def test_a_data_dir_that_is_not_ours_is_never_copied(self):
        self.make_old_data()
        crowded = self.root / 'bigdir'
        (crowded / 'data').mkdir(parents=True)
        (crowded / 'data' / 'records.sqlite').write_text('x')
        (crowded / 'data' / 'chats').mkdir()
        looks_ok_but_named = self.root / 'notes'
        (looks_ok_but_named / 'chats').mkdir(parents=True)
        for name, target in {'root': '/', 'home': self.home(), 'application support': self.app_data.parent, 'app data': self.app_data,
                             'inside app data': self.app_data / 'creative-agent', 'the parent of the data': self.old_data.parent,
                             'wrong name': looks_ok_but_named, 'a parent holding data': crowded}.items():
            with self.subTest(name):
                shutil.rmtree(self.app_data, ignore_errors=True)
                self.old_config(self.shadowed(), target)
                os.environ['HOME'], saved = str(self.home()), os.environ.get('HOME')
                try:
                    self.install()
                finally:
                    os.environ['HOME'] = saved
                self.assertFalse(self.new_data.exists(), name)
                self.assertTrue(self.old_data.is_dir())

    def test_a_folder_that_is_not_data_by_content_is_not_copied(self):
        empty = self.root / 'x' / 'data'
        empty.mkdir(parents=True)
        (empty / 'photo.png').write_text('x')
        self.old_config(self.shadowed(), empty)
        self.install()
        self.assertFalse(self.new_data.exists())

    def test_a_too_large_tree_is_not_copied_and_the_note_says_how_to_copy_it_by_hand(self):
        self.make_old_data()
        self.old_config(self.shadowed())
        for limit in ('MAX_CARRY_FILES', 'MAX_CARRY_BYTES'):
            with self.subTest(limit):
                shutil.rmtree(self.app_data, ignore_errors=True)
                self.old_config(self.shadowed())
                saved = getattr(bundled_release, limit)
                setattr(bundled_release, limit, 3 if limit == 'MAX_CARRY_FILES' else 5)
                try:
                    self.install()
                finally:
                    setattr(bundled_release, limit, saved)
                self.assertFalse(self.new_data.exists())
                note = bundled_release.carried_data_note(self.app_data)
                self.assertEqual(note['result'], 'failed')
                self.assertIn('too large for an automatic copy', note['error'])
                self.assertIn('cp -R', note['by_hand'])
                self.assertIn(str(self.old_data), note['by_hand'])
                text = '\n'.join(bundled_release.shadow_notices(self.app_data))
                self.assertIn('cp -R', text)
                self.assertTrue(self.old_data.is_dir())

    def test_the_walk_does_not_follow_links_and_stops_early(self):
        self.make_old_data()
        (self.old_data / 'loop').symlink_to(self.old_data)                    # a cycle must not hang or recurse
        self.old_config(self.shadowed())
        self.install()
        self.assertTrue((self.new_data / 'loop').is_symlink())               # copied as a link
        self.assertIn('records.sqlite', self.tree(self.new_data))

    def test_the_default_thresholds_are_small_enough_for_the_gui_thread(self):
        self.assertLessEqual(bundled_release.MAX_CARRY_FILES, 50000)
        self.assertLessEqual(bundled_release.MAX_CARRY_BYTES, 500 * 1024 * 1024)

    # -- what the panel shows
    def test_notices_say_what_was_moved_and_copied_and_nothing_when_nothing_happened(self):
        self.assertEqual(bundled_release.shadow_notices(self.app_data), [])
        self.make_old_data()
        folder = self.shadowed()
        folder.mkdir(parents=True)
        (folder / 'build-info.json').write_text(json.dumps({'build_id': 'ec6fec2c' + '0' * 56}))
        self.old_config(folder)
        self.install()
        lines = bundled_release.shadow_notices(self.app_data)
        text = '\n'.join(lines)
        self.assertIn('ec6fec2c0000', text)
        self.assertIn(str(folder.parent), text)
        self.assertIn('moved', text)
        self.assertIn('not deleted', text)
        self.assertIn('copied', text)
        self.assertIn(str(self.old_data), text)

    def test_a_copy_without_build_info_is_named_as_such(self):
        folder = self.shadowed()
        folder.mkdir(parents=True)
        self.assertIn('no build id', '\n'.join(bundled_release.shadow_notices(self.app_data)))

    def test_a_plugin_running_from_the_profile_while_the_app_has_its_own_is_reported(self):
        app_plugin = self.root / 'Toska.app' / 'Contents' / 'Resources' / 'krita' / 'pykrita' / 'kritamcp'
        app_plugin.mkdir(parents=True)
        (app_plugin / '__init__.py').write_text('x')
        (app_plugin / 'build-info.json').write_text(json.dumps({'build_id': 'b' * 64}))
        profile_plugin = self.app_data / 'krita' / 'pykrita' / 'kritamcp'
        profile_plugin.mkdir(parents=True)
        (profile_plugin / 'build-info.json').write_text(json.dumps({'build_id': 'a' * 64}))
        text = bundled_release.profile_plugin_notice(profile_plugin, self.app_data, app_plugin)
        self.assertIn('aaaaaaaaaaaa', text)
        self.assertIn('bbbbbbbbbbbb', text)
        self.assertIn('profile', text)
        self.assertIsNone(bundled_release.profile_plugin_notice(app_plugin, self.app_data, app_plugin))        # running the app's own
        (profile_plugin / 'build-info.json').write_text(json.dumps({'build_id': 'b' * 64}))
        self.assertIsNone(bundled_release.profile_plugin_notice(profile_plugin, self.app_data, app_plugin))    # same build: no shadow
        self.assertIsNone(bundled_release.profile_plugin_notice(profile_plugin, None, app_plugin))             # stock Krita
        self.assertIsNone(bundled_release.profile_plugin_notice(profile_plugin, self.app_data, self.root / 'none'))   # no app plugin
        dev = self.root / 'checkout' / 'kritamcp'
        dev.mkdir(parents=True)
        self.assertIsNone(bundled_release.profile_plugin_notice(dev, self.app_data, app_plugin))               # not in the profile


if __name__ == '__main__':
    unittest.main()
