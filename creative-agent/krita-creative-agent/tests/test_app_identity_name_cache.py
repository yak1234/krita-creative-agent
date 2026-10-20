# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The build named Toska shows "Toska" even in a build folder configured before the rename.

An older cmake/modules/KritaAppIdentity.cmake wrote its derived name, "Krita Agent", into the CMake cache
(KRITA_APP_DISPLAY_NAME, KRITA_MACOS_BUNDLE_NAME). CMake keeps a cache value, so those folders stayed "Krita Agent"
(window titles, the About box, KAboutData, the menu bar) while KRITA_APP_OWN_SPLASH said Toska. The module now resets
exactly that old default, once, for the settings folder KritaAgent; any other value someone chose is kept.

Evaluated with cmake (no build): the same script-mode harness as test_toska_splash.py, and one real configure of a
tiny project so the cache is a real CMakeCache.txt.
"""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
MODULE = REPO / 'cmake/modules/KritaAppIdentity.cmake'
CMAKE = shutil.which('cmake')
MIGRATION = 'Krita Agent'
NOTE = 'old derived name "Krita Agent"'   # the STATUS line the migration prints


def run_script(folder, cached=None):
    """KritaAppIdentity.cmake in cmake's script mode, with these values already in the cache (-D makes cache entries).
    Returns (display name, bundle name, cached display name, cached bundle name, the STATUS lines that mention it)."""
    cached = cached or {}
    with tempfile.TemporaryDirectory(prefix='toska-name-') as out:
        out = pathlib.Path(out)
        (out / 'probe.cmake').write_text(
            'set(CMAKE_SCRIPT_MODE_FILE "")\n'
            'set(CMAKE_BINARY_DIR "${OUT}")\n'
            'include("${REPO}/cmake/modules/KritaAppIdentity.cmake")\n'
            'message("RESULT|${KRITA_APP_DISPLAY_NAME}|${KRITA_MACOS_BUNDLE_NAME}|'
            '$CACHE{KRITA_APP_DISPLAY_NAME}|$CACHE{KRITA_MACOS_BUNDLE_NAME}")\n')
        args = [CMAKE, f'-DREPO={REPO}', f'-DOUT={out}', f'-DKRITA_APP_SETTINGS_FOLDER={folder}']
        args += [f'-D{name}:STRING={value}' for name, value in cached.items()]
        run = subprocess.run(args + ['-P', str(out / 'probe.cmake')], capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        output = run.stdout + run.stderr
        line = next(l for l in output.splitlines() if l.startswith('RESULT|'))
        name, bundle, cached_name, cached_bundle = line.split('|')[1:]
        notes = [l for l in output.splitlines() if NOTE in l]
        return name, bundle, cached_name, cached_bundle, notes


@unittest.skipUnless(CMAKE, 'cmake is not installed')
class StaleDisplayNameTest(unittest.TestCase):
    def test_fresh_configure_gives_toska(self):
        name, bundle, cached_name, _, notes = run_script('KritaAgent')
        self.assertEqual((name, bundle, cached_name), ('Toska', 'Toska', ''))
        self.assertEqual(notes, [])

    def test_stale_krita_agent_with_folder_kritaagent_gives_toska_once(self):
        name, bundle, cached_name, cached_bundle, notes = run_script(
            'KritaAgent', {'KRITA_APP_DISPLAY_NAME': MIGRATION, 'KRITA_MACOS_BUNDLE_NAME': MIGRATION})
        self.assertEqual((name, bundle), ('Toska', 'Toska'))
        self.assertEqual((cached_name, cached_bundle), ('', ''), 'the cache is reset, so the next configure is quiet')
        self.assertEqual(len(notes), 1, notes)

    def test_stale_bundle_name_alone_is_reset_too(self):
        name, bundle, _, cached_bundle, notes = run_script('KritaAgent', {'KRITA_MACOS_BUNDLE_NAME': MIGRATION})
        self.assertEqual((name, bundle, cached_bundle), ('Toska', 'Toska', ''))
        self.assertEqual(len(notes), 1, notes)

    def test_an_explicit_value_is_kept(self):
        name, bundle, cached_name, _, notes = run_script('KritaAgent', {'KRITA_APP_DISPLAY_NAME': 'Something'})
        self.assertEqual((name, bundle, cached_name), ('Something', 'Something', 'Something'))
        self.assertEqual(notes, [])
        name, bundle, _, cached_bundle, _ = run_script('KritaAgent', {'KRITA_MACOS_BUNDLE_NAME': 'My Bundle'})
        self.assertEqual((name, bundle, cached_bundle), ('Toska', 'My Bundle', 'My Bundle'))

    def test_another_folder_keeps_krita_agent(self):
        name, bundle, cached_name, _, notes = run_script('Other', {'KRITA_APP_DISPLAY_NAME': MIGRATION})
        self.assertEqual((name, bundle, cached_name), (MIGRATION, MIGRATION, MIGRATION))
        self.assertEqual(notes, [])

    def test_stock_gives_krita(self):
        name, bundle, cached_name, _, notes = run_script('')
        self.assertEqual((name, bundle, cached_name), ('Krita', 'Krita', ''))
        self.assertEqual(notes, [])

    def test_a_real_build_folder_with_the_old_cache_line_is_migrated(self):
        # The line the main build's CMakeCache.txt holds, then a second configure that must stay quiet and Toska
        with tempfile.TemporaryDirectory(prefix='toska-name-cfg-') as top:
            top = pathlib.Path(top)
            source, build = top / 'src', top / 'build'
            source.mkdir()
            (source / 'CMakeLists.txt').write_text(
                'cmake_minimum_required(VERSION 3.16)\n'
                'project(toska_name_probe NONE)\n'
                f'include("{MODULE.as_posix()}")\n'
                'message(STATUS "RESULT|${KRITA_APP_DISPLAY_NAME}|${KRITA_MACOS_BUNDLE_NAME}")\n')

            def configure(*extra):
                run = subprocess.run([CMAKE, '-S', str(source), '-B', str(build), *extra],
                                     capture_output=True, text=True, timeout=120)
                self.assertEqual(run.returncode, 0, run.stderr)
                output = run.stdout + run.stderr
                result = next(l for l in output.splitlines() if 'RESULT|' in l).split('RESULT|')[1].split('|')
                notes = [l for l in output.splitlines() if NOTE in l]
                cache = (build / 'CMakeCache.txt').read_text()
                return result, notes, cache

            result, notes, cache = configure('-DKRITA_APP_DISPLAY_NAME:STRING=Krita Agent',
                                             '-DKRITA_MACOS_BUNDLE_NAME:STRING=Krita Agent')
            self.assertEqual(result, ['Toska', 'Toska'])
            self.assertEqual(len(notes), 1, notes)
            self.assertIn('KRITA_APP_DISPLAY_NAME:STRING=\n', cache)
            self.assertIn('KRITA_MACOS_BUNDLE_NAME:STRING=\n', cache)
            result, notes, _ = configure()
            self.assertEqual(result, ['Toska', 'Toska'])
            self.assertEqual(notes, [])


if __name__ == '__main__':
    unittest.main()
