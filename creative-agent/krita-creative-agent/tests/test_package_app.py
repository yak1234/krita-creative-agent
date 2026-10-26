# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of agent/package-app.sh's logic (agent/package_app.py), the first-run launcher (agent/app-launcher.c) and
agent/install-app.sh, on small fake bundles built in a temporary folder (never the 1.5 GB app, never the artist's files).

The Mach-O tests compile tiny programs with `cc`; they are skipped where there is no compiler or not macOS.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[3]
AGENT = pathlib.Path(os.environ.get('KRITA_AGENT_TEST_AGENT_DIR') or REPO / 'agent')   # another copy of agent/: to see a test fail on old code
SPEC = importlib.util.spec_from_file_location('package_app', AGENT / 'package_app.py')
package_app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_app)

_spec = importlib.util.spec_from_file_location('test_bundled_release_helpers', pathlib.Path(__file__).with_name('test_bundled_release.py'))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
make_release = _helpers.make_release
MACOS = sys.platform == 'darwin'
HAVE_CC = MACOS and shutil.which('cc') is not None
MACOS_ARM64 = MACOS and os.uname().machine == 'arm64'      # the app is built for Apple Silicon only


def run(*command, **kwargs):
    return subprocess.run([str(part) for part in command], capture_output=True, text=True, **kwargs)


def compile_c(directory, name, source, *flags):
    path = pathlib.Path(directory) / (name + '.c')
    path.write_text(source)
    out = pathlib.Path(directory) / name
    # clang leaves an empty krita-XXXXXX / u-XXXXXX folder in $TMPDIR when it builds a universal binary: keep it in the test's own folder
    scratch = pathlib.Path(directory) / '.cc-tmp'
    scratch.mkdir(exist_ok=True)
    result = run('cc', '-o', out, path, *flags, env={'PATH': '/usr/bin:/bin', 'TMPDIR': str(scratch)})
    assert result.returncode == 0, result.stderr
    return out


class FakeBundle:
    """A bundle with one executable that loads one library: a small stand-in for the real thing."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.app = self.root / 'Toska.app'
        self.contents = self.app / 'Contents'
        self.frameworks = self.contents / 'Frameworks'
        self.macos = self.contents / 'MacOS'
        for folder in (self.frameworks, self.macos):
            folder.mkdir(parents=True)
        build = self.root / 'build'
        build.mkdir()
        self.build = build
        lib = compile_c(build, 'libfoo.dylib', 'int foo(void) { return 1; }\n', '-dynamiclib', '-install_name', '@rpath/libfoo.dylib',
                       '-Wl,-headerpad_max_install_names')
        shutil.copy2(lib, self.frameworks / 'libfoo.dylib')
        self.lib_source = lib
        main = compile_c(build, 'main', 'int foo(void);\nint main(void) { return foo() - 1; }\n', str(lib),
                         '-Wl,-rpath,@executable_path/../Frameworks', '-Wl,-headerpad_max_install_names')
        shutil.copy2(main, self.macos / 'krita')
        self.main = self.macos / 'krita'
        with open(self.contents / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'local.kritaagent', 'CFBundleExecutable': 'krita',
                           'CFBundleName': 'Toska', 'KritaAgentBuild': 'abc'}, stream)

    def sign(self):
        package_app.sign_bundle(self.app, None, log=lambda *_: None)


class MachOParsingTests(unittest.TestCase):
    SAMPLE = '''Load command 9
          cmd LC_ID_DYLIB
      cmdsize 56
         name @rpath/libfoo.dylib (offset 24)
Load command 10
          cmd LC_LOAD_DYLIB
         name @rpath/QtCore.framework/Versions/A/QtCore (offset 24)
Load command 11
          cmd LC_LOAD_WEAK_DYLIB
         name /usr/lib/libSystem.B.dylib (offset 24)
Load command 12
          cmd LC_RPATH
      cmdsize 32
         path @loader_path/../../.. (offset 12)
Load command 13
          cmd LC_RPATH
         path /Users/someone/forks/krita/_install/lib (offset 12)
Load command 14
          cmd LC_LOAD_DYLIB
         name @rpath/QtCore.framework/Versions/A/QtCore (offset 24)
'''

    def test_reads_dependencies_rpaths_and_install_name_once_each(self):
        info = package_app.parse_load_commands(self.SAMPLE)
        self.assertEqual(info.deps, ['@rpath/QtCore.framework/Versions/A/QtCore', '/usr/lib/libSystem.B.dylib'])
        self.assertEqual(info.rpaths, ['@loader_path/../../..', '/Users/someone/forks/krita/_install/lib'])
        self.assertEqual(info.ident, '@rpath/libfoo.dylib')

    def test_reads_the_minimum_macos_of_each_binary(self):
        build = 'Load command 1\n      cmd LC_BUILD_VERSION\n  cmdsize 32\n platform 1\n    minos 14.0\n      sdk 15.0\n'
        self.assertEqual(package_app.parse_load_commands(build).minos, (14, 0, 0))
        old = 'Load command 1\n      cmd LC_VERSION_MIN_MACOSX\n  cmdsize 16\n  version 12.0\n      sdk 13.1\n'
        self.assertEqual(package_app.parse_load_commands(old).minos, (12, 0, 0))
        self.assertIsNone(package_app.parse_load_commands(self.SAMPLE).minos)

    def test_a_binary_needing_a_newer_macos_than_the_app_declares_is_a_problem(self):
        # onnxruntime (minos 14.0) shipped in an app that declared macOS 12: on 12 and 13 the models would not load.
        needs = {'Contents/Resources/x/libonnxruntime.1.dylib': (14, 0, 0), 'Contents/MacOS/krita': (12, 0, 0), 'Contents/Frameworks/new.dylib': (15, 1, 0)}
        self.assertEqual(package_app.version_problems('14', needs), ['Contents/Frameworks/new.dylib: needs macOS 15.1 but the app declares 14'])
        self.assertEqual(len(package_app.version_problems('12', needs)), 2)
        self.assertEqual(package_app.version_problems('15.1', needs), [])
        self.assertEqual(package_app.version_problems(None, needs), [], 'nothing declared: the packager always declares it (below)')

    def test_the_app_declares_macos_14(self):
        self.assertEqual(package_app.MINIMUM_MACOS, '14')
        self.assertEqual(package_app.system_requirements({'LSMinimumSystemVersion': '12'})['LSMinimumSystemVersion'], '14')

    def test_system_paths(self):
        self.assertTrue(package_app.is_system('/usr/lib/libz.1.dylib'))
        self.assertTrue(package_app.is_system('/System/Library/Frameworks/AppKit.framework/AppKit'))
        self.assertFalse(package_app.is_system('/opt/homebrew/lib/libpng.dylib'))
        self.assertFalse(package_app.is_system('@rpath/libz.dylib'))


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class SelfContainmentCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeBundle(self.temp.name)

    def test_a_clean_bundle_has_no_problems(self):
        self.assertEqual(package_app.check_bundle(self.fake.app), [])

    def test_a_library_that_is_missing_does_not_resolve(self):
        (self.fake.frameworks / 'libfoo.dylib').unlink()
        problems = package_app.check_bundle(self.fake.app)
        self.assertEqual(len(problems), 1)
        self.assertIn('@rpath/libfoo.dylib does not resolve inside the bundle', problems[0])

    def test_an_rpath_outside_the_bundle_is_reported(self):
        run('install_name_tool', '-add_rpath', '@executable_path/../../../../lib', self.fake.main)
        run('install_name_tool', '-add_rpath', '/opt/homebrew/lib', self.fake.main)
        problems = ' '.join(package_app.check_bundle(self.fake.app))
        self.assertIn('leaves the bundle', problems)
        self.assertIn('absolute rpath /opt/homebrew/lib', problems)

    def test_an_absolute_dependency_in_a_build_tree_is_reported(self):
        tree = pathlib.Path(self.temp.name) / 'forks' / 'krita-master' / '_install' / 'lib'
        tree.mkdir(parents=True)
        shutil.copy2(self.fake.lib_source, tree / 'libfoo.dylib')
        run('install_name_tool', '-change', '@rpath/libfoo.dylib', str(tree / 'libfoo.dylib'), self.fake.main)
        problems = package_app.check_bundle(self.fake.app)
        self.assertTrue(any('absolute dependency' in p and '_install' in p for p in problems), problems)

    def test_a_loader_path_dependency_inside_the_bundle_is_fine_and_outside_is_not(self):
        run('install_name_tool', '-change', '@rpath/libfoo.dylib', '@executable_path/../Frameworks/libfoo.dylib', self.fake.main)
        self.assertEqual(package_app.check_bundle(self.fake.app), [])
        (self.fake.frameworks / 'libfoo.dylib').unlink()
        self.assertEqual(len(package_app.check_bundle(self.fake.app)), 1)

    def test_a_stale_absolute_install_name_is_reported(self):
        run('install_name_tool', '-id', '/Users/x/forks/krita-master/_install/lib/libfoo.dylib', self.fake.frameworks / 'libfoo.dylib')
        problems = package_app.check_bundle(self.fake.app)
        self.assertTrue(any('install name' in p for p in problems), problems)

    def test_universal_and_symlinks_are_handled(self):
        os.symlink('libfoo.dylib', self.fake.frameworks / 'libfoo.1.dylib')      # a link is not a second Mach-O file
        self.assertEqual(len(package_app.macho_files(self.fake.app)), 2)
        self.assertTrue(package_app.is_macho(self.fake.main))
        self.assertFalse(package_app.is_macho(self.fake.contents / 'Info.plist'))
        self.assertFalse(package_app.is_macho(self.fake.frameworks / 'libfoo.1.dylib'))


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class SigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeBundle(self.temp.name)

    def test_ad_hoc_signing_is_inside_out_and_verifies_strictly(self):
        self.fake.sign()
        ok, message = package_app.verify_signature(self.fake.app)
        self.assertTrue(ok, message)
        details = run('codesign', '-dv', self.fake.app).stderr
        self.assertIn('Identifier=local.kritaagent', details)
        self.assertIn('Signature=adhoc', details)

    def test_a_changed_file_breaks_the_seal(self):
        self.fake.sign()
        (self.fake.contents / 'Frameworks' / 'new-file.txt').write_text('x')
        self.assertFalse(package_app.verify_signature(self.fake.app)[0])

    def test_nothing_is_run_from_a_bundle_whose_signature_is_invalid(self):
        self.fake.sign()
        self.assertEqual(package_app.invalid_signatures(self.fake.app), [])
        package_app.require_runnable(self.fake.app)                                  # passes
        run('install_name_tool', '-add_rpath', '@executable_path/../Frameworks/x', self.fake.main)   # edits without re-signing
        self.assertEqual(package_app.invalid_signatures(self.fake.app), [str(self.fake.main)])
        with self.assertRaises(RuntimeError) as raised:
            package_app.require_runnable(self.fake.app)
        self.assertIn('refusing to run', str(raised.exception))
        with self.assertRaises(RuntimeError):
            package_app.smoke_test(self.fake.app, log=lambda *_: None)               # refuses before executing anything
        package_app.adhoc_sign(self.fake.main)                                       # signing again makes it runnable
        self.assertEqual(package_app.invalid_signatures(self.fake.app), [])

    def test_the_companions_native_files_stay_as_the_release_made_them_and_the_app_still_verifies(self):
        # onnxruntime-node's binaries (element shapes) are files of the companion, checked against the release manifest when
        # the plugin installs the companion: re-signing or editing them would make the companion refuse itself.
        native = self.fake.contents / 'Resources/creative-agent-bundle/companion/node_modules/onnxruntime-node/bin/napi-v6/darwin/arm64'
        native.mkdir(parents=True)
        lib = compile_c(self.fake.build, 'libonnx.dylib', 'int onnx(void) { return 2; }\n', '-dynamiclib', '-install_name', '@rpath/libonnx.1.dylib')
        shutil.copy2(lib, native / 'libonnx.1.dylib')
        before = (native / 'libonnx.1.dylib').read_bytes()
        self.assertNotIn(str(native / 'libonnx.1.dylib'), package_app.app_macho_files(self.fake.app))
        self.fake.sign()
        self.assertEqual((native / 'libonnx.1.dylib').read_bytes(), before, 'not re-signed')
        ok, message = package_app.verify_signature(self.fake.app)
        self.assertTrue(ok, message)
        self.assertEqual(package_app.invalid_signatures(self.fake.app), [])

    def test_a_named_identity_that_is_not_in_the_keychain_fails_instead_of_signing_ad_hoc(self):
        with self.assertRaises(RuntimeError):
            package_app.sign_bundle(self.fake.app, 'Krita Agent Test Identity That Does Not Exist', log=lambda *_: None)


ONNX_BINARIES = ('onnxruntime_binding.node', 'libonnxruntime.1.dylib')


def onnx_files(platforms):
    """A release's onnxruntime-node (element shapes' runtime) with binaries for the given <platform>/<arch> folders."""
    files = {'companion/node_modules/onnxruntime-node/package.json': '{"name": "onnxruntime-node"}',
             'companion/node_modules/onnxruntime-node/dist/index.js': 'x', 'companion/node_modules/onnxruntime-common/package.json': '{}'}
    for platform in platforms:
        for name in ONNX_BINARIES:
            files['companion/node_modules/onnxruntime-node/bin/napi-v6/%s/%s' % (platform, name)] = 'binary ' + name
    return files


class LayoutTests(unittest.TestCase):
    def make_complete(self, root, onnx=('darwin/arm64',)):
        contents = pathlib.Path(root) / 'Toska.app' / 'Contents'
        for path in ('MacOS/krita', 'MacOS/krita-app', 'MacOS/kritarunner', 'Resources/kritaplugins/a.xmlgui',
                     'Resources/krita/pykrita/kritamcp/__init__.py', 'Resources/krita/pykrita/kritamcp.desktop',
                     'Resources/krita/pykrita/kritamcp/_vendor/macos-arm64/numpy/__init__.py', 'Resources/LICENSES/README.txt',
                     'Resources/LICENSES/THIRD-PARTY-NOTICES.txt', 'Resources/LICENSES/GPL-3.0-or-later.txt', 'Resources/BUILD.txt',
                     'Resources/etc/fonts/fonts.conf', 'Resources/krita-python-libs/krita/__init__.py',
                     'Resources/krita-python-libs/PyKrita/krita.so', 'PlugIns/platforms/libqcocoa.dylib', 'PlugIns/kritapykrita.so',
                     'Frameworks/Python.framework/Versions/3.13/lib/x', 'Frameworks/QtCore.framework/Versions/A/QtCore'):
            (contents / path).parent.mkdir(parents=True, exist_ok=True)
            (contents / path).write_text('x')
        release = pathlib.Path(root) / 'rel'
        bundled, manifest = make_release(release, extra_files=onnx_files(onnx))          # a valid companion in Resources/creative-agent
        shutil.copytree(bundled, contents / 'Resources' / 'creative-agent-bundle')
        (contents / 'Resources/krita/pykrita/kritamcp/build-info.json').write_text(
            json.dumps({'build_id': manifest['build_id'], 'protocol_version': manifest.get('protocol_version', 2)}))
        os.symlink('3.13', contents / 'Frameworks/Python.framework/Versions/Current')
        os.symlink('Resources', contents / 'share')
        os.symlink('Resources/etc', contents / 'etc')
        with open(contents / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'local.kritaagent', 'CFBundleExecutable': 'krita', 'KritaAgentBuild': 'abc'}, stream)
        return contents.parent

    def test_a_complete_layout_has_no_problems_and_each_missing_part_is_named(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            bundle = self.make_complete(root)
            self.assertEqual(package_app.layout_problems(bundle), [])
            shutil.rmtree(bundle / 'Contents/Resources/krita/pykrita/kritamcp/_vendor')
            os.remove(bundle / 'Contents/share')
            plist = bundle / 'Contents/Info.plist'
            with open(plist, 'wb') as stream:
                plistlib.dump({'CFBundleIdentifier': 'org.krita', 'CFBundleExecutable': 'krita'}, stream)
            problems = ' | '.join(package_app.layout_problems(bundle))
            self.assertIn('no vendored numpy', problems)
            self.assertIn('Contents/share should be a symlink to Resources', problems)
            self.assertIn("CFBundleIdentifier is 'org.krita'", problems)
            self.assertIn('no KritaAgentBuild', problems)
            (bundle / 'Contents/Resources/creative-agent-bundle/companion/src/main.mjs').write_text('tampered')   # the companion must match its manifest
            self.assertIn('the bundled companion', ' | '.join(package_app.layout_problems(bundle)))

    def test_a_plugin_that_does_not_carry_the_companions_build_id_is_a_problem(self):
        # The packaged app once shipped a plugin with no build-info.json: it said 'development-unverified' and the companion
        # refused it ("Reload the matching Creative Agent build") on every first run.
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            bundle = self.make_complete(root)
            info = bundle / 'Contents/Resources/krita/pykrita/kritamcp/build-info.json'
            self.assertEqual(package_app.layout_problems(bundle), [])
            info.write_text(json.dumps({'build_id': 'f' * 64, 'protocol_version': 2}))
            self.assertIn('plugin build id', ' | '.join(package_app.layout_problems(bundle)))
            info.unlink()
            self.assertIn('plugin build id', ' | '.join(package_app.layout_problems(bundle)))


    def test_the_companion_carries_onnx_runtime_for_this_platform_only(self):
        # onnxruntime-node ships every platform's binaries (~300 MB unpacked); the app keeps its own (darwin/arm64) only.
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            bundle = self.make_complete(root, onnx=('darwin/arm64', 'linux/x64', 'win32/arm64'))
            problems = ' | '.join(package_app.layout_problems(bundle))
            self.assertIn('onnxruntime-node binaries for other platforms', problems)
            self.assertIn('linux/x64', problems); self.assertIn('win32/arm64', problems)
            self.assertNotIn('bundled companion', problems, 'only the platform problem: the release matches its manifest')
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            bundle = self.make_complete(root, onnx=())
            self.assertIn('no onnxruntime-node binary for darwin/arm64', ' | '.join(package_app.layout_problems(bundle)))
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            bundle = self.make_complete(root, onnx=('darwin/arm64',))
            problems = ' | '.join(package_app.layout_problems(bundle, arch='x86_64'))   # the packager's own architecture decides
            self.assertIn('no onnxruntime-node binary for darwin/x64', problems)
            self.assertIn('darwin/arm64', problems)


def load_build_release():
    spec = importlib.util.spec_from_file_location('build_release_for_tests', REPO / 'creative-agent' / 'krita-creative-agent' / 'scripts' / 'build-release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OnnxRuntimeReleaseTests(unittest.TestCase):
    """build-release.py (which package-app.sh runs) copies onnxruntime-node with this platform's binaries only."""
    def test_only_this_platforms_binaries_are_copied(self):
        build_release = load_build_release()
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            modules = pathlib.Path(root) / 'node_modules'
            for name, text in onnx_files(('darwin/arm64', 'darwin/x64', 'linux/x64', 'linux/arm64', 'win32/x64')).items():
                path = modules / name.removeprefix('companion/node_modules/')
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            (modules / 'onnxruntime-node/script').mkdir(); (modules / 'onnxruntime-node/script/install.js').write_text('downloads CUDA')
            arm = modules / 'onnxruntime-node/bin/napi-v6/darwin/arm64'
            (arm / 'libonnxruntime.1.30.0.dylib').write_text('binary libonnxruntime.1.dylib')           # npm ships the library twice, as two identical files
            companion = pathlib.Path(root) / 'companion'; companion.mkdir()
            kept = build_release.copy_onnxruntime(modules, companion, 'darwin', 'arm64')
            folders = sorted(str(p.relative_to(companion / 'node_modules/onnxruntime-node/bin/napi-v6')) for p in
                             (companion / 'node_modules/onnxruntime-node/bin/napi-v6').glob('*/*'))
            self.assertEqual(folders, ['darwin/arm64'])
            kept_files = sorted(p.name for p in (companion / 'node_modules/onnxruntime-node/bin/napi-v6/darwin/arm64').iterdir())
            self.assertEqual(kept_files, ['libonnxruntime.1.dylib', 'onnxruntime_binding.node'], 'the identical copy under the longer name is left out')
            self.assertEqual(kept, 'darwin/arm64')
            self.assertTrue((companion / 'node_modules/onnxruntime-node/dist/index.js').is_file())
            self.assertTrue((companion / 'node_modules/onnxruntime-common/package.json').is_file())
            self.assertFalse((companion / 'node_modules/onnxruntime-node/script').exists(), 'no install scripts in the app')
            with self.assertRaises(ValueError):
                build_release.copy_onnxruntime(modules, pathlib.Path(root) / 'other', 'win32', 'ia32')

    @unittest.skipUnless(MACOS_ARM64, 'the release layout is the Apple Silicon app\'s (onnxruntime-node darwin/arm64 only): needs macOS on arm64')
    @unittest.skipUnless(shutil.which('node') and (REPO / 'creative-agent/krita-creative-agent/node_modules/.bin/esbuild').exists(),
                         'needs node and npm ci in krita-creative-agent')
    def test_the_bundled_worker_and_onnx_runtime_load_from_the_release_layout(self):
        build_release = load_build_release()
        root = REPO / 'creative-agent' / 'krita-creative-agent'
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as temp:
            companion = pathlib.Path(temp) / 'companion'; (companion / 'src').mkdir(parents=True)
            arch = 'arm64' if os.uname().machine == 'arm64' else 'x64'
            build_release.bundle_shape_worker(root, companion, root / 'node_modules/.bin/esbuild', root / 'node_modules', arch)
            build_release.validate_shape_worker(pathlib.Path(shutil.which('node')), companion)        # passes
            next(companion.glob('node_modules/onnxruntime-node/bin/napi-*/darwin/*/onnxruntime_binding.node')).unlink()
            with self.assertRaisesRegex(ValueError, 'shape worker'):
                build_release.validate_shape_worker(pathlib.Path(shutil.which('node')), companion)

    @unittest.skipUnless(MACOS_ARM64, 'the release layout is the Apple Silicon app\'s (onnxruntime-node darwin/arm64 only): needs macOS on arm64')
    @unittest.skipUnless(shutil.which('node') and (REPO / 'creative-agent/krita-creative-agent/node_modules/.bin/esbuild').exists(),
                         'needs node and npm ci in krita-creative-agent')
    def test_the_bundled_sharpening_worker_loads_onnx_runtime_from_the_release_layout(self):
        build_release = load_build_release()
        root = REPO / 'creative-agent' / 'krita-creative-agent'
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as temp:
            companion = pathlib.Path(temp) / 'companion'; (companion / 'src').mkdir(parents=True)
            arch = 'arm64' if os.uname().machine == 'arm64' else 'x64'
            build_release.bundle_shape_worker(root, companion, root / 'node_modules/.bin/esbuild', root / 'node_modules', arch)
            build_release.bundle_upscale_worker(root, companion, root / 'node_modules/.bin/esbuild')
            build_release.validate_upscale_worker(pathlib.Path(shutil.which('node')), companion)       # passes
            next(companion.glob('node_modules/onnxruntime-node/bin/napi-*/darwin/*/onnxruntime_binding.node')).unlink()
            with self.assertRaisesRegex(ValueError, 'sharpening worker'):
                build_release.validate_upscale_worker(pathlib.Path(shutil.which('node')), companion)

    def test_the_release_names_the_architecture_its_node_reported(self):
        text = (REPO / 'creative-agent' / 'krita-creative-agent' / 'scripts' / 'build-release.py').read_text()
        self.assertNotIn("'architecture': 'any'", text)
        self.assertIn("'architecture': details['architecture']", text)
        self.assertNotIn('platform.machine()', text, 'the architecture comes from the pinned Node, not the machine (Rosetta)')

    def test_the_release_bundles_the_shape_worker_beside_the_companion(self):
        text = (REPO / 'creative-agent' / 'krita-creative-agent' / 'scripts' / 'build-release.py').read_text()
        self.assertIn("src/shapes/worker.ts", text)
        self.assertIn("src/shapes-worker.mjs", text)
        self.assertIn("src/upscale/worker.ts", text)
        self.assertIn("src/upscale-worker.mjs", text)
        self.assertIn('--external:onnxruntime-node', text)


def build_launcher(directory, hook=True, folder='KritaAgent'):
    flags = ['-DSETTINGS_FOLDER="%s"' % folder] + (['-DKRITA_AGENT_TEST_HOOK'] if hook else [])
    out = pathlib.Path(directory) / ('krita' if not hook else 'krita-hook')
    result = run('cc', '-O1', '-Wall', '-Wextra', '-Werror', *flags, '-o', out, AGENT / 'app-launcher.c')
    assert result.returncode == 0, result.stderr
    return out


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class FirstRunDefaultsTests(unittest.TestCase):
    """The Python rule and the launcher's C rule (agent/app-launcher.c) must agree; and the launcher must never damage
    the artist's kritarc or write its marker when it did not do the job."""
    CASES = {
        'empty': b'',
        'other group only': b'[theme]\nTheme=Krita dark\n',
        'no trailing newline': b'[theme]\nTheme=Krita dark',
        'python group without the key': b'[python]\nenable_scripter=true\n\n[theme]\nTheme=x\n',
        'python group at the end, no newline': b'[theme]\nTheme=x\n\n[python]\nenable_scripter=true',
        'python header last, nothing after': b'[python]',
        'key already true': b'[python]\nenable_kritamcp=true\n',
        'key switched off by the artist': b'[python]\nenable_kritamcp=false\nenable_scripter=true\n',
        'key in another group is not ours': b'[other]\nenable_kritamcp=true\n',
        'spaces around the equals sign': b'[python]\nenable_kritamcp = false\n',
        'locale/immutable suffix counts as present': b'[python]\nenable_kritamcp[$i]=false\n',
        'CRLF line ends, key missing': b'[theme]\r\nTheme=x\r\n[python]\r\nenable_scripter=true\r\n',
        'CRLF line ends, key present': b'[python]\r\nenable_kritamcp=false\r\n',
        'UTF-8 byte order mark': b'\xef\xbb\xbf[python]\nenable_scripter=true\n',
        'byte order mark and key present': b'\xef\xbb\xbf[python]\nenable_kritamcp=false\n',
        'a similar key is not ours': b'[python]\nenable_kritamcp_extra=true\n',
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.launcher = build_launcher(self.root)
        self.n = 0

    def fresh_home(self):
        self.n += 1
        home = self.root / ('home%d' % self.n)
        folder = home / 'Library' / 'Preferences' / 'KritaAgent'
        folder.mkdir(parents=True)
        return home, folder

    def start(self, home):
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'CFFIXED_USER_HOME': str(home)}
        return run(self.launcher, '--agent-first-run-only', env=env)

    def test_python_rule(self):
        merge = package_app.merge_first_run_defaults
        self.assertEqual(merge(''), '[python]\nenable_kritamcp=true\n')
        self.assertEqual(merge('[theme]\nTheme=x\n'), '[theme]\nTheme=x\n\n[python]\nenable_kritamcp=true\n')
        self.assertEqual(merge('[python]\nenable_scripter=true\n'), '[python]\nenable_kritamcp=true\nenable_scripter=true\n')
        self.assertIsNone(merge('[python]\nenable_kritamcp=false\n'))               # the artist's choice stays
        self.assertIsNone(merge('[python]\nenable_kritamcp[$i]=false\n'))
        self.assertIn('[python]\nenable_kritamcp=true', merge('[other]\nenable_kritamcp=true\n'))

    def test_the_launcher_does_the_same_in_a_fresh_home_and_only_once(self):
        for name, existing in self.CASES.items():
            with self.subTest(name):
                home, folder = self.fresh_home()
                kritarc = folder / 'kritarc'
                if existing:
                    kritarc.write_bytes(existing)
                self.assertEqual(self.start(home).returncode, 0)
                expected = package_app.merge_first_run_defaults(existing.decode('utf-8'))
                self.assertEqual(kritarc.read_bytes() if kritarc.exists() else b'', existing if expected is None else expected.encode('utf-8'))
                self.assertTrue((folder / '.agent-first-run-1').exists())
                # A second run changes nothing, even if the artist since switched the plugin off.
                kritarc.write_bytes(b'[python]\nenable_kritamcp=false\n')
                self.start(home)
                self.assertEqual(kritarc.read_bytes(), b'[python]\nenable_kritamcp=false\n')

    def test_a_key_already_there_in_any_spelling_is_never_duplicated(self):
        home, folder = self.fresh_home()
        (folder / 'kritarc').write_bytes(b'[python]\nenable_kritamcp[$i]=false\n')
        self.start(home)
        self.assertEqual((folder / 'kritarc').read_bytes().count(b'enable_kritamcp'), 1)

    def test_an_unreadable_kritarc_is_left_alone_and_gets_no_marker(self):
        home, folder = self.fresh_home()
        kritarc = folder / 'kritarc'
        kritarc.write_bytes(b'[theme]\nTheme=x\n')
        kritarc.chmod(0)
        self.assertEqual(self.start(home).returncode, 0)
        kritarc.chmod(0o600)
        self.assertEqual(kritarc.read_bytes(), b'[theme]\nTheme=x\n')
        self.assertFalse((folder / '.agent-first-run-1').exists())

    def test_a_read_only_kritarc_or_folder_is_left_alone_and_gets_no_marker(self):
        home, folder = self.fresh_home()
        kritarc = folder / 'kritarc'
        kritarc.write_bytes(b'[theme]\nTheme=x\n')
        kritarc.chmod(0o444)
        self.start(home)
        self.assertEqual(kritarc.read_bytes(), b'[theme]\nTheme=x\n')
        self.assertFalse((folder / '.agent-first-run-1').exists())
        kritarc.chmod(0o600)
        folder.chmod(0o555)
        self.addCleanup(folder.chmod, 0o755)
        self.start(home)
        self.assertEqual(kritarc.read_bytes(), b'[theme]\nTheme=x\n')
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['kritarc'])      # no temporary file, no marker

    def test_a_folder_named_kritarc_is_left_alone(self):
        home, folder = self.fresh_home()
        (folder / 'kritarc').mkdir()
        self.assertEqual(self.start(home).returncode, 0)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['kritarc'])
        self.assertTrue((folder / 'kritarc').is_dir())

    def test_a_symlinked_kritarc_stays_a_link_and_its_target_is_changed(self):
        home, folder = self.fresh_home()
        elsewhere = self.root / 'dotfiles'
        elsewhere.mkdir()
        (elsewhere / 'kritarc-real').write_bytes(b'[theme]\nTheme=x\n')
        os.symlink(elsewhere / 'kritarc-real', folder / 'kritarc')
        self.assertEqual(self.start(home).returncode, 0)
        self.assertTrue((folder / 'kritarc').is_symlink())
        self.assertIn(b'enable_kritamcp=true', (elsewhere / 'kritarc-real').read_bytes())
        self.assertTrue((folder / '.agent-first-run-1').exists())
        self.assertEqual(sorted(p.name for p in elsewhere.iterdir()), ['kritarc-real'])
        home2, folder2 = self.fresh_home()                                             # a dangling link: nothing, no marker
        os.symlink(self.root / 'nowhere', folder2 / 'kritarc')
        self.start(home2)
        self.assertFalse((folder2 / '.agent-first-run-1').exists())
        self.assertFalse((self.root / 'nowhere').exists())

    def test_the_file_mode_is_kept_and_a_new_file_is_private(self):
        home, folder = self.fresh_home()
        (folder / 'kritarc').write_bytes(b'[theme]\nTheme=x\n')
        (folder / 'kritarc').chmod(0o640)
        self.start(home)
        self.assertEqual((folder / 'kritarc').stat().st_mode & 0o777, 0o640)
        home2, folder2 = self.fresh_home()
        self.start(home2)
        self.assertEqual((folder2 / 'kritarc').stat().st_mode & 0o777, 0o600)

    def test_concurrent_starts_leave_one_key_and_no_temporary_files(self):
        home, folder = self.fresh_home()
        (folder / 'kritarc').write_bytes(b'[theme]\nTheme=x\n[python]\nenable_scripter=true\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'CFFIXED_USER_HOME': str(home)}
        processes = [subprocess.Popen([str(self.launcher), '--agent-first-run-only'], env=env) for _ in range(12)]
        self.assertEqual([p.wait() for p in processes], [0] * 12)
        self.assertEqual((folder / 'kritarc').read_bytes(), b'[theme]\nTheme=x\n[python]\nenable_kritamcp=true\nenable_scripter=true\n')
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['.agent-first-run-1', 'kritarc'])

    def test_the_packaged_launcher_has_no_test_hooks_and_starts_the_real_executable_with_the_same_arguments(self):
        macos = self.root / 'Toska.app' / 'Contents' / 'MacOS'
        macos.mkdir(parents=True)
        shutil.copy2(build_launcher(self.root, hook=False), macos / 'krita')
        compile_c(macos, 'krita-app', '#include <stdio.h>\n#include <stdlib.h>\nint main(int c, char **v) { for (int i = 1; i < c; ++i) puts(v[i]);'
                  ' puts(getenv("PYTHONNOUSERSITE") ? getenv("PYTHONNOUSERSITE") : "unset"); puts(getenv("MLT_REPOSITORY")); return 7; }\n')
        home = self.root / 'home-exec'
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'CFFIXED_USER_HOME': str(home)}
        result = run(macos / 'krita', '--agent-first-run-only', 'a b', env=env)         # the hook is not there: passed through
        self.assertEqual(result.returncode, 7)
        contents = (self.root / 'Toska.app' / 'Contents').resolve()
        self.assertEqual(result.stdout.split('\n')[:4], ['--agent-first-run-only', 'a b', '1', str(contents / 'PlugIns/mlt')])
        self.assertTrue((home / 'Library/Preferences/KritaAgent/kritarc').exists())

    def test_the_environment_the_launcher_sets_is_what_the_python_side_expects(self):
        macos = self.root / 'Toska.app' / 'Contents' / 'MacOS'
        macos.mkdir(parents=True)
        shutil.copy2(self.launcher, macos / 'krita')
        result = run(macos / 'krita', '--agent-print-env', env={'PATH': '/usr/bin:/bin'})
        printed = dict(line.split('=', 1) for line in result.stdout.splitlines())
        self.assertEqual(printed, package_app.launcher_environment((self.root / 'Toska.app' / 'Contents').resolve()))


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class ShadowingPluginTests(unittest.TestCase):
    """A kritamcp copy in the profile's pykrita folder would be loaded BEFORE the plugin inside the app (verified on the
    artist's machine). The launcher renames it aside, only under the narrow conditions in app-launcher.c, never deleting."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.macos = self.root / 'Toska.app' / 'Contents' / 'MacOS'
        self.macos.mkdir(parents=True)
        shutil.copy2(build_launcher(self.root), self.macos / 'krita-hook')          # once: rewriting a running-before binary gets it killed
        shutil.copy2(build_launcher(self.root, hook=False), self.macos / 'krita')
        self.home = self.root / 'home'
        self.profile = self.home / 'Library' / 'Application Support' / 'KritaAgent' / 'krita'
        self.user = self.profile / 'pykrita'
        self.user.mkdir(parents=True)

    def bundle_plugin(self, build_id='b' * 64, info=True, manifest=True):
        folder = self.root / 'Toska.app' / 'Contents' / 'Resources' / 'krita' / 'pykrita'
        if manifest:
            release = folder.parents[1] / 'creative-agent-bundle'
            release.mkdir(parents=True, exist_ok=True)
            (release / 'release-manifest.json').write_text('{}')
        (folder / 'kritamcp').mkdir(parents=True)
        (folder / 'kritamcp' / '__init__.py').write_text('bundled\n')
        (folder / 'kritamcp.desktop').write_text('[Desktop Entry]\n')
        if info:
            (folder / 'kritamcp' / 'build-info.json').write_text(json.dumps({'version': '1', 'build_id': build_id}))
        return folder

    def user_plugin(self, build_id='a' * 64, info=True, desktop=True):
        folder = self.user / 'kritamcp'
        folder.mkdir()
        (folder / '__init__.py').write_text('old\n')
        (folder / 'creative-agent-config.json').write_text('{"data_dir": "/old"}\n')
        if info:
            (folder / 'build-info.json').write_text('{\n  "build_id" :  "%s"\n}\n' % build_id)
        if desktop:
            (self.user / 'kritamcp.desktop').write_text('[Desktop Entry]\nName=old\n')
        return folder

    def other_plugin(self):
        (self.user / 'scripter').mkdir()
        (self.user / 'scripter' / '__init__.py').write_text('theirs\n')
        (self.user / 'scripter.desktop').write_text('[Desktop Entry]\nName=theirs\n')

    def start(self, **extra):
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.home), 'CFFIXED_USER_HOME': str(self.home), **extra}
        return run(self.macos / 'krita-hook', '--agent-shadow-only', env=env, timeout=20)

    def shadowed(self):
        return sorted(p.name for p in self.profile.iterdir() if p.name.startswith('pykrita-shadowed-'))

    def snapshot(self):
        return sorted((str(p.relative_to(self.profile)), p.read_bytes() if p.is_file() else None) for p in self.profile.rglob('*'))

    def test_an_old_copy_with_another_build_is_renamed_aside_whole_and_nothing_else_moves(self):
        self.bundle_plugin()
        old = self.user_plugin()
        self.other_plugin()
        before = {str(p.relative_to(old)): p.read_bytes() for p in old.rglob('*') if p.is_file()}
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())
        self.assertFalse((self.user / 'kritamcp.desktop').exists())
        names = self.shadowed()
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r'^pykrita-shadowed-\d{4}-\d{2}-\d{2}$')
        moved = self.profile / names[0]
        self.assertEqual({str(p.relative_to(moved / 'kritamcp')): p.read_bytes() for p in (moved / 'kritamcp').rglob('*') if p.is_file()}, before)
        self.assertEqual((moved / 'kritamcp.desktop').read_text(), '[Desktop Entry]\nName=old\n')
        self.assertEqual(sorted(p.name for p in moved.iterdir()), ['kritamcp', 'kritamcp.desktop'])
        self.assertEqual((self.user / 'scripter' / '__init__.py').read_text(), 'theirs\n')          # another plugin: untouched
        self.assertTrue((self.user / 'scripter.desktop').exists())
        self.assertIn('a' * 64, result.stderr)                                                          # logged, with the old build
        self.assertIn(names[0], result.stderr)

    def test_a_copy_without_build_info_is_old_too(self):
        self.bundle_plugin()
        self.user_plugin(info=False)
        self.assertEqual(self.start().returncode, 0)
        self.assertEqual(len(self.shadowed()), 1)
        self.assertFalse((self.user / 'kritamcp').exists())

    def test_a_damaged_build_info_counts_as_no_build_id(self):
        self.bundle_plugin()
        old = self.user_plugin()
        (old / 'build-info.json').write_text('{"build_id": "abc')
        self.start()
        self.assertEqual(len(self.shadowed()), 1)

    def test_the_same_build_shadows_nothing_and_stays(self):
        self.bundle_plugin(build_id='c' * 64)
        self.user_plugin(build_id='c' * 64)
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.shadowed(), [])

    def test_a_link_a_file_or_a_folder_without_init_is_left_alone(self):
        self.bundle_plugin()
        checkout = self.root / 'checkout' / 'kritamcp'
        checkout.mkdir(parents=True)
        (checkout / '__init__.py').write_text('dev\n')
        os.symlink(checkout, self.user / 'kritamcp')                                                    # a developer's link
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)
        os.unlink(self.user / 'kritamcp')
        (self.user / 'kritamcp').write_text('a file\n')
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)
        os.unlink(self.user / 'kritamcp')
        (self.user / 'kritamcp').mkdir()
        (self.user / 'kritamcp' / 'notes.txt').write_text('no package\n')
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)

    def test_an_app_without_its_own_plugin_moves_nothing(self):
        self.user_plugin()                                                                              # no bundle_plugin()
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)
        folder = self.bundle_plugin()
        (folder / 'kritamcp.desktop').unlink()                                                          # half a plugin is none
        self.start()
        self.assertEqual(self.snapshot(), before)

    def test_the_developers_escape_variable_keeps_the_copy(self):
        self.bundle_plugin()
        self.user_plugin()
        before = self.snapshot()
        self.start(KRITA_AGENT_KEEP_PROFILE_PLUGIN='1')
        self.assertEqual(self.snapshot(), before)

    def test_no_profile_at_all_creates_nothing(self):
        self.bundle_plugin()
        shutil.rmtree(self.profile.parent)
        self.assertEqual(self.start().returncode, 0)
        self.assertFalse(self.profile.parent.exists())

    def test_a_second_stale_copy_the_same_day_gets_its_own_folder_and_the_first_is_kept(self):
        self.bundle_plugin()
        self.user_plugin(build_id='1' * 64)
        self.start()
        self.user_plugin(build_id='2' * 64)
        result = self.start()
        names = self.shadowed()
        self.assertEqual(len(names), 2)
        ids = sorted(json.loads((self.profile / n / 'kritamcp' / 'build-info.json').read_text())['build_id'] for n in names)
        self.assertEqual(ids, ['1' * 64, '2' * 64])
        self.start()                                                                                    # nothing left to move
        self.assertEqual(self.shadowed(), names)

    def test_the_packaged_launcher_moves_the_copy_before_it_starts_krita_and_still_passes_the_arguments(self):
        self.bundle_plugin()
        self.user_plugin()
        compile_c(self.macos, 'krita-app', '#include <stdio.h>\nint main(int c, char **v) { for (int i = 1; i < c; ++i) puts(v[i]); return 7; }\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.home), 'CFFIXED_USER_HOME': str(self.home)}
        result = run(self.macos / 'krita', 'one', env=env)
        self.assertEqual((result.returncode, result.stdout), (7, 'one\n'))
        self.assertFalse((self.user / 'kritamcp').exists())
        self.assertEqual(len(self.shadowed()), 1)
        result = run(self.macos / 'krita', '--agent-shadow-only', env=env)                              # no hook in the real one
        self.assertEqual(result.stdout, '--agent-shadow-only\n')

    # -- review fixes: the bundle must be a release with a readable build id, and the profile folders real
    def test_a_bundle_without_a_readable_build_id_moves_nothing(self):
        for text in (None, '', '{}', '{"build_id": ""}', '{"build_id": "abc', '{"build_id": 7}'):
            with self.subTest(text):
                shutil.rmtree(self.root / 'Toska.app' / 'Contents' / 'Resources', ignore_errors=True)
                folder = self.bundle_plugin(info=False)
                if text is not None:
                    (folder / 'kritamcp' / 'build-info.json').write_text(text)
                shutil.rmtree(self.user, ignore_errors=True)
                self.user.mkdir(parents=True)
                self.user_plugin()
                before = self.snapshot()
                self.assertEqual(self.start().returncode, 0)
                self.assertEqual(self.snapshot(), before)

    def test_an_app_that_is_not_a_release_moves_nothing(self):
        self.bundle_plugin(manifest=False)
        self.user_plugin()
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)

    def test_a_linked_pykrita_or_krita_folder_is_left_alone(self):
        self.bundle_plugin()
        self.user_plugin()
        real = self.root / 'elsewhere'
        self.user.rename(real)
        os.symlink(real, self.user)
        before = sorted(str(p.relative_to(real)) for p in real.rglob('*'))
        self.start()
        self.assertEqual(sorted(str(p.relative_to(real)) for p in real.rglob('*')), before)
        self.assertEqual(self.shadowed(), [])
        os.unlink(self.user)
        real.rename(self.user)
        moved = self.root / 'krita-real'
        self.profile.rename(moved)
        os.symlink(moved, self.profile)
        before = sorted(str(p.relative_to(moved)) for p in moved.rglob('*'))
        self.start()
        self.assertEqual(sorted(str(p.relative_to(moved)) for p in moved.rglob('*')), before)

    def test_a_build_info_that_is_a_pipe_or_huge_does_not_hang_or_count_as_an_id(self):
        self.bundle_plugin()
        old = self.user_plugin()
        (old / 'build-info.json').unlink()
        os.mkfifo(old / 'build-info.json')
        result = self.start()                                                    # must return (run has no timeout: guard it)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(self.shadowed()), 1)                                # no readable id: stale
        bundle = self.root / 'Toska.app' / 'Contents' / 'Resources' / 'krita' / 'pykrita' / 'kritamcp' / 'build-info.json'
        bundle.unlink()
        os.mkfifo(bundle)
        self.user_plugin()
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)                                # the app's id unreadable: nothing moves
        bundle.unlink()
        bundle.write_text(json.dumps({'build_id': 'b' * 64, 'pad': 'x' * 70000}))
        self.start()
        self.assertEqual(self.snapshot(), before)                                # over 64 KB: not read, so no id, so nothing moves

    def test_if_the_folder_cannot_be_moved_the_desktop_file_goes_back(self):
        self.bundle_plugin()
        old = self.user_plugin()
        os.chmod(old, 0o555)                                                     # a folder that cannot be renamed away
        self.addCleanup(lambda: os.path.isdir(old) and os.chmod(old, 0o755))
        before = self.snapshot()
        self.start()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.shadowed(), [])
        self.assertTrue((self.user / 'kritamcp.desktop').is_file())


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class InstallScriptTests(unittest.TestCase):
    INSTALL = str(AGENT / 'install-app.sh')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeBundle(self.temp.name)
        self.fake.sign()
        self.home = pathlib.Path(self.temp.name) / 'home'
        self.target = pathlib.Path(self.temp.name) / 'Applications'
        self.system_apps = pathlib.Path(self.temp.name) / 'SystemApplications'      # stands in for /Applications: never the real one

    def make_old_app(self, folder, bundle_id='local.kritaagent'):
        old = folder / 'Krita Agent.app'
        (old / 'Contents' / 'MacOS').mkdir(parents=True)
        with open(old / 'Contents' / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': bundle_id}, stream)
        return old

    def install(self, *args, **kwargs):
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.home), 'KRITA_AGENT_APPLICATIONS_DIR': str(self.system_apps)}
        return run('/bin/zsh', self.INSTALL, *args, env=env, **kwargs)

    def test_installs_and_replaces_in_place_without_leftovers(self):
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.target / 'Toska.app'
        self.assertTrue((installed / 'Contents/MacOS/krita').exists())
        (installed / 'OLD-MARK').write_text('old')                                   # something only the old copy has
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((installed / 'OLD-MARK').exists())
        self.assertEqual([p.name for p in self.target.iterdir()], ['Toska.app'])   # no staging or old copy left
        self.assertTrue(package_app.verify_signature(installed)[0])

    def test_the_old_name_is_replaced_by_the_new_app_and_never_left_beside_it(self):
        old = self.target / 'Krita Agent.app'
        (old / 'Contents').mkdir(parents=True)
        with open(old / 'Contents' / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'local.kritaagent'}, stream)
        (self.target / 'Notes.txt').write_text('mine')
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ['Notes.txt', 'Toska.app'])   # one app with the bundle id

    def test_the_old_app_in_the_other_applications_folder_is_replaced_too(self):
        # a plain install goes to one folder; the old app may be in the other (the system one, or ~/Applications)
        user_old = self.make_old_app(self.home / 'Applications')
        system_old = self.make_old_app(self.system_apps)
        stock = self.system_apps / 'krita.app'
        (stock / 'Contents').mkdir(parents=True)
        (stock / 'MARK').write_text('stock')
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / 'Toska.app').is_dir())
        self.assertFalse(user_old.exists())
        self.assertFalse(system_old.exists())
        self.assertEqual((stock / 'MARK').read_text(), 'stock')                       # never the stock Krita

    def test_the_old_app_in_another_folder_that_is_not_ours_stays(self):
        other = self.make_old_app(self.home / 'Applications', bundle_id='org.example.other')
        self.assertEqual(self.install('--to', self.target, self.fake.app).returncode, 0)
        self.assertTrue(other.is_dir())

    def test_a_running_old_app_in_another_folder_stops_the_install_and_nothing_is_changed(self):
        old = self.make_old_app(self.home / 'Applications')
        sleeper = compile_c(self.temp.name, 'sleeper', '#include <unistd.h>\nint main(void) { sleep(60); return 0; }\n')
        shutil.copy2(sleeper, old / 'Contents' / 'MacOS' / 'sleeper')
        process = subprocess.Popen([str(old / 'Contents' / 'MacOS' / 'sleeper')])
        try:
            result = self.install('--to', self.target, self.fake.app)
        finally:
            process.kill()
            process.wait()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertTrue(old.is_dir())
        self.assertFalse((self.target / 'Toska.app').exists())

    def test_removing_the_old_app_says_to_remake_the_desktop_link_and_dock_icon(self):
        old = self.make_old_app(self.home / 'Applications')
        (self.home / 'Desktop').mkdir(parents=True)
        link = self.home / 'Desktop' / 'Krita Agent'
        os.symlink(old, link)
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ln -s ~/Applications/Toska.app ~/Desktop/Toska', result.stdout + result.stderr)
        self.assertIn('Dock', result.stdout + result.stderr)
        self.assertIn(str(link), result.stdout + result.stderr)                        # a link to the removed app is named
        self.assertTrue(os.path.islink(link))                                          # and left alone

    def test_a_desktop_link_to_something_else_is_not_mentioned(self):
        self.make_old_app(self.home / 'Applications')
        (self.home / 'Desktop').mkdir(parents=True)
        link = self.home / 'Desktop' / 'Krita Agent'
        os.symlink('/usr/bin', link)
        result = self.install('--to', self.target, self.fake.app)
        self.assertNotIn(str(link), result.stdout + result.stderr)

    def test_no_old_app_no_remake_line(self):
        result = self.install('--to', self.target, self.fake.app)
        self.assertNotIn('Desktop', result.stdout + result.stderr)

    def test_an_app_under_the_old_name_that_is_not_ours_is_left_alone(self):
        other = self.target / 'Krita Agent.app'
        (other / 'Contents').mkdir(parents=True)
        with open(other / 'Contents' / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'org.example.other'}, stream)
        self.assertEqual(self.install('--to', self.target, self.fake.app).returncode, 0)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ['Krita Agent.app', 'Toska.app'])

    def test_the_old_name_running_stops_the_install(self):
        old = self.target / 'Krita Agent.app'
        macos = old / 'Contents' / 'MacOS'
        macos.mkdir(parents=True)
        with open(old / 'Contents' / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'local.kritaagent'}, stream)
        sleeper = compile_c(self.temp.name, 'sleeper', '#include <unistd.h>\nint main(void) { sleep(60); return 0; }\n')
        shutil.copy2(sleeper, macos / 'sleeper')
        process = subprocess.Popen([str(macos / 'sleeper')])
        try:
            result = self.install('--to', self.target, self.fake.app)
        finally:
            process.kill()
            process.wait()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertTrue(old.is_dir())
        self.assertFalse((self.target / 'Toska.app').exists())

    def test_removes_quarantine_from_the_installed_copy(self):
        run('xattr', '-w', 'com.apple.quarantine', '0081;00000000;Safari;', self.fake.main)
        self.assertEqual(self.install('--to', self.target, self.fake.app).returncode, 0)
        attributes = run('xattr', '-rl', self.target / 'Toska.app').stdout
        self.assertNotIn('com.apple.quarantine', attributes)

    def test_refuses_folders_macos_protects_in_any_spelling_and_through_links(self):
        for protected in ('Documents', 'Desktop', 'Downloads', 'DOCUMENTS', 'desktop', 'Library/CloudStorage', 'Library/Mobile Documents'):
            result = self.install('--to', self.home / protected / 'x', '--dry-run', self.fake.app)
            self.assertEqual(result.returncode, 2, protected)
            self.assertIn('refusing', result.stderr)
            self.assertFalse((self.home / protected).exists(), protected)             # not even created
        (self.home / 'Documents').mkdir(parents=True)
        os.symlink(self.home / 'Documents', self.home / 'Apps')                       # a link into a protected folder
        self.assertEqual(self.install('--to', self.home / 'Apps', '--dry-run', self.fake.app).returncode, 2)

    def test_refuses_the_inside_of_an_app_and_system_folders(self):
        inside = pathlib.Path(self.temp.name) / 'krita.app' / 'Contents'
        result = self.install('--to', inside, self.fake.app)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(inside.exists())
        for system in ('/', '/System', '/System/Library/x', '/usr/local', '/bin', '/Library/Foo', '/private/etc'):
            self.assertEqual(self.install('--to', system, '--dry-run', self.fake.app).returncode, 2, system)
        other = pathlib.Path(self.temp.name) / 'Other.APP' / 'x'                      # any app, any case
        self.assertEqual(self.install('--to', other, '--dry-run', self.fake.app).returncode, 2)

    def test_a_folder_with_stock_krita_is_left_alone_except_the_applications_folders(self):
        self.target.mkdir()
        (self.target / 'krita.app').mkdir()
        (self.target / 'krita.app' / 'MARK').write_text('stock')
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 2)
        self.assertIn('krita.app', result.stderr)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ['krita.app'])
        self.assertEqual((self.target / 'krita.app' / 'MARK').read_text(), 'stock')
        user_apps = self.home / 'Applications'                                          # the user's Applications is fine
        (user_apps / 'krita.app').mkdir(parents=True)
        self.assertEqual(self.install('--to', user_apps, self.fake.app).returncode, 0)
        self.assertTrue((user_apps / 'krita.app').is_dir())                             # untouched
        self.assertEqual(sorted(p.name for p in user_apps.iterdir()), ['Toska.app', 'krita.app'])

    def test_refuses_while_the_installed_app_is_running(self):
        self.assertEqual(self.install('--to', self.target, self.fake.app).returncode, 0)
        sleeper = compile_c(self.temp.name, 'sleeper', '#include <unistd.h>\nint main(void) { sleep(60); return 0; }\n')
        installed = self.target / 'Toska.app' / 'Contents' / 'MacOS' / 'sleeper'
        shutil.copy2(sleeper, installed)
        process = subprocess.Popen([str(installed)])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('is running', result.stderr)
        self.assertTrue(installed.exists())                                             # the old copy stays as it was

    def test_a_home_with_pattern_characters_is_still_protected(self):
        odd = pathlib.Path(self.temp.name) / 'ho[m]e*'                                # zsh pattern characters in the path
        (odd / 'Documents').mkdir(parents=True)
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(odd)}
        refused = run('/bin/zsh', self.INSTALL, '--to', odd / 'Documents' / 'x', '--dry-run', self.fake.app, env=env)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        fine = run('/bin/zsh', self.INSTALL, '--to', odd / 'Applications', '--dry-run', self.fake.app, env=env)
        self.assertEqual(fine.returncode, 0, fine.stderr)

    def test_the_running_check_ignores_case(self):
        self.assertEqual(self.install('--to', self.target, self.fake.app).returncode, 0)
        sleeper = compile_c(self.temp.name, 'sleeper', '#include <unistd.h>\nint main(void) { sleep(60); return 0; }\n')
        installed = self.target / 'Toska.app' / 'Contents' / 'MacOS' / 'sleeper'
        shutil.copy2(sleeper, installed)
        shouting = pathlib.Path(str(installed).replace('Toska.app', 'TOSKA.APP'))
        process = subprocess.Popen([str(shouting)])                                  # the same file, started by another spelling
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 3, result.stderr)

    def test_an_old_app_left_in_an_interrupted_installs_folder_is_put_back(self):
        self.target.mkdir()
        interrupted = self.target / '.krita-agent-install.999999' / 'old.app'         # a pid that is not running
        (interrupted / 'Contents').mkdir(parents=True)
        (interrupted / 'Contents' / 'MARK').write_text('the old app')
        (self.fake.contents / 'Frameworks' / 'extra.txt').write_text('breaks the seal, so the install itself stops')
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 4)
        self.assertIn('interrupted install', result.stderr)
        self.assertEqual((self.target / 'Toska.app' / 'Contents' / 'MARK').read_text(), 'the old app')   # restored, not lost
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ['Toska.app'])

    def test_refuses_something_that_is_not_the_packaged_app(self):
        other = pathlib.Path(self.temp.name) / 'Other.app'
        other.mkdir()
        self.assertEqual(self.install('--to', self.target, other).returncode, 2)

    def test_refuses_a_copy_that_does_not_verify_and_keeps_the_old_app(self):
        self.assertEqual(self.install('--to', self.target, self.fake.app).returncode, 0)
        (self.fake.contents / 'Frameworks' / 'extra.txt').write_text('breaks the seal')
        result = self.install('--to', self.target, self.fake.app)
        self.assertEqual(result.returncode, 4)
        self.assertTrue((self.target / 'Toska.app' / 'Contents/MacOS/krita').exists())
        self.assertEqual([p.name for p in self.target.iterdir()], ['Toska.app'])

    def test_help_prints_the_usage_lines(self):
        result = self.install('-h')
        self.assertEqual(result.returncode, 0)
        self.assertIn('agent/install-app.sh [--to DIR]', result.stdout)
        self.assertNotIn('set -euo', result.stdout)


notices = package_app.notices


def make_repo(root):
    """A git checkout with two commits and a publish-map, as the fork's main checkout has."""
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)
    def git(*args):
        return subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], capture_output=True, text=True, check=True).stdout.strip()
    git('init', '-q', '-b', 'main')
    (root / 'a.txt').write_text('1')
    git('add', '.')
    git('commit', '-q', '-m', 'one')
    first = git('rev-parse', 'HEAD')
    (root / 'a.txt').write_text('2')
    git('commit', '-q', '-am', 'two')
    second = git('rev-parse', 'HEAD')
    return git, first, second


class BuildRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name) / 'repo'
        self.git, self.first, self.second = make_repo(self.root)
        self.packaging = pathlib.Path(self.temp.name) / 'packaging'                    # a second clean checkout for the scripts
        make_repo(self.packaging)

    def publish(self, local, public=None):
        public = public or local
        (self.root / '.git' / 'publish-map').write_text('%s %s\n' % (local, public))
        self.git('update-ref', 'refs/remotes/public/main', public)

    def record(self, built_from=None, **flags):
        return notices.build_record(self.root, built_from or self.second[:7], packaging_root=self.packaging, **flags)

    def test_a_clean_published_head_is_accepted_and_its_public_hash_recorded(self):
        self.publish(self.second, self.first)                                            # the public hash differs from the local one
        record, problems = self.record()
        self.assertEqual(problems, [])
        self.assertEqual(record['commit'], self.second)
        self.assertEqual(record['public_commit'], self.first)
        statement = notices.source_statement(record)
        self.assertIn(self.first, statement)
        self.assertIn(self.second, statement)                                            # both are stated
        self.assertIn('https://github.com/yak1234/toska', statement)
        self.assertNotIn('@', statement)

    def test_a_dirty_tree_is_refused_unless_allowed_and_then_stamped(self):
        self.publish(self.second)
        (self.root / 'a.txt').write_text('changed')
        record, problems = self.record()
        self.assertTrue(any('uncommitted' in p for p in problems), problems)
        record, problems = self.record(allow_dirty=True)
        self.assertEqual(problems, [])
        self.assertTrue(any('dirty' in n for n in record['notes']))

    def test_a_dirty_packaging_checkout_is_refused_too(self):
        self.publish(self.second)
        (self.packaging / 'a.txt').write_text('changed')
        self.assertTrue(any('packaging' in p for p in self.record()[1]))

    def test_a_build_that_is_not_head_is_refused_unless_allowed_and_both_commits_are_stamped(self):
        self.publish(self.first)
        _, problems = self.record(built_from=self.first[:7])
        self.assertTrue(any('not from HEAD' in p for p in problems), problems)
        record, problems = self.record(built_from=self.first[:7], allow_stale=True)
        self.assertEqual(problems, [])
        self.assertEqual(record['commit'], self.first)                                   # THE commit is the one the binaries report
        self.assertIn(self.second[:12], ' '.join(record['notes']))

    def test_a_commit_the_checkout_does_not_know_is_refused(self):
        self.assertTrue(self.record(built_from='deadbee')[1])
        self.assertTrue(any('not in' in p for p in self.record(built_from='')[1]))

    def test_an_unpublished_commit_is_refused_unless_allowed(self):
        record, problems = self.record()
        self.assertTrue(any('public/main' in p for p in problems), problems)
        record, problems = self.record(allow_unpublished=True)
        self.assertEqual(problems, [])
        self.assertEqual(record['public_commit'], notices.NOT_PUBLISHED)
        self.assertIn('not published', notices.source_statement(record))

    def test_the_record_text_is_what_the_about_box_reads_back(self):
        self.publish(self.second)
        record, _ = self.record()
        parsed = notices.parse_record(notices.record_text(record))
        self.assertEqual(parsed['build commit'], self.second)
        self.assertEqual(parsed['source'], 'https://github.com/yak1234/toska')
        self.assertEqual(parsed['public commit'], self.second)
        self.assertNotIn('@', notices.record_text(record))


class DerivedNoticeTests(unittest.TestCase):
    def test_ffmpeg_facts_come_from_the_libraries_own_strings(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            lib = pathlib.Path(root) / 'libavutil.60.dylib'
            lib.write_bytes(b'\x00\x01junk\x00LGPL version 2.1 or later\x00 8.0.1-g1834eb471506fe3f6296aa844825ac317e51bd5b \x00'
                            b'8.0.1-g1834eb471506fe3f6296aa844825ac317e51bd5b\x00'
                            b'-Dlibaom_av1_encoder=enabled -Dlibaom=enabled -Dlibmp3lame=enabled -Dlibvpx=enabled -Dsdl2=enabled -Dzlib=enabled -Dlibvpl=auto\x00\x02')
            facts = notices.ffmpeg_facts(lib)
            self.assertEqual(facts['license'], 'LGPL version 2.1 or later')
            self.assertTrue(facts['version'].startswith('8.0.1-g'))
            self.assertEqual(notices.ffmpeg_libraries(facts['configuration']), ['libaom', 'libmp3lame', 'libvpx', 'sdl2', 'zlib'])      # not libaom_av1_encoder
            text = '\n'.join(notices.ffmpeg_notice(lib))
            self.assertIn('LGPL version 2.1 or later', text)
            self.assertIn('LAME', text)
            self.assertIn('https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz', text)
            self.assertNotIn('cisco', text.lower())
            self.assertNotIn('NOTE: this FFmpeg reports', text)                           # no GPL warning for an LGPL library
            # a GPL FFmpeg as Homebrew builds it (the OpenCV wheel's): the notice says so and names x264 with its licence
            lib.write_bytes(b'\x00libavutil license: GPL version 3 or later\x00--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 --enable-gpl --enable-version3'
                            b' --enable-libx264 --enable-libx265 --enable-libdav1d --enable-videotoolbox\x00')
            gpl = '\n'.join(notices.ffmpeg_notice(lib))
            self.assertIn('licence reported by the shipped libavutil: GPL version 3 or later', gpl)
            self.assertIn('configured with --enable-gpl --enable-version3', gpl)
            self.assertIn('x264: GPL-2.0-or-later', gpl)
            self.assertIn('ffmpeg-7.1.1.tar.xz', gpl)
            self.assertIn('Homebrew', gpl)
            self.assertNotIn('LGPL', gpl.split('codec and format')[0])

    def test_wheel_notices_have_the_full_expression_and_the_libraries_they_carry(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            root = pathlib.Path(root)
            expression = 'BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 AND LicenseRef-' + 'x' * 200
            dist = root / 'numpy-2.5.4.dist-info'
            (dist / 'licenses').mkdir(parents=True)
            (dist / 'METADATA').write_text('Metadata-Version: 2.4\nName: numpy\nVersion: 2.5.4\nLicense-Expression: %s\n\nbody' % expression)
            (dist / 'licenses' / 'LICENSE.txt').write_text('BSD')
            (dist / 'licenses' / 'LICENSES_bundled.txt').write_text('bundled')
            (root / 'numpy' / '.dylibs').mkdir(parents=True)
            (root / 'numpy' / '.dylibs' / 'libgfortran.5.dylib').write_text('x')
            (root / 'numpy' / '.dylibs' / 'libscipy_openblas64_.dylib').write_text('x')
            name, version, licence, files, carried = notices.python_package_notices(root)[0]
            self.assertEqual(licence, expression)                                         # not cut
            self.assertEqual(sorted(f.name for f in files), ['LICENSE.txt', 'LICENSES_bundled.txt'])
            self.assertEqual(carried, ['numpy/.dylibs/libgfortran.5.dylib', 'numpy/.dylibs/libscipy_openblas64_.dylib'])
            self.assertIn('GCC-exception', notices.wheel_library_licence('libgfortran.5.dylib'))
            self.assertIn('BSD-3-Clause', notices.wheel_library_licence('libscipy_openblas64_.dylib'))

    def test_companion_packages_outside_the_bundle_are_listed_from_their_own_package_json(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            modules = pathlib.Path(root) / 'node_modules'
            (modules / '@visioncortex' / 'vtracer' / 'pkg').mkdir(parents=True)
            (modules / '@visioncortex' / 'vtracer' / 'package.json').write_text(json.dumps({
                'name': '@visioncortex/vtracer', 'version': '1.0.0-alpha.4', 'license': 'MIT OR Apache-2.0',
                'repository': {'type': 'git', 'url': 'https://github.com/visioncortex/vtracer.git', 'directory': 'nodejs'}}))
            (modules / 'pyodide').mkdir()
            (modules / 'pyodide' / 'package.json').write_text(json.dumps({'name': 'pyodide', 'version': '1.2.3', 'license': 'MPL-2.0',
                                                                          'repository': 'github:pyodide/pyodide'}))
            (modules / 'stray').mkdir()                                     # no package.json: not a package
            found = notices.companion_package_notices(pathlib.Path(root))
            self.assertEqual(found, [('@visioncortex/vtracer', '1.0.0-alpha.4', 'MIT OR Apache-2.0', 'https://github.com/visioncortex/vtracer'),
                                     ('pyodide', '1.2.3', 'MPL-2.0', 'github:pyodide/pyodide')])
        self.assertEqual(notices.companion_package_notices(pathlib.Path('/nonexistent')), [])

    def test_models_downloaded_on_first_use_are_listed_from_the_release_with_their_licences(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            (pathlib.Path(root) / 'src').mkdir()
            shutil.copy2(REPO / 'creative-agent/krita-creative-agent/src/downloaded-models.json', pathlib.Path(root) / 'src/downloaded-models.json')
            text = '\n'.join(notices.downloaded_model_notices(pathlib.Path(root)))
            self.assertIn('not inside the app', text)
            self.assertIn('Real-ESRGAN x4plus (Sharpen goal): BSD-3-Clause, Copyright (c) 2021, Xintao Wang (https://github.com/xinntao/Real-ESRGAN)', text)
            self.assertIn('SAM 2.1 base-plus (element shapes): Apache-2.0', text)
            self.assertIn('pinned by SHA-256', text)
        self.assertEqual(notices.downloaded_model_notices(pathlib.Path('/nonexistent')), [])

    def test_the_qt_notice_states_the_right_to_replace_and_the_recipe(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            record = {'commit': 'c' * 40, 'public_commit': 'p' * 40, 'source': 'https://example.org/r', 'branch': 'main', 'notes': []}
            text = '\n'.join(notices.qt_notice(pathlib.Path(root), root, record))
            for needed in ('replace these Qt frameworks', 'codesign', 'reverse engineer', 'krita-deps-management', 'ext_qt', 'LGPL'):
                self.assertIn(needed, text)


class ProductNameTests(unittest.TestCase):
    """What the artist sees is Toska; internal identifiers keep their names until the profile migration (AGENT-FORK.md)."""

    def test_the_bundle_is_toska_and_the_info_plist_strings_say_so(self):
        self.assertEqual(package_app.APP_NAME, 'Toska.app')
        self.assertEqual(package_app.BUNDLE_ID, 'local.kritaagent')          # internal: the artist's profile is keyed by it
        self.assertEqual(package_app.SETTINGS_FOLDER, 'KritaAgent')
        plist = package_app.user_visible_strings({'CFBundleIdentifier': package_app.BUNDLE_ID})
        self.assertEqual((plist['CFBundleName'], plist['CFBundleDisplayName']), ('Toska', 'Toska'))
        self.assertEqual(plist['CFBundleIdentifier'], 'local.kritaagent')
        shown = [v for k, v in plist.items() if k != 'CFBundleIdentifier']
        self.assertFalse([v for v in shown if 'Krita Agent' in v], shown)
        for key in ('NSDocumentsFolderUsageDescription', 'NSDesktopFolderUsageDescription', 'NSDownloadsFolderUsageDescription',
                    'NSRemovableVolumesUsageDescription'):
            self.assertTrue(plist[key].startswith('Toska '), key)
        # the upstream credit stays
        self.assertIn('based on Krita', plist['NSHumanReadableCopyright'])
        self.assertIn('https://krita.org', plist['NSHumanReadableCopyright'])
        self.assertIn('GPL-3.0-or-later', plist['NSHumanReadableCopyright'])

    def test_the_build_record_and_the_notices_name_toska_and_keep_the_credit(self):
        record = {'commit': 'c' * 40, 'public_commit': 'p' * 40, 'source': 'https://example.org/r', 'branch': 'main',
                  'built_from': 'c' * 40, 'head': 'c' * 40, 'notes': [], 'date': '2026-10-20'}
        text = notices.record_text(record)
        self.assertTrue(text.startswith('Toska\n'))
        self.assertNotIn('Krita Agent', text)
        self.assertEqual(notices.parse_record(text)['build commit'], 'c' * 40)
        source = (AGENT / 'package_app.py').read_text() + (AGENT / 'package_notices.py').read_text()
        self.assertNotIn('Krita Agent', source.replace("'Krita Agent.app'", ''))   # no old name in a string, but the legacy folder name
        self.assertIn('is based on Krita (https://krita.org)', source)

    def test_the_resigning_command_in_the_qt_notice_names_the_new_bundle(self):
        with mock.patch.object(notices, 'deps_recipe', return_value=('https://example.org/deps', 'abc', 'main')), \
             mock.patch.object(notices, 'qt_facts', return_value='6.0'):
            lines = notices.qt_notice(pathlib.Path('/nonexistent'), pathlib.Path('/nonexistent'), {'commit': 'c' * 40, 'public_commit': 'p' * 40,
                                      'source': 'https://example.org/r', 'branch': 'main', 'built_from': '', 'head': '', 'notes': [], 'date': 'x'})
        self.assertTrue(any('"Toska.app"' in line for line in lines), lines)


class OutputFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.install = self.root / 'src' / '_install'
        self.install.mkdir(parents=True)
        self.home.mkdir()

    def refused(self, out, **kwargs):
        with self.assertRaises(package_app.Refused, msg=str(out)):
            package_app.check_output_folder(out, self.install, self.root / 'src', home=self.home, **kwargs)

    def test_applications_in_any_spelling_and_through_links_is_refused(self):
        self.refused('/Applications/zz')
        self.refused('/Applications')
        self.refused('/applications/ZZ')
        self.refused(self.home / 'Applications' / 'x')
        self.refused(self.root / 'Apps' / 'x', applications=self.root / 'Apps')
        os.symlink('/Applications', self.root / 'link')
        self.refused(self.root / 'link' / 'x')
        self.refused(os.path.relpath('/Applications/x'))                                    # a relative spelling

    def test_the_environment_override_stands_in_for_applications_in_tests(self):
        fake = self.root / 'FakeApplications'
        os.environ['KRITA_AGENT_APPLICATIONS_DIR'] = str(fake)
        try:
            self.refused(fake / 'zz-test')
        finally:
            del os.environ['KRITA_AGENT_APPLICATIONS_DIR']
        self.assertFalse(fake.exists())

    def test_system_folders_the_home_folder_and_app_bundles_are_refused(self):
        for bad in ('/', '/System/x', '/usr/local/x', '/Library/x', self.home, self.root / 'Other.APP' / 'x'):
            self.refused(bad)

    def test_a_folder_containing_or_inside_the_install_tree_is_refused(self):
        self.refused(self.root / 'src')
        self.refused(self.root)
        self.refused(self.install / 'out')
        package_app.check_output_folder(self.root / 'elsewhere' / '_package', self.install, self.root / 'src', home=self.home)

    def test_only_a_bundle_made_by_this_script_is_ever_replaced(self):
        bundle = self.root / 'out' / 'Toska.app'
        self.assertTrue(package_app.safe_to_replace(bundle))
        (bundle / 'Contents').mkdir(parents=True)
        self.assertFalse(package_app.safe_to_replace(bundle))                             # no plist: not ours
        with open(bundle / 'Contents' / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'org.krita'}, stream)
        self.assertFalse(package_app.safe_to_replace(bundle))
        with open(bundle / 'Contents' / 'Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'local.kritaagent'}, stream)
        self.assertTrue(package_app.safe_to_replace(bundle))


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class ReferenceScanTests(unittest.TestCase):
    HOME = '/Users/someone'
    TREE = '/Users/someone/forks/krita-master'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeBundle(self.temp.name)
        self.marks = package_app.reference_marks([self.TREE]) + (self.HOME,)

    def leaky_program(self, name):
        compile_c(self.fake.build, name, 'const char *a = "%(t)s/libs/ui/x.cpp"; const char *b = "%(t)s/_install/lib/libpython3.13.dylib";'
                  ' const char *c = "%(t)s/_build"; const char *d = "%(h)s/Library/Caches/x";'
                  ' int main(int argc, char **argv) { return (a && b && c && d && argc > 5) ? 0 : 0; }\n' % {'t': self.TREE, 'h': self.HOME})
        shutil.copy2(self.fake.build / name, self.fake.macos / name)
        return self.fake.macos / name

    def test_a_clean_bundle_passes(self):
        self.assertEqual(package_app.reference_problems(self.fake.app, self.marks), [])

    def test_baked_build_paths_are_found_even_when_they_look_like_source_files_or_the_known_constants(self):
        self.leaky_program('leaky')
        problems = ' | '.join(package_app.reference_problems(self.fake.app, self.marks))
        for needle in ('libs/ui/x.cpp', 'libpython3.13.dylib', '/_build'):
            self.assertIn(needle, problems)                      # nothing is whitelisted while it carries the artist's prefix
        compile_c(self.fake.build, 'home-only', 'const char *d = "%s/Library/Caches/x"; int main(void) { return d == 0; }\n' % self.HOME)
        shutil.copy2(self.fake.build / 'home-only', self.fake.macos / 'home-only')
        self.assertTrue(any('Library/Caches' in p for p in package_app.reference_problems(self.fake.app, self.marks)))

    def test_neutralising_the_prefixes_removes_them_with_the_same_length_and_the_program_still_runs(self):
        program = self.leaky_program('leaky')
        before = program.stat().st_size
        self.assertTrue(package_app.neutralise_file(program, [self.TREE, self.HOME]))
        self.assertEqual(program.stat().st_size, before)
        package_app.adhoc_sign(program)                          # the file changed: signed again before it runs
        self.assertEqual(run(program).returncode, 0)
        data = program.read_bytes()
        self.assertNotIn(b'/Users/someone', data)
        self.assertIn(b'/libs/ui/x.cpp', data)                   # the rest of the string is untouched
        # what is left is harmless by the anchored rules: a source path, the two known constants; the home path is gone
        self.assertEqual(package_app.reference_problems(self.fake.app, self.marks), [])
        self.assertFalse(package_app.neutralise_file(program, [self.TREE, self.HOME]), 'nothing left to change the second time')

    def test_neutralise_bytes_keeps_the_length_and_handles_overlapping_prefixes(self):
        data = b'\x00' + b'/Users/someone/forks/krita-master/_build' + b'\x00' + b'/Users/someone/Library' + b'\x00unrelated/Users\x00'
        out = package_app.neutralise_bytes(data, ['/Users/someone', '/Users/someone/forks/krita-master', '/'])
        self.assertEqual(len(out), len(data))
        self.assertNotIn(b'someone', out)
        as_paths = package_app.neutralise_bytes(data, [pathlib.Path('/Users/someone/forks/krita-master'), pathlib.Path('/Users/someone')])   # what the packager passes
        self.assertNotIn(b'someone', as_paths)
        self.assertTrue(out.endswith(b'unrelated/Users\x00'))
        self.assertIn(b'/_build', out)

    def test_the_anchored_rules(self):
        marks = package_app.reference_marks([self.TREE]) + (self.HOME,)
        harmless = package_app.harmless_reference
        concrete = tuple(m for m in marks if m not in ('/_install', '/_build'))
        self.assertTrue(harmless('/build/////////libs/ui/x.cpp', concrete))
        self.assertTrue(harmless('/build/////////_install/lib/libpython3.13.dylib', concrete))
        self.assertTrue(harmless('/build/////////_build', concrete))
        self.assertFalse(harmless(self.TREE + '/libs/ui/x.cpp', concrete))                  # the artist's prefix is never harmless
        self.assertFalse(harmless(self.TREE + '/_install/lib/libpython3.13.dylib', concrete))
        self.assertFalse(harmless('/build////x.cpp and then ' + self.HOME + '/secret', concrete))   # not a bare path
        self.assertFalse(harmless('see /build////_install/lib/libpython3.13.dylib now', concrete))   # constants are matched whole
        # upstream's CI path is theirs, but only that token is excused, not the whole line
        gitlab = '/Users/gitlab/workspace/builds/x/ext_openssl/_install/ssl'
        self.assertTrue(harmless('OPENSSLDIR: "%s"' % gitlab, concrete))
        self.assertFalse(harmless('OPENSSLDIR: "%s" copied from %s/x' % (gitlab, self.HOME), concrete))

    def test_other_peoples_build_paths_are_not_ours(self):
        # A name that is nobody's home folder: GitHub's macOS runner is the account "runner", so /Users/runner would be OURS there.
        compile_c(self.fake.build, 'theirs', 'const char *a = "/Users/some-other-builder/work/numpy/.openblas"; int main(void) { return a == 0; }\n')
        shutil.copy2(self.fake.build / 'theirs', self.fake.macos / 'theirs')
        self.assertEqual(package_app.reference_problems(self.fake.app, self.marks), [])

    def test_a_symlink_out_of_the_bundle_or_to_nothing_is_a_problem(self):
        self.assertEqual(package_app.symlink_problems(self.fake.app), [])
        os.symlink('../../../elsewhere', self.fake.contents / 'out-link')
        os.symlink('Frameworks/libfoo.dylib', self.fake.contents / 'good-link')
        os.symlink('Frameworks/missing', self.fake.contents / 'dangling')
        problems = ' | '.join(package_app.symlink_problems(self.fake.app))
        self.assertIn('out-link', problems)
        self.assertIn('dangling', problems)
        self.assertNotIn('good-link', problems)


class SigningOrderTests(unittest.TestCase):
    TOP = '/x/Toska.app'

    def files(self):
        top = self.TOP + '/Contents/'
        return [top + 'MacOS/krita-app', top + 'PlugIns/a.so', top + 'Frameworks/QtCore.framework/Versions/A/QtCore',
                top + 'Frameworks/Python.framework/Versions/3.13/Python', top + 'Frameworks/Python.framework/Versions/3.13/lib/x.so',
                top + 'Library/Helper.app/Contents/MacOS/Helper', top + 'Library/Helper.app/Contents/Frameworks/Inner.framework/Versions/A/Inner',
                top + 'PlugIns/Share.xpc/Contents/MacOS/Share', top + 'PlugIns/Thumb.plugin/Contents/MacOS/Thumb', top + 'PlugIns/Thumb.plugin/Contents/Resources/b.dylib']

    def test_files_of_one_nested_bundle_of_any_type_are_signed_one_after_another(self):
        groups = package_app.signing_groups(self.files(), self.TOP)
        by_owner = {os.path.basename(owner): sorted(os.path.basename(f) for f in members) for owner, members in groups.items()}
        self.assertEqual(by_owner['Python.framework'], ['Python', 'x.so'])
        self.assertEqual(by_owner['Helper.app'], ['Helper', 'Inner'])               # a framework inside an app: the app is the owner
        self.assertEqual(by_owner['Thumb.plugin'], ['Thumb', 'b.dylib'])
        self.assertEqual(by_owner['Share.xpc'], ['Share'])
        self.assertEqual(by_owner['QtCore.framework'], ['QtCore'])
        self.assertEqual(by_owner['a.so'], ['a.so'])                                # loose files are their own group (parallel)
        self.assertNotIn('Toska.app', by_owner)                               # the top bundle is not a nested one

    def test_nested_bundles_are_sealed_innermost_first(self):
        order = [os.path.basename(d) for d in package_app.nested_bundles(self.files(), self.TOP)]
        self.assertLess(order.index('Inner.framework'), order.index('Helper.app'))
        self.assertEqual(sorted(order), sorted(['QtCore.framework', 'Python.framework', 'Inner.framework', 'Helper.app', 'Share.xpc', 'Thumb.plugin']))


class HeadlessHelperTests(unittest.TestCase):
    """The bundled Python ignores the caller's PYTHONPATH (hermetic), so kritarunner finds the helper scripts in the user's
    pykrita folder, which is inside the TEMPORARY home."""

    def test_the_script_is_staged_in_the_user_pykrita_folder_of_the_temporary_home(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            home = pathlib.Path(root) / 'home'
            path = package_app.stage_helper_script(home, 'smoke_bundle', 'def __main__(a): pass\n', 'KritaAgent')
            self.assertEqual(path, home / 'Library/Application Support/KritaAgent/kritarunner/krita/pykrita/smoke_bundle.py')
            self.assertEqual(path.read_text(), 'def __main__(a): pass\n')
            self.assertTrue(package_app.inside(path, home))
            other = package_app.stage_helper_script(home, 'other', 'x', 'Other Folder')
            self.assertIn('Other Folder', str(other))                                  # the build's settings folder names it

    def test_the_staged_folder_is_what_the_launchers_python_would_list_first_for_this_app(self):
        # KisApplication names the kritarunner process "kritarunner" under the settings folder (see the real sys.path of a smoke run)
        folder = package_app.helper_folder('/h', 'KritaAgent')
        self.assertEqual(str(folder), '/h/Library/Application Support/KritaAgent/kritarunner/krita/pykrita')

    def test_sys_path_entries_outside_the_bundle_and_home_and_a_leaked_pythonpath_are_problems(self):
        copy, home, poison = '/t/Toska.app', '/t/home', '/t/poison'
        good = [copy + '/Contents/Resources/krita-python-libs', copy + '/Contents/Frameworks/Python.framework/Versions/3.13/lib/python3.13',
                home + '/Library/Application Support/KritaAgent/kritarunner/krita/pykrita', '']
        self.assertEqual(package_app.sys_path_problems(good, copy, home, poison), [])
        bad = package_app.sys_path_problems(good + ['/opt/homebrew/lib/python3.13', poison], copy, home, poison)
        self.assertEqual(len(bad), 3, bad)                                              # two outside entries, and the leak is named
        self.assertTrue(any('PYTHONPATH' in p and 'ignore' in p for p in bad))
        # a poisoned entry that happens to sit inside the temporary home is still a leak
        self.assertTrue(any('PYTHONPATH' in p for p in package_app.sys_path_problems(good + [home + '/poison'], copy, home, home + '/poison')))


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class SigningReportTests(unittest.TestCase):
    def test_a_missing_identity_prints_one_line_and_leaves_the_bundle_as_it_was(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            fake = FakeBundle(root)
            fake.sign()
            lines = []
            status = package_app.sign_and_report(fake.app, 'Krita Agent Test Identity That Does Not Exist', out=lines.append)
            self.assertEqual(status, 1)
            self.assertEqual(len(lines), 1)
            self.assertIn('NOT SIGNED', lines[0])
            self.assertIn('left as it was', lines[0])
            self.assertTrue(package_app.verify_signature(fake.app)[0])                    # still the ad-hoc seal

    def test_the_sandbox_profile_denies_reads_of_the_trees(self):
        profile = package_app.sandbox_profile(['/tmp/some tree'])
        self.assertIn('(deny file-read* file-write* (subpath "/tmp/some tree"))', profile)
        self.assertIn('(allow default)', profile)


class AppIconTests(unittest.TestCase):
    """The app's icon (Info.plist CFBundleIconFile 'krita' -> Resources/krita.icns) is Toska's emblem, from
    creative-agent/docs/branding/Toska.icns; the document icons (.kra, .krz) stay Krita's: they are Krita's file formats."""

    class Stub(package_app.Packager):
        def __init__(self, resources):
            self.resources, self.log = pathlib.Path(resources), (lambda *_: None)

    def test_the_app_icon_is_toskas_and_the_document_icons_stay(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            resources = pathlib.Path(root) / 'Resources'
            resources.mkdir()
            for name in ('krita.icns', 'krita-kra.icns', 'krita-krz.icns'):
                (resources / name).write_bytes(b'icns-from-the-build-' + name.encode())
            self.Stub(resources).brand_icon()
            branding = package_app.ROOT / 'creative-agent' / 'docs' / 'branding' / 'Toska.icns'
            self.assertEqual((resources / 'krita.icns').read_bytes(), branding.read_bytes())
            self.assertEqual((resources / 'krita-kra.icns').read_bytes(), b'icns-from-the-build-krita-kra.icns')
            self.assertEqual((resources / 'krita-krz.icns').read_bytes(), b'icns-from-the-build-krita-krz.icns')

    def test_a_missing_branding_icon_refuses_instead_of_shipping_krita_s(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            resources = pathlib.Path(root) / 'Resources'
            resources.mkdir()
            (resources / 'krita.icns').write_bytes(b'x')
            stub = self.Stub(resources)
            with self.assertRaises(package_app.Refused):
                stub.brand_icon(source=pathlib.Path(root) / 'nope.icns')


class CompanionInTheAppTests(unittest.TestCase):
    """Packager.copy_release: the companion of a build-release.py release goes into Resources/creative-agent, checked."""

    class Stub(package_app.Packager):
        def __init__(self, release, resources):
            self.release, self.resources, self.log, self.trees, self.release_info = pathlib.Path(release), pathlib.Path(resources), (lambda *_: None), [], None
            self.arch, self.options = 'arm64', {}
            plugin = self.resources / 'krita' / 'pykrita' / 'kritamcp'                    # the app's plugin, copied before the release
            plugin.mkdir(parents=True, exist_ok=True)
            (plugin / '__init__.py').write_text('')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.bundled, self.manifest = make_release(self.root / 'src', extra_files=onnx_files(('darwin/arm64',)))
        self.release = self.bundled                                                       # the same layout: companion/ + manifest
        (self.release / 'plugin').mkdir()                                                 # the plugin half of a release is not copied
        (self.release / 'plugin' / 'x.py').write_text('x')

    def test_the_companion_and_manifest_are_copied_checked_and_the_plugin_half_is_left_out(self):
        stub = self.Stub(self.release, self.root / 'Resources')
        stub.resources.mkdir(exist_ok=True)
        stub.copy_release()
        target = stub.resources / 'creative-agent-bundle'
        self.assertTrue((target / 'companion' / 'src' / 'main.mjs').is_file())
        self.assertTrue((target / 'release-manifest.json').is_file())
        self.assertFalse((target / 'plugin').exists())
        self.assertEqual(stub.release_info['build_id'], self.manifest['build_id'])
        self.assertEqual(stub.release_info['node'], '22.23.2')
        self.assertIn('built_at', json.loads((target / 'bundle-info.json').read_text()))

    def test_a_release_with_other_platforms_onnx_runtime_is_refused(self):
        bundled, _ = make_release(self.root / 'other', extra_files=onnx_files(('darwin/arm64', 'linux/x64')))
        stub = self.Stub(bundled, self.root / 'Resources-other')
        with self.assertRaisesRegex(package_app.Refused, 'linux/x64'):
            stub.copy_release()

    def test_the_plugin_in_the_app_carries_the_companions_build_id(self):
        # The companion refuses a bridge whose build_id differs (runtime.mjs acceptBridgeHealth). The plugin reads its own
        # build-info.json next to its code: without it the packaged app says 'development-unverified' and the panel shows
        # "Reload the matching Creative Agent build" on every first run.
        stub = self.Stub(self.release, self.root / 'Resources')
        plugin = stub.resources / 'krita' / 'pykrita' / 'kritamcp'
        stub.copy_release()
        info = json.loads((plugin / 'build-info.json').read_text())
        self.assertEqual(info['build_id'], self.manifest['build_id'])
        self.assertEqual(info['protocol_version'], self.manifest.get('protocol_version', 2))
        for heavy in ('files', 'node_runtime', 'dependencies'):
            self.assertNotIn(heavy, info)

    def test_with_a_developer_id_a_release_whose_native_files_are_not_signed_with_it_is_refused(self):
        native = 'companion/node_modules/onnxruntime-node/bin/napi-v6/darwin/arm64/libonnxruntime.1.dylib'
        bundled, _ = make_release(self.root / 'signed', extra_files={native: FAKE_MACHO.decode('latin-1')})
        (bundled / native).write_bytes(FAKE_MACHO)                                        # make_release writes text: the real bytes
        manifest = json.loads((bundled / 'release-manifest.json').read_text())
        manifest['files'][native] = hashlib.sha256(FAKE_MACHO).hexdigest()
        (bundled / 'release-manifest.json').write_text(json.dumps(manifest))
        stub = self.Stub(bundled, self.root / 'Resources-signed')
        stub.options = {'sign_identity': DEVELOPER_ID}
        unsigned = FakeTools([(('codesign', '-dvv'), 1, '', 'code object is not signed at all')])
        with mock.patch.object(package_app, 'run_tool', side_effect=unsigned):
            with self.assertRaisesRegex(package_app.Refused, re.escape('not signed with %s' % DEVELOPER_ID)):
                stub.copy_release()
        self.assertTrue(unsigned.calls[0][-1].endswith('libonnxruntime.1.dylib'))

    def test_a_release_that_does_not_match_its_manifest_or_is_no_release_is_refused(self):
        (self.release / 'companion' / 'src' / 'main.mjs').write_text('tampered')
        stub = self.Stub(self.release, self.root / 'Resources')
        stub.resources.mkdir(exist_ok=True)
        with self.assertRaises(package_app.Refused):
            stub.copy_release()
        empty = self.root / 'empty'
        empty.mkdir()
        with self.assertRaises(package_app.Refused):
            self.Stub(empty, self.root / 'Resources2').copy_release()


@unittest.skipUnless(HAVE_CC, 'needs macOS and a C compiler')
class ArchitectureTests(unittest.TestCase):
    def build(self, root, *archs):
        main = pathlib.Path(root) / 'bin' / 'krita.app' / 'Contents' / 'MacOS'
        main.mkdir(parents=True)
        flags = [f for arch in archs for f in ('-arch', arch)]
        compile_c(main, 'krita', 'int main(void) { return 0; }\n', *flags)
        return pathlib.Path(root)

    def test_the_architecture_is_the_binarys_and_only_arm64_is_accepted(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            self.assertEqual(package_app.install_architecture(self.build(pathlib.Path(root) / 'a', 'arm64')), 'arm64')
            with self.assertRaises(package_app.Refused) as raised:
                package_app.install_architecture(self.build(pathlib.Path(root) / 'b', 'x86_64'))
            self.assertIn('arm64-only', str(raised.exception))
            with self.assertRaises(package_app.Refused):
                package_app.install_architecture(self.build(pathlib.Path(root) / 'c', 'arm64', 'x86_64'))     # universal: not one build

    def test_a_universal_file_is_cut_to_the_given_architecture_not_the_machines(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            universal = compile_c(root, 'u', 'int main(void) { return 0; }\n', '-arch', 'arm64', '-arch', 'x86_64')
            self.assertTrue(package_app.thin_to(universal, 'x86_64'))
            self.assertEqual(package_app.macho_archs(universal), ['x86_64'])
            with self.assertRaises(RuntimeError):
                other = compile_c(root, 'v', 'int main(void) { return 0; }\n', '-arch', 'arm64', '-arch', 'x86_64')
                package_app.thin_to(other, 'ppc')


class PackageScriptTests(unittest.TestCase):
    @unittest.skipUnless(MACOS, 'macOS only')
    def test_refuses_applications_and_a_missing_install_without_creating_anything(self):
        script = str(AGENT / 'package-app.sh')
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            fake_applications = pathlib.Path(root) / 'Applications'
            env = {'PATH': '/usr/bin:/bin', 'HOME': root, 'KRITA_AGENT_APPLICATIONS_DIR': str(fake_applications)}
            install = pathlib.Path(root) / 'src' / '_install'
            (install / 'bin' / 'krita.app').mkdir(parents=True)
            refused = run('/bin/zsh', script, str(install), '--out', str(fake_applications / 'zz-test'), env=env)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn('Applications folder', refused.stderr)
            self.assertFalse(fake_applications.exists())                                   # nothing was created
            missing = run('/bin/zsh', script, root + '/no-install', '--out', root + '/out', env=env)
            self.assertEqual(missing.returncode, 2)
            self.assertIn('build first', missing.stderr)
            self.assertFalse(pathlib.Path(root, 'out').exists())

    @unittest.skipUnless(MACOS, 'macOS only')
    def test_help_prints_the_usage(self):
        result = run('/bin/zsh', str(AGENT / 'package-app.sh'), '-h', env={'PATH': '/usr/bin:/bin', 'HOME': tempfile.gettempdir()})
        self.assertEqual(result.returncode, 0)
        self.assertIn('agent/package-app.sh [INSTALL_DIR]', result.stdout)
        self.assertNotIn('set -euo', result.stdout)

# --------------------------------------------------------------------------- Developer ID signing, notarization, the .dmg
# Every tool is faked (no codesign, no network, nothing uploaded to Apple): these tests check the decisions and the commands.

DEVELOPER_ID = 'Developer ID Application: Test Signer (TEAM123456)'
FAKE_MACHO = b'\xcf\xfa\xed\xfe' + b'\0' * 60


class FakeTools:
    """A runner for package_app's tool calls: records each command and answers from `answers`, a list of (prefix, returncode,
    stdout, stderr) matched by the command's first words (the first match wins; unmatched commands succeed silently)."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, command):
        command = [str(part) for part in command]
        self.calls.append(command)
        for prefix, code, out, err in self.answers:
            if command[:len(prefix)] == list(prefix):
                return subprocess.CompletedProcess(command, code, out, err)
        return subprocess.CompletedProcess(command, 0, '', '')

    def named(self, *prefix):
        return [call for call in self.calls if call[:len(prefix)] == list(prefix)]


def fake_app(root, companion=True):
    """A bundle of fake Mach-O files (magic only): an executable, a framework's library, and the companion's native file."""
    app = pathlib.Path(root) / 'Toska.app'
    files = ['Contents/MacOS/krita', 'Contents/MacOS/krita-app', 'Contents/Frameworks/QtCore.framework/Versions/A/QtCore',
             'Contents/Frameworks/libfoo.dylib']
    if companion:
        files.append(package_app.COMPANION_FOLDER + '/companion/node_modules/onnxruntime-node/bin/napi-v6/darwin/arm64/libonnxruntime.1.dylib')
    for name in files:
        (app / name).parent.mkdir(parents=True, exist_ok=True)
        (app / name).write_bytes(FAKE_MACHO)
    with open(app / 'Contents' / 'Info.plist', 'wb') as stream:
        plistlib.dump({'CFBundleIdentifier': 'local.kritaagent', 'CFBundleShortVersionString': '6.1.0'}, stream)
    return app


class DeveloperIdSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.app = fake_app(self.temp.name)

    def signing_commands(self, identity):
        calls = []
        with mock.patch.object(package_app, 'run', side_effect=lambda command, **_: calls.append([str(c) for c in command]) or ''), \
             mock.patch.object(package_app, 'identity_available', return_value=True):
            package_app.sign_bundle(self.app, identity, log=lambda *_: None)
        return calls

    def test_a_developer_id_signs_files_nested_bundles_and_the_app_with_a_secure_timestamp(self):
        calls = self.signing_commands(DEVELOPER_ID)
        targets = [call[-1] for call in calls]
        self.assertIn(str(self.app / 'Contents/Frameworks/QtCore.framework'), targets)
        self.assertEqual(targets[-1], str(self.app))
        for call in calls:
            self.assertEqual(call[:4], ['codesign', '--force', '--sign', DEVELOPER_ID])
            self.assertIn('--timestamp', call, call)
            self.assertNotIn('--timestamp=none', call)
            self.assertEqual(call[call.index('--options') + 1], 'runtime')
        # The companion's files are the release's (signed by build-release.py before its manifest): never re-signed here.
        self.assertFalse(any('creative-agent-bundle' in target for target in targets))

    def test_ad_hoc_signing_stays_without_a_timestamp(self):
        calls = self.signing_commands(None)
        for call in calls:
            self.assertEqual(call[:4], ['codesign', '--force', '--sign', '-'])
            self.assertIn('--timestamp=none', call)
            self.assertNotIn('--timestamp', call)
            self.assertNotIn('runtime', call)

    def test_the_release_is_built_with_the_identity_the_app_is_signed_with(self):
        self.assertEqual(package_app.release_environment(DEVELOPER_ID, {'HOME': '/h'})['KRITA_AGENT_SIGN_IDENTITY'], DEVELOPER_ID)
        self.assertNotIn('KRITA_AGENT_SIGN_IDENTITY', package_app.release_environment(None, {'HOME': '/h'}))
        self.assertEqual(package_app.release_environment(None, {'HOME': '/h'})['HOME'], '/h')

    def test_companion_files_not_signed_by_the_identity_are_problems(self):
        native = str(self.app / package_app.COMPANION_FOLDER / 'companion/node_modules/onnxruntime-node/bin/napi-v6/darwin/arm64/libonnxruntime.1.dylib')
        good = ('Executable=%s\nAuthority=%s\nAuthority=Developer ID Certification Authority\nTimestamp=26 Oct 2026\n'
                'CodeDirectory v=20500 size=1 flags=0x10000(runtime) hashes=1\n' % (native, DEVELOPER_ID))
        tools = FakeTools([(('codesign', '-dvv'), 0, '', good)])
        self.assertEqual(package_app.companion_signing_problems(self.app, DEVELOPER_ID, tools), [])
        self.assertEqual([call[-1] for call in tools.calls], [native])                     # only the companion's Mach-O files
        unsigned = FakeTools([(('codesign', '-dvv'), 1, '', 'code object is not signed at all')])
        self.assertIn('not signed with %s' % DEVELOPER_ID, ' '.join(package_app.companion_signing_problems(self.app, DEVELOPER_ID, unsigned)))
        no_time = FakeTools([(('codesign', '-dvv'), 0, '', good.replace('Timestamp=26 Oct 2026', 'Signed Time=26 Oct 2026'))])
        self.assertIn('secure timestamp', ' '.join(package_app.companion_signing_problems(self.app, DEVELOPER_ID, no_time)))
        no_runtime = FakeTools([(('codesign', '-dvv'), 0, '', good.replace('0x10000(runtime)', '0x2(adhoc)'))])
        self.assertIn('hardened runtime', ' '.join(package_app.companion_signing_problems(self.app, DEVELOPER_ID, no_runtime)))


class NotarizationTests(unittest.TestCase):
    PROFILE = 'test-profile'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.app = fake_app(self.temp.name)
        self.lines = []

    def notarize(self, tools, path=None):
        return package_app.notarize(path or self.app, self.PROFILE, runner=tools, log=self.lines.append)

    def accepted(self, assessment='%s: accepted\nsource=Notarized Developer ID\n'):
        return FakeTools([(('xcrun', 'notarytool', 'submit'), 0, json.dumps({'id': 'abc-123', 'status': 'Accepted', 'message': 'ok'}), ''),
                          (('spctl',), 0, '', assessment % self.app)])

    def test_an_accepted_app_is_zipped_submitted_stapled_and_assessed(self):
        tools = self.accepted()
        result = self.notarize(tools)
        self.assertEqual(result['status'], 'Accepted')
        ditto = tools.named('ditto')[0]
        self.assertEqual(ditto[:4], ['ditto', '-c', '-k', '--keepParent'])
        self.assertEqual(ditto[4], str(self.app))
        upload = ditto[5]
        self.assertTrue(upload.endswith('.zip'))
        submit = tools.named('xcrun', 'notarytool', 'submit')[0]
        self.assertEqual(submit[3], upload)
        self.assertEqual(submit[submit.index('--keychain-profile') + 1], self.PROFILE)
        self.assertIn('--wait', submit)
        self.assertEqual(tools.named('xcrun', 'stapler', 'staple')[0][-1], str(self.app))
        spctl = tools.named('spctl')[0]
        self.assertEqual(spctl[:4], ['spctl', '--assess', '--type', 'execute'])
        self.assertEqual(spctl[-1], str(self.app))
        order = [call[0] if call[0] != 'xcrun' else call[1] + ' ' + call[2] for call in tools.calls]
        self.assertEqual(order, ['ditto', 'notarytool submit', 'stapler staple', 'spctl'])
        self.assertFalse(pathlib.Path(upload).exists(), 'the zip is removed afterwards')
        self.assertIn('accepted', ' '.join(self.lines))

    def test_an_invalid_submission_prints_each_issue_and_fails_without_stapling(self):
        log = {'status': 'Invalid', 'issues': [
            {'severity': 'error', 'path': 'Toska.zip/Toska.app/Contents/Frameworks/libfoo.dylib', 'message': 'The binary is not signed with a valid Developer ID certificate.'},
            {'severity': 'error', 'path': 'Toska.zip/Toska.app/Contents/MacOS/krita', 'message': 'The signature does not include a secure timestamp.'}]}
        tools = FakeTools([(('xcrun', 'notarytool', 'submit'), 1, json.dumps({'id': 'abc-123', 'status': 'Invalid'}), ''),
                           (('xcrun', 'notarytool', 'log'), 0, json.dumps(log), '')])
        with self.assertRaises(package_app.NotarizationFailed) as raised:
            self.notarize(tools)
        self.assertIn('Invalid', str(raised.exception))
        fetched = tools.named('xcrun', 'notarytool', 'log')[0]
        self.assertEqual(fetched[3], 'abc-123')
        self.assertEqual(fetched[fetched.index('--keychain-profile') + 1], self.PROFILE)
        text = '\n'.join(self.lines)
        self.assertIn('Contents/Frameworks/libfoo.dylib: The binary is not signed with a valid Developer ID certificate.', text)
        self.assertIn('Contents/MacOS/krita: The signature does not include a secure timestamp.', text)
        self.assertEqual(tools.named('xcrun', 'stapler'), [])
        self.assertEqual(tools.named('spctl'), [])

    def test_a_submission_that_never_got_an_answer_fails_with_what_notarytool_said(self):
        tools = FakeTools([(('xcrun', 'notarytool', 'submit'), 69, '', 'Error: No Keychain password item found for profile')])
        with self.assertRaises(package_app.NotarizationFailed) as raised:
            self.notarize(tools)
        self.assertIn('No Keychain password item found', str(raised.exception))
        self.assertEqual(tools.named('xcrun', 'notarytool', 'log'), [])
        self.assertEqual(tools.named('xcrun', 'stapler'), [])

    def test_a_failed_staple_or_a_rejected_assessment_fails(self):
        staple = self.accepted()
        staple.answers.insert(0, (('xcrun', 'stapler'), 65, '', 'Could not validate ticket'))
        with self.assertRaisesRegex(package_app.NotarizationFailed, 'stapl'):
            self.notarize(staple)
        rejected = FakeTools([(('xcrun', 'notarytool', 'submit'), 0, json.dumps({'id': 'x', 'status': 'Accepted'}), ''),
                              (('spctl',), 3, '', '%s: rejected\nsource=Unnotarized Developer ID\n' % self.app)])
        with self.assertRaisesRegex(package_app.NotarizationFailed, 'rejected'):
            self.notarize(rejected)

    def test_a_dmg_is_submitted_as_it_is_and_assessed_as_a_disk_image(self):
        dmg = pathlib.Path(self.temp.name) / 'Toska-6.1.0.dmg'
        dmg.write_bytes(b'dmg')
        tools = FakeTools([(('xcrun', 'notarytool', 'submit'), 0, json.dumps({'id': 'd', 'status': 'Accepted'}), ''),
                           (('spctl',), 0, '', '%s: accepted\nsource=Notarized Developer ID\n' % dmg)])
        self.notarize(tools, dmg)
        self.assertEqual(tools.named('ditto'), [])
        self.assertEqual(tools.named('xcrun', 'notarytool', 'submit')[0][3], str(dmg))
        spctl = tools.named('spctl')[0]
        self.assertEqual(spctl[:6], ['spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature'])

    def test_notarizing_needs_a_developer_id_signature(self):
        tools = FakeTools([(('codesign', '-dvv'), 0, '', 'Signature=adhoc\n')])
        with self.assertRaisesRegex(package_app.NotarizationFailed, 'Developer ID'):
            package_app.require_developer_id(self.app, tools)
        signed = FakeTools([(('codesign', '-dvv'), 0, '', 'Authority=%s\nTimestamp=26 Oct 2026\n' % DEVELOPER_ID)])
        self.assertEqual(package_app.require_developer_id(self.app, signed), DEVELOPER_ID)


class DiskImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.app = fake_app(self.temp.name)
        self.out = pathlib.Path(self.temp.name) / 'dist'
        self.staged = {}

    def tools(self, *answers):
        tools = FakeTools(answers)
        original = tools.__call__

        def look(command):
            command = [str(part) for part in command]
            if command[0] == 'hdiutil':                     # what the image would hold, seen while the staging folder exists
                folder = pathlib.Path(command[command.index('-srcfolder') + 1])
                self.staged = {child.name: (os.readlink(child) if child.is_symlink() else 'folder') for child in folder.iterdir()}
            return original(command)
        return look, tools

    def test_the_image_holds_the_app_and_an_applications_link_and_is_signed(self):
        runner, tools = self.tools()
        dmg = package_app.make_dmg(self.app, self.out, DEVELOPER_ID, runner=runner, log=lambda *_: None)
        self.assertEqual(dmg, self.out / 'Toska-6.1.0.dmg')
        self.assertEqual(self.staged, {'Toska.app': 'folder', 'Applications': '/Applications'})
        copy = tools.named('ditto')[0]
        self.assertEqual(copy[1], str(self.app))
        create = tools.named('hdiutil', 'create')[0]
        self.assertEqual(create[create.index('-format') + 1], 'UDZO')
        self.assertEqual(create[create.index('-volname') + 1], 'Toska')
        self.assertEqual(create[-1], str(dmg))
        sign = tools.named('codesign', '--force', '--sign')[0]
        self.assertEqual(sign, ['codesign', '--force', '--sign', DEVELOPER_ID, '--timestamp', str(dmg)])
        self.assertEqual(tools.named('xcrun'), [])                                         # not notarized unless asked
        self.assertFalse(pathlib.Path(create[create.index('-srcfolder') + 1]).exists(), 'the staging folder is removed')

    def test_with_notarize_the_signed_image_is_notarized_and_stapled(self):
        runner, tools = self.tools((('xcrun', 'notarytool', 'submit'), 0, json.dumps({'id': 'd', 'status': 'Accepted'}), ''),
                                   (('spctl',), 0, '', 'x.dmg: accepted\nsource=Notarized Developer ID\n'))
        dmg = package_app.make_dmg(self.app, self.out, DEVELOPER_ID, profile='test-profile', runner=runner, log=lambda *_: None)
        order = [call[0] if call[0] not in ('xcrun', 'hdiutil') else ' '.join(call[:2] if call[0] == 'hdiutil' else call[1:3]) for call in tools.calls]
        self.assertEqual(order, ['ditto', 'hdiutil create', 'codesign', 'notarytool submit', 'stapler staple', 'spctl'])
        self.assertEqual(tools.named('xcrun', 'notarytool', 'submit')[0][3], str(dmg))
        self.assertEqual(tools.named('xcrun', 'stapler', 'staple')[0][-1], str(dmg))

    def test_notarizing_without_an_identity_is_refused_before_anything_is_made(self):
        runner, tools = self.tools()
        with self.assertRaisesRegex(package_app.NotarizationFailed, 'identity'):
            package_app.make_dmg(self.app, self.out, None, profile='test-profile', runner=runner, log=lambda *_: None)
        self.assertEqual(tools.calls, [])
        self.assertFalse(self.out.exists())

    def test_without_an_identity_the_image_is_left_unsigned(self):
        runner, tools = self.tools()
        package_app.make_dmg(self.app, self.out, None, runner=runner, log=lambda *_: None)
        self.assertEqual(tools.named('codesign'), [])

    def test_the_image_is_never_written_inside_the_app(self):
        runner, tools = self.tools()
        with self.assertRaises(package_app.Refused):
            package_app.make_dmg(self.app, self.app / 'Contents', None, runner=runner, log=lambda *_: None)
        self.assertEqual(tools.calls, [])


class SigningReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.app = fake_app(self.temp.name, companion=False)

    def test_an_ad_hoc_bundle_reports_ad_hoc_and_is_not_verified_deeply(self):
        tools = FakeTools([(('codesign', '-dvv'), 0, '', 'Identifier=local.kritaagent\nSignature=adhoc\n')])
        lines, problems = package_app.signing_report(self.app, tools)
        self.assertEqual(problems, [])
        self.assertIn('ad hoc', ' '.join(lines))
        self.assertEqual(tools.named('codesign', '--verify'), [])

    def test_a_developer_id_bundle_is_verified_deeply_and_names_its_authority(self):
        details = 'Authority=%s\nAuthority=Developer ID Certification Authority\nAuthority=Apple Root CA\nTimestamp=26 Oct 2026\n' % DEVELOPER_ID
        tools = FakeTools([(('codesign', '-dvv'), 0, '', details)])
        lines, problems = package_app.signing_report(self.app, tools)
        self.assertEqual(problems, [])
        self.assertIn('signed by %s' % DEVELOPER_ID, ' '.join(lines))
        verify = tools.named('codesign', '--verify')[0]
        self.assertEqual(verify[:4], ['codesign', '--verify', '--deep', '--strict'])
        self.assertEqual(verify[-1], str(self.app))
        broken = FakeTools([(('codesign', '-dvv'), 0, '', details), (('codesign', '--verify'), 1, '', 'a sealed resource is missing or invalid')])
        lines, problems = package_app.signing_report(self.app, broken)
        self.assertEqual(len(problems), 1)
        self.assertIn('a sealed resource is missing or invalid', problems[0])


class ReleaseCommandTests(unittest.TestCase):
    """package_app.py notarize / dmg and package-app.sh --notarize, with the tools faked."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.app = fake_app(self.temp.name)

    def main(self, *argv, tools, identity=None):
        environment = {'KRITA_AGENT_SIGN_IDENTITY': identity} if identity else {}
        with mock.patch.object(package_app, 'run_tool', side_effect=tools), mock.patch.dict(os.environ, environment, clear=False), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if not identity:
                os.environ.pop('KRITA_AGENT_SIGN_IDENTITY', None)
            return package_app.main([str(part) for part in argv])

    def test_notarize_refuses_an_app_without_a_developer_id_signature(self):
        tools = FakeTools([(('codesign', '-dvv'), 0, '', 'Signature=adhoc\n')])
        self.assertEqual(self.main('notarize', self.app, '--profile', 'p', tools=tools), 1)
        self.assertEqual(tools.named('xcrun'), [])
        self.assertEqual(tools.named('ditto'), [])

    def test_notarize_submits_with_the_named_profile(self):
        tools = FakeTools([(('codesign', '-dvv'), 0, '', 'Authority=%s\nTimestamp=x\n' % DEVELOPER_ID),
                           (('xcrun', 'notarytool', 'submit'), 0, json.dumps({'id': 'i', 'status': 'Accepted'}), ''),
                           (('spctl',), 0, '', 'Toska.app: accepted\nsource=Notarized Developer ID\n')])
        self.assertEqual(self.main('notarize', self.app, '--profile', 'my-profile', tools=tools), 0)
        submit = tools.named('xcrun', 'notarytool', 'submit')[0]
        self.assertEqual(submit[submit.index('--keychain-profile') + 1], 'my-profile')

    def test_dmg_with_notarize_needs_the_identity(self):
        tools = FakeTools()
        self.assertEqual(self.main('dmg', self.app, '--out', pathlib.Path(self.temp.name) / 'dist', '--notarize', tools=tools), 1)
        self.assertEqual(tools.calls, [])
        made = FakeTools([(('xcrun', 'notarytool', 'submit'), 0, json.dumps({'id': 'i', 'status': 'Accepted'}), ''),
                          (('spctl',), 0, '', 'x.dmg: accepted\nsource=Notarized Developer ID\n')])
        self.assertEqual(self.main('dmg', self.app, '--out', pathlib.Path(self.temp.name) / 'dist', '--notarize', '--profile', 'p',
                                   tools=made, identity=DEVELOPER_ID), 0)
        self.assertEqual(made.named('codesign', '--force', '--sign')[0][3], DEVELOPER_ID)
        self.assertEqual(len(made.named('xcrun', 'stapler', 'staple')), 1)

    @unittest.skipUnless(MACOS, 'macOS only')
    def test_package_app_sh_refuses_notarize_without_an_identity_before_anything_is_made(self):
        with tempfile.TemporaryDirectory(prefix='krita-agent-test-') as root:
            env = {'PATH': '/usr/bin:/bin', 'HOME': root}
            install = pathlib.Path(root) / 'src' / '_install'
            (install / 'bin' / 'krita.app').mkdir(parents=True)
            refused = run('/bin/zsh', AGENT / 'package-app.sh', install, '--out', pathlib.Path(root) / 'out', '--notarize', env=env)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn('KRITA_AGENT_SIGN_IDENTITY', refused.stderr)
            self.assertFalse(pathlib.Path(root, 'out').exists())
            no_sign = run('/bin/zsh', AGENT / 'package-app.sh', install, '--out', pathlib.Path(root) / 'out', '--dmg', '--notarize', '--no-sign',
                          env={**env, 'KRITA_AGENT_SIGN_IDENTITY': DEVELOPER_ID})
            self.assertEqual(no_sign.returncode, 2, no_sign.stderr)
            self.assertFalse(pathlib.Path(root, 'out').exists())


if __name__ == '__main__':
    unittest.main()
