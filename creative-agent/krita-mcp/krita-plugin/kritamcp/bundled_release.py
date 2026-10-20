# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Creative Agent companion that ships inside the packaged Krita Agent.app, copied out on first use.

The app (agent/package-app.sh --release) carries `Contents/Resources/creative-agent-bundle/{companion/, release-manifest.json,
bundle-info.json}`: pure JavaScript, JSON and wasm, signed with the app and never written to. (The name differs from the
`creative-agent` folder the build copies go to in the user's folder, so the two can never be mistaken for each other.) The
companion cannot run its sandbox, state and caches from there, and the panel's configuration (`creative-agent-config.json`)
names absolute paths, so on first use this module:

  1. reads the manifest and, only if this build is not installed yet, checks every file of the bundled companion against its
     SHA-256 list (and that nothing else is there; no entry may climb out of `companion/`);
  2. copies it into the user's own folder, `<AppData>/<settings folder>/creative-agent/<build_id>/`, through a temporary folder
     and one rename, with a `.complete` marker written first: a copy without it is broken and is replaced, and an existing
     complete copy is never touched;
  3. writes `<AppData>/<settings folder>/creative-agent-config.json` unless the artist or an installer already made one. The
     panel uses a config next to the plugin (the dev fork, install.py --krita fork) before this one. A config this module wrote
     follows a newer build, keeps every key it does not own (and the artist's edits), and is never moved back by an older app;
  4. best-effort, removes other build copies (never the one the config points at, never `data/`) and day-old leftovers.

Node itself is not bundled: the config names the managed runtime, which the panel fetches once, SHA-256 verified, on the first
"Connect assistant" (node_runtime.py). Standard library only; no Qt (the caller passes the folders). The copy of a few megabytes
runs on the GUI thread, once per build, at the first "Connect assistant"; later presses only read the manifest.
"""
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

MANAGED = 'bundled-release'          # marks a config written here
CONFIG_NAME = 'creative-agent-config.json'
BUNDLE_FOLDER = 'creative-agent-bundle'
COMPLETE = '.complete'
# What a build owns in the config it manages; everything else (the artist's paintings folder, bridge address, unknown keys) is kept.
OWNED_KEYS = ('companion', 'node', 'node_runtime', 'node_runtimes', 'build_id', 'protocol_version', 'managed_by', 'built_at')
LEFTOVER_AGE = 86400


class BundledReleaseError(ValueError):
    """The bundled companion is not what its manifest says, or cannot be installed, or a config cannot be used."""


def bundled_dir(plugin_dir):
    """The bundle's folder next to the plugin (`Resources/krita/pykrita/kritamcp` -> `Resources/creative-agent-bundle`), or None
    when this is not a packaged app (a dev layout, a path too shallow to have one)."""
    try:
        candidate = Path(plugin_dir).resolve().parents[2] / BUNDLE_FOLDER
    except IndexError:
        return None
    return candidate if (candidate / 'release-manifest.json').is_file() and (candidate / 'companion').is_dir() else None


def app_data_dir(generic_data_location, organization):
    """`<AppData>` of an app with its own settings folder (~/Library/Application Support/KritaAgent), from Qt's
    GenericDataLocation and the organization name, as bridge_config.py takes its port from the organization name. None for
    stock Krita (no organization name): the bundled release is only for the fork."""
    return Path(generic_data_location) / organization if organization and generic_data_location else None


def resolve_config(plugin_dir, app_data):
    """The Creative Agent config to use: the one next to the plugin when there is one (the dev fork, install.py --krita fork),
    else `<AppData>/creative-agent-config.json` (what the packaged app writes), else the plugin folder's path, where an installer
    would write it."""
    beside = Path(plugin_dir) / CONFIG_NAME
    if beside.is_file():
        return str(beside)
    user = Path(app_data) / CONFIG_NAME if app_data else None
    return str(user) if user is not None and user.is_file() else str(beside)


def load_config(path):
    """The config as a dict, or a BundledReleaseError that names the file (missing, unreadable, empty, not JSON, not an object)."""
    try:
        with open(path) as stream:
            data = json.load(stream)
    except FileNotFoundError:
        raise BundledReleaseError('The Creative Agent configuration %s does not exist. Run the installer or start the packaged app.' % path)
    except OSError as error:
        raise BundledReleaseError('The Creative Agent configuration %s cannot be read: %s' % (path, error.strerror or error))
    except ValueError as error:
        raise BundledReleaseError('The Creative Agent configuration %s is empty or damaged (%s). Fix or delete it.' % (path, error))
    if not isinstance(data, dict):
        raise BundledReleaseError('The Creative Agent configuration %s is not a JSON object. Fix or delete it.' % path)
    return data


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(bundled):
    """The manifest (cheap: no hashing), or BundledReleaseError."""
    try:
        manifest = json.loads((Path(bundled) / 'release-manifest.json').read_text())
        build_id = manifest['build_id']
        manifest['files']
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise BundledReleaseError('The bundled release manifest is unreadable: %s' % error)
    if not isinstance(build_id, str) or len(build_id) != 64 or any(c not in '0123456789abcdef' for c in build_id):
        raise BundledReleaseError('The bundled release has no valid build id.')
    return manifest


def build_time(bundled, manifest):
    """When the app was built (an ISO UTC string that sorts): the packager's bundle-info.json, else the manifest's own
    `built_at`, else the manifest file's time. Used to tell a newer build from an older app opened later."""
    try:
        stamp = json.loads((Path(bundled) / 'bundle-info.json').read_text()).get('built_at')
        if isinstance(stamp, str) and stamp:
            return stamp
    except (OSError, ValueError, AttributeError):
        pass
    if isinstance(manifest.get('built_at'), str):
        return manifest['built_at']
    try:
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime((Path(bundled) / 'release-manifest.json').stat().st_mtime))
    except OSError:
        return ''


def verify_companion(bundled):
    """The manifest, after checking the files of `companion/` against it. Raises BundledReleaseError for a missing, changed,
    extra, linked or out-of-folder file."""
    bundled = Path(bundled)
    manifest = read_manifest(bundled)
    expected = {name: digest for name, digest in manifest['files'].items() if name.startswith('companion/')}
    if not expected:
        raise BundledReleaseError('The bundled release lists no companion files.')
    root = (bundled / 'companion').resolve()
    for name in expected:
        if root not in (bundled / name).resolve().parents:
            raise BundledReleaseError('The bundled release names a file outside the companion folder: %s' % name)
    present = set()
    for path in sorted((bundled / 'companion').rglob('*')):
        if path.is_symlink():
            raise BundledReleaseError('The bundled companion contains a link: %s' % path.relative_to(bundled))
        if path.is_file():
            present.add(path.relative_to(bundled).as_posix())
    if present != set(expected):
        difference = sorted(present ^ set(expected))[:3]
        raise BundledReleaseError('The bundled companion does not match its manifest (%s ...).' % ', '.join(difference))
    for name, digest in expected.items():
        if sha256(bundled / name) != digest:
            raise BundledReleaseError('The bundled companion file %s was changed.' % name)
    return manifest


def settings_for(manifest, app_data, runtimes, node, paintings_dir, bridge_url, cache_dir, built_at=''):
    release = Path(app_data) / 'creative-agent' / manifest['build_id']
    data = Path(app_data) / 'creative-agent' / 'data'
    settings = {
        'node': str(node),
        'companion': str(release / 'companion' / 'src' / 'main.mjs'),
        'project_root': str(paintings_dir), 'paintings_dir': str(paintings_dir),
        'data_dir': str(data), 'cache_dir': str(cache_dir), 'output': str(data),
        'bridge_url': bridge_url, 'build_id': manifest['build_id'], 'protocol_version': manifest.get('protocol_version', 2),
        'managed_by': MANAGED, 'built_at': built_at,
    }
    if manifest.get('node_runtime'):
        settings['node_runtime'] = manifest['node_runtime']
        settings['node_runtimes'] = str(runtimes)
    return settings


def write_atomically(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.config-', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def read_existing_config(config):
    """None when there is no config (only FileNotFoundError means that); the dict when there is; BundledReleaseError naming the
    file when it cannot be read or is damaged: such a file is the artist's and is left exactly as it is."""
    try:
        return load_config(config)
    except BundledReleaseError:
        if not os.path.exists(config) and not os.path.islink(config):
            return None
        raise


def prune(parent, app_data, keep_build, protected_paths):
    """Best effort: other 64-hex build copies (not `keep_build`, not one a config points into) and `.release-*` / `.config-*`
    leftovers a day old. Never `data/`, never anything else."""
    now = time.time()
    try:
        for entry in Path(parent).iterdir():
            name = entry.name
            is_build = len(name) == 64 and all(c in '0123456789abcdef' for c in name)
            if is_build and name != keep_build and not any(name in str(p) for p in protected_paths):
                shutil.rmtree(entry, ignore_errors=True)
            elif name.startswith('.release-') and now - entry.stat().st_mtime > LEFTOVER_AGE:
                shutil.rmtree(entry, ignore_errors=True)
        for entry in Path(app_data).iterdir():
            if entry.name.startswith('.config-') and now - entry.stat().st_mtime > LEFTOVER_AGE:
                entry.unlink()
    except OSError:
        pass


def ensure_installed(bundled, app_data, runtimes, node, paintings_dir=None, bridge_url='http://127.0.0.1:5679', cache_dir=None):
    """Make the bundled companion usable. Returns the config path to use. Idempotent: a complete install that is there is not
    touched or re-hashed, a config that is not ours is not replaced, and a newer config is not moved back."""
    bundled, app_data = Path(bundled), Path(app_data)
    config = app_data / CONFIG_NAME
    existing = read_existing_config(config)           # an unreadable or damaged file stops here, untouched
    manifest = read_manifest(bundled)
    parent = app_data / 'creative-agent'
    release = parent / manifest['build_id']
    parent.mkdir(parents=True, exist_ok=True)
    if not (release / COMPLETE).is_file():
        manifest = verify_companion(bundled)           # hashes the files: only when installing
        stage = Path(tempfile.mkdtemp(prefix='.release-', dir=str(parent)))
        try:
            shutil.copytree(bundled / 'companion', stage / 'companion')
            shutil.copy2(bundled / 'release-manifest.json', stage / 'release-manifest.json')
            (stage / COMPLETE).write_text(manifest['build_id'] + '\n')
            if release.exists():                       # a copy without its marker is broken: put it aside and replace it
                broken = Path(tempfile.mkdtemp(prefix='.release-broken-', dir=str(parent)))
                os.rename(release, broken / 'old')
                shutil.rmtree(broken, ignore_errors=True)
            try:
                os.rename(stage, release)
            except OSError:
                if not (release / COMPLETE).is_file():  # not a lost race with another copy: a real failure
                    raise
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
    paintings = Path(paintings_dir) if paintings_dir else app_data / 'paintings'
    paintings.mkdir(parents=True, exist_ok=True)
    built_at = build_time(bundled, manifest)
    settings = settings_for(manifest, app_data, runtimes, node, paintings, bridge_url, cache_dir or app_data / 'cache', built_at)
    if existing is None:
        write_atomically(config, json.dumps(settings, indent=2) + '\n')
        final = settings
    elif existing.get('managed_by') == MANAGED and existing.get('build_id') != manifest['build_id'] and built_at > str(existing.get('built_at', '')):
        # A newer build ships: take what this build owns, keep every other key as the file has it (the artist's edits, new keys).
        merged = dict(settings)
        merged.update({key: value for key, value in existing.items() if key not in OWNED_KEYS})
        write_atomically(config, json.dumps(merged, indent=2) + '\n')
        final = merged
    else:
        final = existing
    prune(parent, app_data, manifest['build_id'], [final.get('companion', '')])
    return config
