# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""build-release.py: packages the bundle leaves outside (VTracer reads its WebAssembly from its own folder) are copied
beside it into the companion's node_modules, and esbuild is told so. Works in a temporary folder, removed afterwards."""
import importlib.util
import json
import pathlib
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('build_release_externals', pathlib.Path(__file__).resolve().parents[1] / 'scripts/build-release.py')
build_release = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(build_release)


class ExternalPackagesTests(unittest.TestCase):
    def test_vtracer_is_an_external_package_and_a_locked_dependency(self):
        self.assertIn('@visioncortex/vtracer', build_release.EXTERNAL_PACKAGES)
        package = json.loads((pathlib.Path(build_release.ROOT) / 'package.json').read_text())
        self.assertEqual(package['dependencies']['@visioncortex/vtracer'], '1.0.0-alpha.4', 'pinned exactly')

    def test_external_packages_are_copied_whole_and_a_missing_one_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            source = root / 'deps' / '@visioncortex' / 'vtracer'
            (source / 'pkg').mkdir(parents=True)
            (source / 'package.json').write_text('{"name": "@visioncortex/vtracer", "version": "1.0.0-alpha.4"}')
            (source / 'index.js').write_text('module.exports = {}')
            (source / 'pkg' / 'vtracer_wasm_bg.wasm').write_bytes(b'\0asm')
            (source / 'index.js.map').write_text('{}')
            companion = root / 'companion'; companion.mkdir()
            build_release.copy_external_packages(root / 'deps', companion, ('@visioncortex/vtracer',))
            target = companion / 'node_modules' / '@visioncortex' / 'vtracer'
            self.assertTrue((target / 'pkg' / 'vtracer_wasm_bg.wasm').is_file(), 'the WebAssembly beside its loader')
            self.assertTrue((target / 'package.json').is_file())
            self.assertFalse((target / 'index.js.map').exists())
            with self.assertRaisesRegex(ValueError, 'npm ci'):
                build_release.copy_external_packages(root / 'deps', root / 'other', ('@visioncortex/missing',))


if __name__ == '__main__':
    unittest.main()
