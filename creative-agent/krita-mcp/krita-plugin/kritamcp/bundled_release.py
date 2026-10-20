# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Creative Agent companion that ships inside the packaged Toska.app, copied out on first use.

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

An old installer also put a copy of this plugin (with its own config and data folder) in the profile's pykrita folder, which Krita
reads before the app's; the launcher (agent/app-launcher.c) renames such a copy to `<AppData>/krita/pykrita-shadowed-<date>/`. When
step 3 writes the first config here and there is no data folder yet, the data folder the old config named (chats, model endpoints,
records) is COPIED to the new place (never moved or deleted; the lock and active-session files are skipped), and the panel can say
what happened (`shadow_notices`, `profile_plugin_notice`).

Node itself is not bundled: the config names the managed runtime, which the panel fetches once, SHA-256 verified, on the first
"Connect assistant" (node_runtime.py). Standard library only; no Qt (the caller passes the folders). The companion copy of a few megabytes
runs on the GUI thread, once per build, at the first "Connect assistant"; later presses only read the manifest. The data copy is bounded
(MAX_CARRY_FILES, MAX_CARRY_BYTES, measured first without following links): a larger old data folder is not copied, and the
note and the panel say how to copy it by hand.
"""
import hashlib
import json
import os
import shlex
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
SHADOW_PREFIX = 'pykrita-shadowed-'  # the launcher's folder for a stale plugin copy, beside <AppData>/krita/pykrita (Krita never scans it)
CARRIED_NOTE = 'data-carried-from.json'
RUNTIME_ONLY = ('companion.lock', 'active-session.json')   # state of a running companion: never carried over
# The copy runs on the GUI thread at the first "Connect assistant", so it is bounded: above this the artist copies by hand.
MAX_CARRY_FILES = 50000
MAX_CARRY_BYTES = 500 * 1024 * 1024


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


def read_build_id(plugin_folder):
    """The build id in a plugin folder's build-info.json, or '' (no file, damaged, not a string)."""
    try:
        value = json.loads((Path(plugin_folder) / 'build-info.json').read_text()).get('build_id')
        return value if isinstance(value, str) else ''
    except (OSError, ValueError, AttributeError):
        return ''


def old_config_candidates(app_data):
    """Configs an old installer left in the profile, best first: the one still in the profile's pykrita/kritamcp, then the ones
    inside folders the launcher moved aside (newest first)."""
    krita = Path(app_data) / 'krita'
    found = [krita / 'pykrita' / 'kritamcp' / CONFIG_NAME]
    try:
        moved = [p / 'kritamcp' / CONFIG_NAME for p in krita.iterdir() if p.name.startswith(SHADOW_PREFIX)]
        found += sorted((p for p in moved if p.is_file()), key=lambda p: (p.stat().st_mtime, str(p)), reverse=True)
    except OSError:
        pass
    return found


def _related(a, b):
    """Is `a` the same as `b`, inside it, or an ancestor of it (both resolved)?"""
    return a == b or b in a.parents or a in b.parents


def plausible_data_dir(path, app_data, new_data):
    """Is `path` something we may copy: our own kind of data folder, nowhere near the places that hold everything else? Refused: the
    new data or <AppData> (or anything inside or above them), the home folder or any ancestor of it ("/", Application Support), a
    folder not named `data`, and one with neither `records.sqlite` nor a `chats` folder."""
    try:
        resolved = Path(path).resolve()
        home = Path(os.path.expanduser('~')).resolve()
        if _related(resolved, Path(app_data).resolve()) or _related(resolved, Path(new_data).resolve()):
            return False
        if resolved == home or resolved in home.parents:
            return False
        return resolved.name == 'data' and ((resolved / 'records.sqlite').is_file() or (resolved / 'chats').is_dir())
    except (OSError, RuntimeError):
        return False


def measure(source, max_files, max_bytes):
    """(files, bytes) of what would be copied, or None as soon as either bound is passed. Links are counted, never followed, so a
    cycle cannot loop; the walk stops early, so a huge tree costs no more than the bound."""
    files = size = 0
    pending = [str(source)]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.name in RUNTIME_ONLY:
                    continue
                files += 1
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry.path)
                else:
                    size += entry.stat(follow_symlinks=False).st_size
                if files > max_files or size > max_bytes:
                    return None
    return files, size


def old_data_dir(app_data, new_data):
    """The data folder an old config names that exists, is a real folder and is not `new_data`, else None."""
    for config in old_config_candidates(app_data):
        try:
            value = json.loads(config.read_text()).get('data_dir')
            if not isinstance(value, str) or not value.strip():
                continue
            path = Path(os.path.expanduser(value))
            if path.is_absolute() and path.is_dir() and not path.is_symlink() and plausible_data_dir(path, app_data, new_data):
                return path
        except (OSError, ValueError, AttributeError):
            continue
    return None


def _skip_runtime_files(_folder, names):
    return [name for name in names if name in RUNTIME_ONLY]


def carry_old_data(app_data, parent):
    """Copy the old data folder to `<parent>/data` when that does not exist yet. COPY only: the original is never changed, and
    the new folder appears whole through one rename or not at all. Records what happened in `<parent>/data-carried-from.json`.
    Never raises: the install does not depend on it."""
    data = Path(parent) / 'data'
    if data.exists() or data.is_symlink():
        return
    source = old_data_dir(app_data, data)
    if source is None:
        return
    note = {'from': str(source), 'to': str(data), 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    note['by_hand'] = 'cp -R %s %s   (then delete companion.lock and active-session.json from the copy if present)' % (shlex.quote(str(source)), shlex.quote(str(data)))
    stage = None
    try:
        if measure(source, MAX_CARRY_FILES, MAX_CARRY_BYTES) is None:
            raise OSError('too large for an automatic copy (over %d files or %d MB)' % (MAX_CARRY_FILES, MAX_CARRY_BYTES // (1024 * 1024)))
        stage = Path(tempfile.mkdtemp(prefix='.data-copy-', dir=str(parent)))
        shutil.copytree(source, stage / 'data', symlinks=True, ignore=_skip_runtime_files)
        os.rename(stage / 'data', data)
        note['result'] = 'copied'
    except (OSError, shutil.Error) as error:
        note['result'] = 'failed'
        note['error'] = (str(error) if not getattr(error, 'strerror', None) else error.strerror)[:300]
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
    try:
        write_atomically(Path(parent) / CARRIED_NOTE, json.dumps(note, indent=2) + '\n')
    except OSError:
        pass


def carried_data_note(app_data):
    """What `carry_old_data` did, as a dict, or None when it did nothing."""
    try:
        note = json.loads((Path(app_data) / 'creative-agent' / CARRIED_NOTE).read_text())
        return note if isinstance(note, dict) and note.get('result') in ('copied', 'failed') else None
    except (OSError, ValueError):
        return None


def shadow_notices(app_data):
    """Plain lines for the panel: an old plugin copy the launcher moved out of the profile (with its build and where it is), and
    the data copied from it. Empty when nothing happened. Shown as text, never a dialog."""
    lines = []
    if app_data is None:
        return lines
    try:
        moved = sorted((p for p in (Path(app_data) / 'krita').iterdir() if p.name.startswith(SHADOW_PREFIX) and (p / 'kritamcp').is_dir()),
                       key=lambda p: p.name, reverse=True)
    except OSError:
        moved = []
    for folder in moved[:3]:
        build = read_build_id(folder / 'kritamcp')
        lines.append('An older Creative Agent plugin (%s) was in your profile and would have replaced the one built into this app. '
                     'It was moved, not deleted, to %s.' % ('build ' + build[:12] if build else 'no build id', folder))
    note = carried_data_note(app_data)
    if note and note['result'] == 'copied':
        lines.append('Your chats and model settings were copied (the originals were not touched) from %s to %s.' % (note.get('from'), note.get('to')))
    elif note:
        lines.append('Your chats and model settings could not be copied from %s (%s). They are untouched there. To copy them by hand, quit Krita and run: %s'
                     % (note.get('from'), note.get('error', 'unknown error'), note.get('by_hand', 'cp -R <old data folder> <new data folder>')))
    return lines


def profile_plugin_notice(plugin_dir, app_data, app_plugin):
    """A line when THIS plugin was loaded from the profile's pykrita folder while the app carries its own, different one (the
    launcher leaves a link or an escape-variable copy alone), else None."""
    if app_data is None or app_plugin is None or not (Path(app_plugin) / '__init__.py').is_file():
        return None
    folder = Path(os.path.abspath(plugin_dir))
    if (Path(app_data) / 'krita' / 'pykrita') not in folder.parents:
        return None
    mine, bundled = read_build_id(folder), read_build_id(app_plugin)
    if mine and mine == bundled:
        return None
    return ('This plugin was loaded from your profile folder (%s, %s), not from the app (%s). The copy in the profile hides the app\'s plugin.'
            % (folder, 'build ' + mine[:12] if mine else 'no build id', 'build ' + bundled[:12] if bundled else 'no build id'))


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
            elif name.startswith(('.release-', '.data-copy-')) and now - entry.stat().st_mtime > LEFTOVER_AGE:
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
        carry_old_data(app_data, parent)                # before the config names the new data folder
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
