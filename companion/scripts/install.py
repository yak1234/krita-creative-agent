"""Install a verified self-contained release; never touch artwork or restart Krita."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile


# Matches scripts/install-release.mjs and kritamcp/node_runtime.py: Node's platform names and nodejs.org's runtime keys.
PLATFORMS = {'Darwin': 'darwin', 'Linux': 'linux', 'Windows': 'win32'}
MACHINES = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'amd64': 'x64'}


def runtime_key(system=None, machine=None):
    system = {'darwin': 'darwin', 'linux': 'linux', 'win32': 'win'}.get(PLATFORMS.get(system or platform.system()))
    machine = MACHINES.get((machine or platform.machine()).lower())
    return system + '-' + machine if system and machine else None


def node_file(system=None):
    return 'node.exe' if (system or platform.system()) == 'Windows' else 'bin/node'


def default_locations(system=None, environ=None, home=None):
    """Krita's plugin folder and this app's per-user folders on each OS (releases and runtimes share a parent)."""
    system, environ, home = system or platform.system(), os.environ if environ is None else environ, Path(home or Path.home())
    if system == 'Windows':
        local, roaming = Path(environ.get('LOCALAPPDATA') or home / 'AppData/Local'), Path(environ.get('APPDATA') or home / 'AppData/Roaming')
        return {'destination': roaming / 'krita/pykrita', 'runtime_destination': local / 'Creative Agent/releases', 'cache': local / 'Creative Agent/cache'}
    if system == 'Linux':
        data, cache = Path(environ.get('XDG_DATA_HOME') or home / '.local/share'), Path(environ.get('XDG_CACHE_HOME') or home / '.cache')
        return {'destination': data / 'krita/pykrita', 'runtime_destination': data / 'creative-agent/releases', 'cache': cache / 'creative-agent'}
    return {'destination': home / 'Library/Application Support/krita/pykrita', 'runtime_destination': home / 'Library/Application Support/Creative Agent/releases',
            'cache': home / 'Library/Caches/Creative Agent'}


def verify_bundle(bundle):
    manifest = json.loads((bundle / 'release-manifest.json').read_text())
    if manifest.get('version') != '1.0.0' or manifest.get('protocol_version') != 2:
        raise ValueError('Unsupported release manifest.')
    if not re.fullmatch(r'[a-f0-9]{64}', manifest.get('build_id', '')):
        raise ValueError('Invalid release identifier.')
    actual_files = {path.relative_to(bundle).as_posix() for path in bundle.rglob('*') if path.is_file()}
    if actual_files - {'release-manifest.json'} != set(manifest['files']):
        raise ValueError('Release file inventory does not match its manifest.')
    for name, expected in manifest['files'].items():
        candidate = bundle / name
        if candidate.is_symlink() or not candidate.is_file() or not candidate.resolve().is_relative_to(bundle.resolve()):
            raise ValueError('Missing or unsafe bundle file: ' + name)
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
            raise ValueError('Bundle checksum mismatch: ' + name)
    for name in ('companion/src/main.mjs', 'plugin/kritamcp/creative_docker.py', 'plugin/kritamcp.desktop'):
        if name not in manifest['files']: raise ValueError('Incomplete release: ' + name)
    if not manifest.get('node_runtime') and 'runtime/' + node_file() not in manifest['files']: raise ValueError('Incomplete release: runtime/' + node_file())
    for name in ('companion/build-info.json', 'plugin/kritamcp/build-info.json'):
        info = json.loads((bundle / name).read_text())
        if any(info.get(key) != manifest.get(key) for key in ('build_id','protocol_version','version')):
            raise ValueError('Component build identity mismatch.')
    payload = {name: checksum for name, checksum in manifest['files'].items()
               if name not in ('companion/build-info.json', 'plugin/kritamcp/build-info.json')}
    expected_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if expected_id != manifest['build_id']: raise ValueError('Release content does not match its identifier.')
    # A release either bundles a runtime for one OS and architecture or pins a managed Node for several;
    # a pinned release may say platform "any".
    runtime, key = manifest.get('node_runtime'), runtime_key()
    supported = (key in (runtime or {}).get('archives', {})) if runtime else MACHINES.get(platform.machine().lower()) == manifest.get('architecture')
    if not (manifest.get('platform') == PLATFORMS.get(platform.system()) or (runtime and manifest.get('platform') == 'any')) or not key or not supported:
        raise ValueError('This release does not support this operating system or architecture.')
    return manifest


def install(bundle, destination, runtime_destination, project):
    bundle, destination, runtime_destination, project = map(lambda p: Path(p).expanduser().resolve(), (bundle, destination, runtime_destination, project))
    manifest = verify_bundle(bundle)
    if not project.is_dir(): raise ValueError('Choose an existing artwork project folder.')
    destination.mkdir(parents=True, exist_ok=True)
    runtime_destination.mkdir(parents=True, exist_ok=True)
    release = runtime_destination / manifest['build_id']
    backup = destination.parent / '.creative-agent-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    with tempfile.TemporaryDirectory(prefix='.creative-install-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        staged_plugin = stage / 'kritamcp'
        shutil.copytree(bundle / 'plugin' / 'kritamcp', staged_plugin)
        shutil.copy2(bundle / 'plugin' / 'kritamcp.desktop', stage / 'kritamcp.desktop')
        if not release.exists():
            runtime_stage = Path(tempfile.mkdtemp(prefix='.release-', dir=runtime_destination))
            try:
                shutil.copytree(bundle / 'companion', runtime_stage / 'companion')
                if (bundle / 'runtime').is_dir(): shutil.copytree(bundle / 'runtime', runtime_stage / 'runtime')
                shutil.copy2(bundle / 'release-manifest.json', runtime_stage)
                runtime_stage.rename(release)
            finally:
                if runtime_stage.exists(): shutil.rmtree(runtime_stage)
        else:
            for name, checksum in manifest['files'].items():
                if not name.startswith(('companion/', 'runtime/')): continue
                candidate = release / name
                if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != checksum:
                    raise ValueError('Installed runtime was modified. Use a fresh runtime destination.')
        # Managed runtime: shared by releases, fetched by the panel on first start (kritamcp/node_runtime.py).
        runtimes = runtime_destination.parent / 'runtimes'
        runtime = manifest.get('node_runtime')
        node = runtimes / ('node-v%s-%s' % (runtime['version'], runtime_key())) / node_file() if runtime else release / 'runtime' / node_file()
        settings = {
            'node': str(node), **({'node_runtime': runtime, 'node_runtimes': str(runtimes)} if runtime else {}),
            'companion': str(release / 'companion' / 'src' / 'main.mjs'),
            'project_root': str(project), 'paintings_dir': str(project),
            # Records and app files live beside the releases, not in the artwork folder (storage-layout).
            'data_dir': str(runtime_destination.parent / 'data'),
            'cache_dir': str(default_locations()['cache']),
            'output': str(runtime_destination.parent / 'data'),
            'bridge_url': 'http://127.0.0.1:5678',
            'build_id': manifest['build_id'], 'protocol_version': 2,
        }
        previous_config = destination / 'kritamcp' / 'creative-agent-config.json'
        if previous_config.exists():
            previous = json.loads(previous_config.read_text())
            for key in ('bridge_url', 'model_idle_timeout_ms'):
                if key in previous: settings[key] = previous[key]
            legacy = previous.get('legacy_output') or previous.get('output')
            if legacy and Path(legacy).resolve() != Path(settings['output']).resolve(): settings['legacy_output'] = legacy
        config = staged_plugin / 'creative-agent-config.json'
        config.write_text(json.dumps(settings, indent=2) + '\n'); config.chmod(0o600)
        backup.mkdir(parents=True)
        moved, installed = [], []
        try:
            for name in ('kritamcp', 'kritamcp.desktop'):
                target = destination / name
                if target.exists(): target.rename(backup / name); moved.append(name)
                (stage / name).rename(target); installed.append(name)
        except Exception:
            for name in ('kritamcp', 'kritamcp.desktop'):
                target = destination / name
                if name in installed:
                    if target.is_dir(): shutil.rmtree(target)
                    elif target.exists(): target.unlink()
                if name in moved: (backup / name).rename(target)
            raise
    return {'destination': str(destination), 'release': str(release), 'backup': str(backup),
            'build_id': manifest['build_id'], 'reload_required': True, 'live_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True, help='Verified output of build-release.py')
    parser.add_argument('--project', type=Path, required=True, help='Existing folder for ordinary artwork files')
    parser.add_argument('--destination', type=Path, default=default_locations()['destination'])
    parser.add_argument('--runtime-destination', type=Path, default=default_locations()['runtime_destination'])
    args = parser.parse_args()
    try: result = install(args.bundle, args.destination, args.runtime_destination, args.project)
    except (ValueError, OSError, KeyError) as error: raise SystemExit(str(error))
    print(json.dumps(result, indent=2))
    print('Files staged. Save your work, then reload Krita when ready. The running panel has not been changed or verified.')


if __name__ == '__main__': main()
