# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""build-release.py with a Developer ID: the companion's own Mach-O files (onnxruntime-node's binaries) are signed BEFORE the
manifest is written, so the manifest records the signed bytes and the plugin's first-run check (bundled_release.py) accepts
them. codesign is faked (it rewrites the file the way a signature would); nothing is signed for real. Works in a temporary
folder, removed afterwards."""
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve()
SPEC = importlib.util.spec_from_file_location('build_release_signing', HERE.parents[1] / 'scripts/build-release.py')
build_release = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(build_release)
_spec = importlib.util.spec_from_file_location('bundled_release_for_signing', HERE.parents[2] / 'krita-mcp/krita-plugin/kritamcp/bundled_release.py')
bundled_release = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bundled_release)

MACHO = b'\xcf\xfa\xed\xfe' + b'\0' * 60                    # a thin 64-bit Mach-O header, as far as the magic goes
IDENTITY = 'Developer ID Application: Test Signer (TEAM123456)'
NATIVE = 'companion/node_modules/onnxruntime-node/bin/napi-v6/darwin/arm64/'


class FakeCodesign:
    """Records each codesign call and, for a signing call, appends a 'signature' to the file (the bytes change, as they do)."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        command = [str(part) for part in command]
        self.calls.append(command)
        if command[0] == 'codesign' and '--sign' in command:
            with open(command[-1], 'ab') as stream:
                stream.write(b'SIGNED BY ' + command[command.index('--sign') + 1].encode())
        return subprocess.CompletedProcess(command, 0, '', '')


def stage(root):
    staging = pathlib.Path(root) / 'staging'
    files = {NATIVE + 'onnxruntime_binding.node': MACHO, NATIVE + 'libonnxruntime.1.dylib': MACHO + b'lib',
             'companion/src/main.mjs': b'console.log(1)\n', 'companion/package.json': b'{}\n',
             'plugin/kritamcp/__init__.py': b'x', 'install.py': b'y'}
    for name, data in files.items():
        (staging / name).parent.mkdir(parents=True, exist_ok=True)
        (staging / name).write_bytes(data)
    return staging


def finish(staging, identity, runner):
    """What build() does after the companion is bundled: sign its native files, then write the manifest."""
    build_release.sign_native_files(staging / 'companion', identity, runner)
    return build_release.finish_release(staging, {'version': '9.9.9'}, {'architecture': 'arm64'}, {'version': '22.23.2', 'archives': {}},
                                        {'pkg': '1.0.0'})


class ReleaseSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='krita-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.staging = stage(self.temp.name)

    def test_with_an_identity_the_native_files_are_signed_before_the_manifest_records_their_bytes(self):
        before = (self.staging / NATIVE / 'onnxruntime_binding.node').read_bytes()
        codesign = FakeCodesign()
        manifest = finish(self.staging, IDENTITY, codesign)
        signed = [call for call in codesign.calls if '--sign' in call]
        self.assertEqual(sorted(pathlib.Path(call[-1]).name for call in signed), ['libonnxruntime.1.dylib', 'onnxruntime_binding.node'])
        for call in signed:
            self.assertEqual(call[:4], ['codesign', '--force', '--sign', IDENTITY])
            self.assertIn('--timestamp', call)                         # a secure timestamp: notarization needs it
            self.assertNotIn('--timestamp=none', call)
            self.assertEqual(call[call.index('--options') + 1], 'runtime')
        after = (self.staging / NATIVE / 'onnxruntime_binding.node').read_bytes()
        self.assertNotEqual(before, after)
        self.assertEqual(manifest['files'][NATIVE + 'onnxruntime_binding.node'], hashlib.sha256(after).hexdigest())
        self.assertEqual(json.loads((self.staging / 'release-manifest.json').read_text())['files'], manifest['files'])
        # Not a Mach-O file: never handed to codesign.
        self.assertFalse(any(call[-1].endswith('main.mjs') for call in codesign.calls))

    def test_the_plugins_first_run_check_accepts_the_signed_companion(self):
        finish(self.staging, IDENTITY, FakeCodesign())
        bundled = pathlib.Path(self.temp.name) / 'Resources' / 'creative-agent-bundle'   # where the packaged app keeps it
        bundled.mkdir(parents=True)
        shutil.copytree(self.staging / 'companion', bundled / 'companion')
        shutil.copy2(self.staging / 'release-manifest.json', bundled / 'release-manifest.json')
        manifest = bundled_release.verify_companion(bundled)
        self.assertEqual(len(manifest['build_id']), 64)
        # Signing after the manifest (what the packager must never do) is caught by the same check.
        FakeCodesign()(['codesign', '--force', '--sign', IDENTITY, str(bundled / NATIVE / 'onnxruntime_binding.node')])
        with self.assertRaisesRegex(bundled_release.BundledReleaseError, 'changed'):
            bundled_release.verify_companion(bundled)

    def test_ad_hoc_builds_sign_nothing_and_keep_the_bytes(self):
        before = (self.staging / NATIVE / 'onnxruntime_binding.node').read_bytes()
        codesign = FakeCodesign()
        manifest = finish(self.staging, None, codesign)
        self.assertEqual(codesign.calls, [])
        self.assertEqual(manifest['files'][NATIVE + 'onnxruntime_binding.node'], hashlib.sha256(before).hexdigest())

    def test_a_failed_signature_stops_the_release(self):
        def failing(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, '', 'errSecInternalComponent')
        with self.assertRaisesRegex(ValueError, 'errSecInternalComponent'):
            finish(self.staging, IDENTITY, failing)
        self.assertFalse((self.staging / 'release-manifest.json').exists())

    def test_the_identity_comes_from_the_packagers_variable_unless_given(self):
        self.assertEqual(build_release.signing_identity(None, {'KRITA_AGENT_SIGN_IDENTITY': IDENTITY}), IDENTITY)
        self.assertEqual(build_release.signing_identity('Other', {'KRITA_AGENT_SIGN_IDENTITY': IDENTITY}), 'Other')
        self.assertIsNone(build_release.signing_identity(None, {}))
        self.assertIsNone(build_release.signing_identity(None, {'KRITA_AGENT_SIGN_IDENTITY': ''}))


if __name__ == '__main__':
    unittest.main()
