"""Assemble a self-contained graphical .app from an already verified Mac release.

Swift and Python are builder tools only. The artist runs the compiled application
and bundled Node runtime; no Python, npm, developer tools or shell setup is needed.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

SCRIPTS = Path(__file__).resolve().parent


def checksum(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''): result.update(data)
    return result.hexdigest()


def build(bundle, output, minimum_macos='13.5'):
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    if output.suffix != '.app': raise ValueError('The output must end in .app.')
    if output.exists(): raise ValueError('Choose a new installer output path; existing apps are never overwritten.')
    spec = importlib.util.spec_from_file_location('creative_release_install', SCRIPTS / 'install.py')
    verifier = importlib.util.module_from_spec(spec); spec.loader.exec_module(verifier)
    manifest = verifier.verify_bundle(bundle)
    swift = subprocess.check_output(['/usr/bin/xcrun', '--find', 'swiftc'], text=True).strip()
    sdk = subprocess.check_output(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    architecture = {'arm64': 'arm64', 'x64': 'x86_64'}[manifest['architecture']]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.creative-installer-', dir=output.parent) as temporary:
        stage = Path(temporary) / output.name
        contents = stage / 'Contents'; executable_dir = contents / 'MacOS'; resources = contents / 'Resources'
        executable_dir.mkdir(parents=True); resources.mkdir()
        executable = executable_dir / 'CreativeAgentInstaller'
        module_cache = Path(temporary) / 'swift-module-cache'
        subprocess.run([swift, '-parse-as-library', '-O', '-target', architecture + '-apple-macos' + minimum_macos,
                        '-sdk', sdk, '-module-cache-path', str(module_cache), str(SCRIPTS / 'mac-installer.swift'),
                        '-o', str(executable)], check=True)
        shutil.copytree(bundle, resources / 'release', symlinks=False)
        shutil.copy2(SCRIPTS / 'install-release.mjs', resources / 'install-release.mjs')
        integrity = {'node_sha256': checksum(resources / 'release/runtime/bin/node'),
                     'installer_sha256': checksum(resources / 'install-release.mjs'),
                     'manifest_sha256': checksum(resources / 'release/release-manifest.json')}
        (resources / 'installer-integrity.json').write_text(json.dumps(integrity, indent=2) + '\n')
        info = {'CFBundleExecutable': 'CreativeAgentInstaller', 'CFBundleIdentifier': 'app.creativeagent.installer',
                'CFBundleName': 'Creative Agent Setup', 'CFBundleDisplayName': 'Creative Agent Setup',
                'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': manifest['version'],
                'CFBundleVersion': '2', 'LSMinimumSystemVersion': minimum_macos, 'NSHighResolutionCapable': True,
                'NSPrincipalClass': 'NSApplication', 'NSHumanReadableCopyright': 'Creative Agent contributors'}
        with (contents / 'Info.plist').open('wb') as stream: plistlib.dump(info, stream)
        (resources / 'installer-validation.json').write_text(json.dumps({
            'build_id': manifest['build_id'], 'architecture': manifest['architecture'],
            'developer_id_signed': False, 'notarized': False, 'clean_mac_verified': False,
            'graphical_installation_verified': False,
            'note': 'Unsigned distribution candidate. Clean Mac, Gatekeeper and graphical installation remain release gates.'
        }, indent=2) + '\n')
        # Sign only the application envelope. Never re-sign or mutate the verified
        # bundled runtime: its existing bytes are covered by the release manifest.
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(stage)], check=True, capture_output=True)
        verification = subprocess.run([str(executable), '--verify-bundle'], check=True, text=True, capture_output=True)
        result = json.loads(verification.stdout)
        if result.get('build_id') != manifest['build_id'] or not result.get('verified'):
            raise ValueError('The compiled installer did not verify its embedded release.')
        stage.rename(output)
    return {'app': str(output), 'build_id': manifest['build_id'], 'architecture': manifest['architecture'],
            'payload_verification': 'passed', 'signature': 'ad-hoc only', 'notarized': False,
            'graphical_installation_verified': False, 'clean_mac_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--minimum-macos', default='13.5')
    args = parser.parse_args()
    try: print(json.dumps(build(args.bundle, args.output, args.minimum_macos), indent=2))
    except (OSError, ValueError, subprocess.SubprocessError) as error: raise SystemExit(str(error))


if __name__ == '__main__': main()
