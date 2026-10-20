#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Package the fork's install tree (_install) as one self-contained "Krita Agent.app".

Driven by agent/package-app.sh (see its header and AGENT-FORK.md, "Packaging"). Python 3.9 compatible, standard library
only, because the script runs with the Command Line Tools' /usr/bin/python3.

    package_app.py package [INSTALL] --out DIR [--packages DIR] [--source DIR] [--release DIR] [--allow-dirty]
                           [--allow-stale-build] [--allow-unpublished] [--source-url URL] [--no-sign]
    package_app.py smoke BUNDLE            headless imports from a temporary copy, with the build trees unreadable
    package_app.py check BUNDLE            the self-containment and layout checks (exit 1 on any problem)
    package_app.py sign BUNDLE             sign inside-out (KRITA_AGENT_SIGN_IDENTITY, else ad-hoc)

The logic that has to be right is in plain functions (macho_load_commands, check_bundle, layout_problems,
merge_first_run_defaults, ...) so that tests run them on a small fake bundle.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))      # -I does not put the script's folder on the path
import package_notices as notices  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = 'Krita Agent.app'
BUNDLE_ID = 'local.kritaagent'
SETTINGS_FOLDER = 'KritaAgent'
PLUGIN_KEY = 'enable_kritamcp'
SYSTEM_PREFIXES = ('/usr/lib/', '/System/Library/', '/Library/Apple/')
MACHO_MAGICS = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe',
                b'\xbe\xba\xfe\xca'}
DEP_COMMANDS = {'LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB', 'LC_LOAD_UPWARD_DYLIB', 'LC_LAZY_LOAD_DYLIB'}


# ---------------------------------------------------------------------------------------------------------------- Mach-O

def is_macho(path):
    """Is `path` a Mach-O file (thin or universal)? Symlinks and directories are not."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
        with open(path, 'rb') as stream:
            head = stream.read(8)
    except OSError:
        return False
    if head[:4] not in MACHO_MAGICS:
        return False
    if head[:4] in (b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):          # Java classes share the magic: a fat file counts <30 archs
        return int.from_bytes(head[4:8], 'big') < 30
    return True


class MachO:
    """What a Mach-O file loads: dependencies (the names it asks for), rpaths, and its own install name."""

    def __init__(self, deps, rpaths, ident):
        self.deps, self.rpaths, self.ident = deps, rpaths, ident


def parse_load_commands(text):
    """Parse the output of `otool -l` (all architectures merged, in order, without duplicates)."""
    deps, rpaths, ident = [], [], None
    command = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('cmd '):
            command = stripped.split()[1]
            continue
        if command in DEP_COMMANDS and stripped.startswith('name '):
            name = re.match(r'name (.*) \(offset \d+\)$', stripped).group(1)
            if name not in deps:
                deps.append(name)
        elif command == 'LC_ID_DYLIB' and stripped.startswith('name '):
            ident = re.match(r'name (.*) \(offset \d+\)$', stripped).group(1)
        elif command == 'LC_RPATH' and stripped.startswith('path '):
            path = re.match(r'path (.*) \(offset \d+\)$', stripped).group(1)
            if path not in rpaths:
                rpaths.append(path)
    return MachO(deps, rpaths, ident)


def macho_load_commands(path):
    out = subprocess.run(['otool', '-l', str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError('otool -l %s: %s' % (path, out.stderr.strip()))
    return parse_load_commands(out.stdout)


def macho_archs(path):
    out = subprocess.run(['lipo', '-archs', str(path)], capture_output=True, text=True)
    return out.stdout.split() if out.returncode == 0 else []


def thin_to(path, arch):
    """A universal file is cut to `arch`, the architecture of the build's main executable. Returns True if it was cut."""
    archs = macho_archs(path)
    if len(archs) <= 1:
        return False
    if arch not in archs:
        raise RuntimeError('%s has no %s slice (%s)' % (path, arch, ' '.join(archs)))
    temporary = str(path) + '.thin'
    run(['lipo', '-thin', arch, str(path), '-output', temporary])
    os.replace(temporary, path)
    return True


def run(command, **kwargs):
    result = subprocess.run([str(part) for part in command], capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError('%s failed (%d): %s' % (' '.join(str(p) for p in command[:3]), result.returncode,
                                                   (result.stderr or result.stdout).strip()[:500]))
    return result.stdout


def make_writable(path):
    mode = os.lstat(path).st_mode
    if not stat.S_ISLNK(mode):
        os.chmod(path, stat.S_IMODE(mode) | 0o200)


def adhoc_sign(path):
    """Sign one Mach-O file ad hoc, keeping what it already has (entitlements, requirements, flags)."""
    run(['codesign', '--force', '--sign', '-', '--timestamp=none',
         '--preserve-metadata=entitlements,requirements,flags,runtime', str(path)])


def invalid_signatures(bundle):
    """Mach-O files of `bundle` whose signature does not verify. Nothing in a bundle may be executed while this is not empty:
    on Apple silicon the kernel kills such a process (SIGKILL, Code Signature Invalid) and macOS opens a crash dialog."""
    bad = []
    for path in macho_files(bundle):
        if subprocess.run(['codesign', '--verify', '--strict', path], capture_output=True).returncode != 0:
            bad.append(path)
    return bad


def require_runnable(bundle):
    """Refuse (with a message, never a crash) to execute anything from a bundle with an invalid signature anywhere."""
    bad = invalid_signatures(bundle)
    if bad:
        raise RuntimeError('refusing to run anything from %s: %d Mach-O files have an invalid signature (first: %s)'
                           % (bundle, len(bad), rel(bad[0], bundle)))


def is_system(name):
    return name.startswith(SYSTEM_PREFIXES)


def inside(path, root):
    path, root = os.path.normpath(str(path)), os.path.normpath(str(root))
    return path == root or path.startswith(root + os.sep)


def macho_files(bundle):
    """Every Mach-O file under `bundle` (symlinks are not followed or counted)."""
    found = []
    for folder, dirs, files in os.walk(bundle, followlinks=False):
        for name in files:
            path = os.path.join(folder, name)
            if is_macho(path):
                found.append(path)
    return sorted(found)


def expand_rpath(rpath, file, bundle):
    """Where dyld looks for `rpath` as written in `file`, as an absolute path (an @executable_path entry is read relative to
    the bundle's MacOS folder when `file` is not itself an executable there)."""
    file_dir = os.path.dirname(str(file))
    macos = os.path.join(str(bundle), 'Contents', 'MacOS')
    if rpath.startswith('@loader_path'):
        return os.path.normpath(file_dir + rpath[len('@loader_path'):])
    if rpath.startswith('@executable_path'):
        base = file_dir if inside(file_dir, macos) else macos
        return os.path.normpath(base + rpath[len('@executable_path'):])
    return rpath


def resolve_dependency(name, file, info, bundle, executable_rpaths):
    """The file in the bundle that dependency `name` of `file` resolves to, or None.
    @rpath is tried against the file's own rpaths, then the executables' (dyld also searches the loading chain)."""
    file_dir = os.path.dirname(str(file))
    macos = os.path.join(str(bundle), 'Contents', 'MacOS')
    if name.startswith('@rpath/'):
        for rpath in list(info.rpaths) + list(executable_rpaths):
            candidate = os.path.join(expand_rpath(rpath, file, bundle), name[len('@rpath/'):])
            if os.path.exists(candidate):
                return os.path.normpath(candidate)
        return None
    if name.startswith('@loader_path/'):
        candidate = os.path.normpath(os.path.join(file_dir, name[len('@loader_path/'):]))
    elif name.startswith('@executable_path/'):
        base = file_dir if inside(file_dir, macos) else macos
        candidate = os.path.normpath(os.path.join(base, name[len('@executable_path/'):]))
    else:
        candidate = name
    return candidate if os.path.exists(candidate) else None


# ------------------------------------------------------------------------------------------------------------- the check

def check_bundle(bundle, forbidden=()):
    """Self-containment problems of `bundle` (a list of strings; empty is clean):
      - a Mach-O file loads something by an absolute path outside the system (/usr/lib, /System/Library);
      - a dependency (@rpath, @loader_path, @executable_path) that does not resolve to a file inside the bundle;
      - an rpath that points outside the bundle or is an absolute path;
      - an install name or any of the above mentioning one of the `forbidden` trees (_install, forks/ ...)."""
    bundle = str(bundle)
    problems = []
    macos = os.path.join(bundle, 'Contents', 'MacOS')
    files = macho_files(bundle)
    infos = {}
    for path in files:
        try:
            infos[path] = macho_load_commands(path)
        except RuntimeError as error:
            problems.append('%s: cannot read (%s)' % (rel(path, bundle), error))
    executable_rpaths = []
    for path, info in infos.items():
        if os.path.dirname(path) == macos:
            executable_rpaths += [expand_rpath(r, path, bundle) for r in info.rpaths]
    forbidden = tuple(forbidden) + ('/_install', '/forks/')
    for path, info in sorted(infos.items()):
        where = rel(path, bundle)
        for rpath in info.rpaths:
            if not rpath.startswith(('@loader_path', '@executable_path')):
                problems.append('%s: absolute rpath %s' % (where, rpath))
                continue
            expanded = expand_rpath(rpath, path, bundle)
            if not inside(expanded, bundle):
                problems.append('%s: rpath %s leaves the bundle' % (where, rpath))
        if info.ident and (info.ident.startswith('/') and not inside(info.ident, bundle)):
            problems.append('%s: install name %s points outside the bundle' % (where, info.ident))
        for name in info.deps:
            if is_system(name):
                continue
            if name.startswith('/'):
                problems.append('%s: absolute dependency %s' % (where, name))
                continue
            if any(mark in name for mark in forbidden):
                problems.append('%s: dependency %s refers to a build tree' % (where, name))
                continue
            target = resolve_dependency(name, path, info, bundle, executable_rpaths)
            if target is None:
                problems.append('%s: %s does not resolve inside the bundle' % (where, name))
            elif not inside(os.path.realpath(target), os.path.realpath(bundle)):
                problems.append('%s: %s resolves outside the bundle (%s)' % (where, name, target))
    return problems


def rel(path, root):
    return os.path.relpath(str(path), str(root))


def layout_problems(bundle):
    """What Krita needs at the places it looks (KoResourcePaths::getInstallationPrefix and friends)."""
    bundle = Path(bundle)
    contents = bundle / 'Contents'
    required = [
        'Info.plist', 'MacOS/krita', 'MacOS/krita-app', 'MacOS/kritarunner', 'Resources/kritaplugins',
        'Resources/krita/pykrita/kritamcp/__init__.py', 'Resources/krita/pykrita/kritamcp.desktop',
        'Resources/LICENSES/README.txt', 'Resources/LICENSES/THIRD-PARTY-NOTICES.txt', 'Resources/LICENSES/GPL-3.0-or-later.txt',
        'Resources/BUILD.txt', 'Resources/creative-agent-bundle/release-manifest.json', 'Resources/creative-agent-bundle/companion/src/main.mjs', 'Resources/creative-agent-bundle/bundle-info.json', 'PlugIns/platforms', 'PlugIns/kritapykrita.so',
        'Frameworks/Python.framework/Versions/Current/lib', 'Resources/krita-python-libs/krita/__init__.py',
        'Resources/krita-python-libs/PyKrita/krita.so', 'Frameworks/QtCore.framework/Versions/A/QtCore',
    ]
    problems = ['missing Contents/%s' % item for item in required if not os.path.lexists(contents / item)]
    for link, target in (('share', 'Resources'), ('etc', 'Resources/etc')):
        path = contents / link
        if not os.path.islink(path) or os.path.normpath(os.readlink(path)) != target:
            problems.append('Contents/%s should be a symlink to %s' % (link, target))
    if os.path.isfile(contents / 'Resources/creative-agent-bundle/release-manifest.json'):
        module = load_bundled_release()
        try:
            module.verify_companion(contents / 'Resources/creative-agent-bundle')
        except module.BundledReleaseError as error:
            problems.append('the bundled companion: %s' % error)
        # The companion refuses a bridge whose build id differs from its own (runtime.mjs): the plugin in the app must carry
        # the release's, or the panel says "Reload the matching Creative Agent build" on every first run.
        try:
            expected = json.loads((contents / 'Resources/creative-agent-bundle/release-manifest.json').read_text())
            actual = json.loads((contents / 'Resources/krita/pykrita/kritamcp/build-info.json').read_text())
            if actual.get('build_id') != expected.get('build_id') or actual.get('protocol_version') != expected.get('protocol_version', 2):
                problems.append('the plugin build id %s (protocol %s) is not the companion\'s %s (protocol %s)' % (
                    str(actual.get('build_id'))[:12], actual.get('protocol_version'), str(expected.get('build_id'))[:12], expected.get('protocol_version', 2)))
        except (OSError, ValueError):
            problems.append('the plugin build id cannot be read (kritamcp/build-info.json is missing or invalid): the companion would refuse it')
    vendor = list((contents / 'Resources/krita/pykrita/kritamcp/_vendor').glob('*/numpy/__init__.py'))
    if not vendor:
        problems.append('no vendored numpy under kritamcp/_vendor/<os>-<machine>')
    try:
        with open(contents / 'Info.plist', 'rb') as stream:
            plist = plistlib.load(stream)
        if plist.get('CFBundleIdentifier') != BUNDLE_ID:
            problems.append('CFBundleIdentifier is %r, not %s' % (plist.get('CFBundleIdentifier'), BUNDLE_ID))
        if plist.get('CFBundleExecutable') != 'krita':
            problems.append('CFBundleExecutable is %r, not krita' % plist.get('CFBundleExecutable'))
        if not plist.get('KritaAgentBuild'):
            problems.append('Info.plist has no KritaAgentBuild')
    except (OSError, plistlib.InvalidFileException, ValueError, KeyError) as error:
        problems.append('Info.plist unreadable: %s' % error)
    return problems


# --------------------------------------------------------------------------------------------- first-run defaults (text)

def merge_first_run_defaults(text):
    """What agent/app-launcher.c does to kritarc, in Python (the tests compare the two): `enable_kritamcp=true` in
    [python], unless a value is already there (as `key=`, `key =` or `key[$i]=`). A byte order mark and CRLF line ends are
    kept. Returns the new text, or None when nothing changes."""
    bom = '\ufeff' if text.startswith('\ufeff') else ''
    body = text[len(bom):]
    lines = body.split('\n') if body else []
    in_python, insert_at, crlf = False, None, False
    for index, line in enumerate(lines):
        if line.startswith('['):
            in_python = line.rstrip(' \r') == '[python]'
            if in_python:
                insert_at, crlf = index + 1, line.endswith('\r')
        elif in_python and re.match(r'%s(\[[^\]]*\])?[ \t]*=' % PLUGIN_KEY, line):
            return None
    eol = '\r\n' if crlf else '\n'
    key = PLUGIN_KEY + '=true'
    if insert_at is not None:
        if insert_at >= len(lines):                      # the header is the last line and has no line end
            return bom + '\n'.join(lines) + eol + key + eol
        lines.insert(insert_at, key + ('\r' if crlf else ''))
        return bom + '\n'.join(lines)
    out = body
    if out and not out.endswith('\n'):
        out += eol
    if out:
        out += eol
    return bom + out + '[python]' + eol + key + eol


def helper_folder(home, settings=SETTINGS_FOLDER):
    """The user pykrita folder of the bundle's kritarunner process (a name of its own under the app's settings folder): one of
    the first entries of the bundled Python's sys.path. The packaged Python takes only its own paths, never the caller's
    PYTHONPATH, so helper scripts are staged here, in the TEMPORARY home, and run with `kritarunner -s <module>`."""
    return Path(home) / 'Library' / 'Application Support' / settings / 'kritarunner' / 'krita' / 'pykrita'


def stage_helper_script(home, name, text, settings=SETTINGS_FOLDER):
    folder = helper_folder(home, settings)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + '.py')
    path.write_text(text)
    return path


def sys_path_problems(entries, copy, home, poison=None):
    """Entries of the bundled Python's sys.path that are outside the bundle and the temporary home, and a leak of the caller's
    PYTHONPATH (`poison`, a folder the test run put there to be ignored)."""
    problems = []
    real_copy, real_home = os.path.realpath(str(copy)), os.path.realpath(str(home))
    for entry in entries:
        if entry and not (inside(os.path.realpath(entry), real_copy) or inside(os.path.realpath(entry), real_home)):
            problems.append('sys.path has an entry outside the bundle and the temporary home: %s' % entry)
    if poison and any(entry and os.path.realpath(entry) == os.path.realpath(str(poison)) for entry in entries):
        problems.append('the caller\'s PYTHONPATH reached the bundled Python: it must ignore it (hermetic)')
    return problems


def settings_folder(source):
    """The build's KRITA_APP_SETTINGS_FOLDER (from its CMake cache), else the fork's default."""
    try:
        for line in (Path(source) / '_build' / 'CMakeCache.txt').read_text().splitlines():
            if line.startswith('KRITA_APP_SETTINGS_FOLDER:'):
                value = line.split('=', 1)[1].strip()
                if value:
                    return value
    except OSError:
        pass
    return SETTINGS_FOLDER


def launcher_environment(contents):
    """The variables the launcher sets before it starts Krita (agent/app-launcher.c prints the same with the test hook)."""
    contents = str(contents)
    return {'PYTHONNOUSERSITE': '1', 'MLT_REPOSITORY': contents + '/PlugIns/mlt', 'MLT_DATA': contents + '/Resources/mlt',
            'MLT_PROFILES_PATH': contents + '/Resources/mlt/profiles', 'MLT_PRESETS_PATH': contents + '/Resources/mlt/presets'}


# ------------------------------------------------------------------------------------------------------------ the copy

class Refused(Exception):
    """The script will not do what was asked (a message for the person, not a crash)."""


def install_architecture(install):
    """The one architecture of the build's main executable (not the machine's: that is wrong under Rosetta). The app is
    arm64-only; anything else is refused."""
    main = Path(install) / 'bin' / 'krita.app' / 'Contents' / 'MacOS' / 'krita'
    archs = macho_archs(main)
    if len(archs) != 1:
        raise Refused('%s has architectures %r: the app is built for one (arm64)' % (main, archs))
    if archs[0] != 'arm64':
        raise Refused('the build is %s: Krita Agent is arm64-only' % archs[0])
    return archs[0]


def fold(path):
    """A path as the file system compares it: canonical (links resolved), Unicode-normalised, case-folded (APFS is not
    case-sensitive)."""
    return unicodedata.normalize('NFC', os.path.realpath(os.path.expanduser(str(path)))).casefold()


def within(path, root):
    return path == root or path.startswith(root.rstrip('/') + '/')


def check_output_folder(out, install, source=None, home=None, applications=None):
    """Refuse an output folder the packager must not write into (the bundle in it is deleted and made again): any spelling or
    link to /Applications or ~/Applications (KRITA_AGENT_APPLICATIONS_DIR adds one, for tests), the system folders, the home
    folder itself, the inside of an app, or a folder that contains the install tree or the source tree."""
    home_folder = fold(home or os.environ.get('HOME') or Path.home())
    target = fold(out)
    if target == '/' or any(within(target, root) for root in ('/system', '/usr', '/bin', '/sbin', '/library', '/private/etc', '/private/var/db')):
        raise Refused('%s is a system folder' % out)
    if target == home_folder:
        raise Refused('%s is the home folder itself: give a folder of its own' % out)
    roots = {fold('/Applications'), fold(Path(home_folder) / 'Applications')}
    for extra in (os.environ.get('KRITA_AGENT_APPLICATIONS_DIR'), applications):
        if extra:
            roots.add(fold(extra))
    if any(within(target, root) for root in roots):
        raise Refused('%s is in an Applications folder: package elsewhere, and put the app there with agent/install-app.sh' % out)
    if any(part.endswith('.app') for part in target.split('/')):
        raise Refused('%s is inside an app bundle' % out)
    for name, tree in (('install', install), ('source', source)):
        if tree and within(fold(tree), target):
            raise Refused('%s contains the %s tree %s' % (out, name, tree))
    if install and within(target, fold(install)):
        raise Refused('%s is inside the install tree, which is read-only input' % out)


def safe_to_replace(bundle):
    """An existing Krita Agent.app that this script made (the bundle id says so), or nothing."""
    plist = Path(bundle) / 'Contents' / 'Info.plist'
    if not os.path.lexists(bundle):
        return True
    try:
        with open(plist, 'rb') as stream:
            return plistlib.load(stream).get('CFBundleIdentifier') == BUNDLE_ID
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


class Packager:
    def __init__(self, install, out, packages=None, source=None, log=print, options=None, release=None):
        self.install = Path(install).resolve()
        self.out = Path(out)
        self.packages = Path(packages) if packages else None
        self.source = Path(source) if source else self.install.parent
        self.release = Path(release) if release else None
        self.options = dict(options or {})
        self.record = None
        self.release_info = None
        self.log = log
        self.bundle = self.out / APP_NAME
        self.contents = self.bundle / 'Contents'
        self.frameworks = self.contents / 'Frameworks'
        self.macos = self.contents / 'MacOS'
        self.resources = self.contents / 'Resources'
        self.plugins = self.contents / 'PlugIns'
        self.sources = {}          # copied Mach-O file -> the file it came from (to resolve @loader_path in the source tree)
        self.trees = []            # (destination folder, source folder) of every copied tree
        self.problems = []
        self.built_from = ''
        self.arch = install_architecture(self.install)
        self.neutralise = [self.install, self.source, ROOT.parent, os.path.expanduser('~')]   # what the binaries must not carry of this machine

    # -- helpers
    def copy_file(self, source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
        make_writable(destination)

    def copy_tree(self, source, destination, ignore=None, symlinks=True):
        self.trees.append((str(destination), str(source)))
        shutil.copytree(source, destination, symlinks=symlinks, ignore=ignore, dirs_exist_ok=True)

    def copy_with_links(self, source, destination):
        """Copy `source` and the chain of symlinks that lead to it, as they are (relative links stay relative)."""
        while True:
            if destination.exists() or destination.is_symlink():
                return
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                target = os.readlink(source)
                if os.path.isabs(target):
                    self.copy_file(source.resolve(), destination)
                    return
                os.symlink(target, destination)
                source, destination = source.parent / target, destination.parent / target
                source, destination = Path(os.path.normpath(source)), Path(os.path.normpath(destination))
            else:
                self.copy_file(source, destination)
                self.sources[str(destination)] = str(source)
                return

    # -- steps
    def start(self):
        if not safe_to_replace(self.bundle):
            raise Refused('%s exists and is not a Krita Agent.app made by this script: not deleting it' % self.bundle)
        if self.bundle.exists():
            shutil.rmtree(self.bundle)
        for folder in (self.macos, self.frameworks, self.resources, self.plugins):
            folder.mkdir(parents=True)

    def copy_executables(self):
        app = self.install / 'bin' / 'krita.app'
        self.copy_file(app / 'Contents/MacOS/krita', self.macos / 'krita-app')
        self.sources[str(self.macos / 'krita-app')] = str(app / 'Contents/MacOS/krita')
        for name in ('kritarunner', 'ffmpeg', 'ffprobe'):
            source = self.install / 'bin' / name
            if source.exists():
                self.copy_file(source, self.macos / name)
                self.sources[str(self.macos / name)] = str(source)
        for icon in (app / 'Contents/Resources').glob('*.icns'):
            self.copy_file(icon, self.resources / icon.name)

    def copy_resources(self):
        keep_out = {'aclocal', 'doc', 'ECM', 'eigen3', 'emacs', 'gettext', 'gettext-0.21', 'info', 'kf5', 'man', 'ocio',
                    'pkgconfig', 'mime', 'translations', 'cmake', 'libraw', 'WebP', 'theora', 'xml', 'qt6',
                    'qlogging-categories6', 'metainfo', 'applications', 'fontconfig', 'licenses'}
        icons = {'krita.icns', 'krita-krz.icns', 'krita-kra.icns', 'Assets.car'}

        def ignore(folder, names):
            if os.path.normpath(folder) == str(self.install / 'share'):
                return [n for n in names if n in keep_out or n in icons]
            return [n for n in names if n in ('.DS_Store', '__pycache__')]     # bytecode is written again here, with the right names

        self.copy_tree(self.install / 'share', self.resources, ignore=ignore)
        # share/locale is large and is Krita's translations: keep it. Qt's own:
        if (self.install / 'translations').is_dir():
            self.copy_tree(self.install / 'translations', self.resources / 'translations')
        if (self.install / 'qml').is_dir():
            self.copy_tree(self.install / 'qml', self.resources / 'qml', ignore=shutil.ignore_patterns('*.qmltypes', '*.prl'))
        # fontconfig: root/etc/fonts. conf.d holds links into share/fontconfig: make them files.
        fonts = self.install / 'etc' / 'fonts'
        if fonts.is_dir():
            self.copy_tree(fonts, self.resources / 'etc' / 'fonts', symlinks=False)
        fonts_conf = self.resources / 'etc' / 'fonts' / 'fonts.conf'
        if fonts_conf.exists():                # upstream's CI build folder is baked into the cache folder list: drop that one entry
            text = fonts_conf.read_text()
            fonts_conf.write_text(re.sub(r'[ \t]*<cachedir>/Users/[^<]*</cachedir>\n', '', text))
        for link, target in (('share', 'Resources'), ('etc', 'Resources/etc')):
            os.symlink(target, self.contents / link)

    def overlay_plugin(self):
        """--overlay-plugin DIR: use this checkout's plugin (kritamcp) instead of the one the build installed, for a package made
        before the next `ninja install` brings the plugin up to date. Stamped into the notices."""
        folder = self.options.get('overlay_plugin')
        if not folder:
            return
        source = Path(folder)
        target = self.resources / 'krita' / 'pykrita' / 'kritamcp'
        if not (source / '__init__.py').is_file():
            raise Refused('%s is not a kritamcp plugin folder' % source)
        shutil.rmtree(target)
        self.copy_tree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'creative-agent-config.json', 'build-info.json', '.DS_Store'))
        desktop = source.parent / 'kritamcp.desktop'
        if desktop.is_file():
            shutil.copy2(desktop, target.parent / 'kritamcp.desktop')

    def copy_plugins(self):
        keep = ('generic', 'iconengines', 'imageformats', 'kf6', 'networkinformation', 'platforms', 'sqldrivers', 'styles', 'tls')
        for name in keep:
            if (self.install / 'plugins' / name).is_dir():
                self.copy_tree(self.install / 'plugins' / name, self.plugins / name, ignore=shutil.ignore_patterns('*.a', '*.prl'))
        for plugin in sorted((self.install / 'lib' / 'kritaplugins').iterdir()):
            if plugin.is_file():
                self.copy_file(plugin, self.plugins / plugin.name)
                self.sources[str(self.plugins / plugin.name)] = str(plugin)
        if (self.install / 'lib' / 'mlt').is_dir():
            self.copy_tree(self.install / 'lib' / 'mlt', self.plugins / 'mlt')

    def copy_python(self):
        framework = self.install / 'lib' / 'Python.framework'
        destination = self.frameworks / 'Python.framework'
        unwanted_dirs = {'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3', 'config-3.13-darwin',
                         'include', 'Headers', 'Python.app', 'bin'}
        unwanted_packages = ('pip', 'pip-', 'setuptools', 'setuptools-', 'wheel', 'wheel-', 'sip-', 'pyqt_builder', 'pyqtbuild',
                             'sipbuild', 'ply', 'packaging', 'tomli', '_distutils_hack', 'distutils-precedence', 'README',
                             'ddc459050edb75a05942__mypyc')

        def ignore(folder, names):
            skipped = []
            in_site = os.path.basename(folder) == 'site-packages'
            for name in names:
                if name in ('__pycache__', '.DS_Store') or name.endswith('_debug'):
                    skipped.append(name)
                elif name in unwanted_dirs and not in_site and 'PyQt6' not in folder:
                    skipped.append(name)
                elif in_site and name.startswith(unwanted_packages):
                    skipped.append(name)
            return skipped

        self.copy_tree(framework, destination, ignore=ignore)
        # The interpreter binary: python3.13 (the launcher stub) is needed to compile the .py files; keep it only in bin/.
        binary = framework / 'Versions' / 'Current' / 'bin' / 'python3.13'
        if binary.exists():
            self.copy_file(binary.resolve(), destination / 'Versions' / '3.13' / 'bin' / 'python3.13')
        # krita-python-libs: Krita's own `krita` package and the PyKrita module.
        self.copy_tree(self.install / 'lib' / 'krita-python-libs', self.resources / 'krita-python-libs',
                       ignore=shutil.ignore_patterns('__pycache__'))

    def copy_agent_packages(self):
        """numpy, OpenCV, psutil, xxhash into the plugin's own `_vendor/<os>-<machine>` (kritamcp/vendor.py already reads it)."""
        plugin = self.resources / 'krita' / 'pykrita' / 'kritamcp'
        tag = 'macos-%s' % self.arch
        target = plugin / '_vendor' / tag
        if self.packages is not None:
            self.copy_tree(self.packages, target, ignore=shutil.ignore_patterns('bin', '__pycache__'))
            return
        python = self.python_version()
        requirements = ROOT / 'creative-agent' / 'krita-mcp' / 'krita-plugin' / 'python-packages.txt'
        uv_platform = {'arm64': 'aarch64-apple-darwin', 'x86_64': 'x86_64-apple-darwin'}[self.arch]
        target.parent.mkdir(parents=True, exist_ok=True)
        run(['uv', 'pip', 'install', '--quiet', '--target', target, '--python-version', python, '--python-platform', uv_platform,
             '--only-binary', ':all:', '-r', requirements])
        shutil.rmtree(target / 'bin', ignore_errors=True)

    def python_version(self):
        versions = sorted((p.name for p in (self.frameworks / 'Python.framework' / 'Versions').glob('3.*')),
                          key=lambda v: tuple(int(n) for n in re.findall(r'\d+', v)))
        if not versions:
            raise RuntimeError('no Python in the bundle')
        return versions[-1]

    # -- Mach-O closure and rewrite
    def source_of(self, path):
        path = str(path)
        if path in self.sources:
            return self.sources[path]
        for destination, source in self.trees:
            if inside(path, destination):
                return os.path.join(source, os.path.relpath(path, destination))
        return None

    def to_bundle_name(self, source):
        """The @rpath name for a library in the install tree: its path under lib/."""
        lib = self.install / 'lib'
        try:
            return os.path.relpath(source, lib) if inside(source, lib) else None
        except ValueError:
            return None

    def bring_library(self, rpath_name):
        """Make Frameworks/<rpath_name> exist, copying it (and its links, or the whole framework) from install/lib."""
        destination = self.frameworks / rpath_name
        if destination.exists() or destination.is_symlink():
            return True
        parts = rpath_name.split('/')
        top = parts[0]
        source_top = self.install / 'lib' / top
        if top.endswith('.framework'):
            if not source_top.is_dir():
                return False
            ignore = shutil.ignore_patterns('Headers', '*_debug', '*.prl', '.DS_Store')
            self.copy_tree(source_top, self.frameworks / top, ignore=ignore)
            for path in (self.frameworks / top).rglob('*'):
                if path.is_file() and not path.is_symlink() and is_macho(path):
                    self.sources[str(path)] = str(source_top / path.relative_to(self.frameworks / top))
            return destination.exists()
        source = self.install / 'lib' / rpath_name
        if not (source.exists() or source.is_symlink()):
            return False
        self.copy_with_links(source, destination)
        return destination.exists()

    def process(self, path):
        """Cut a universal file, bring in what it loads, and point everything at the bundle. Returns the number of changes."""
        thinned = thin_to(path, self.arch)
        patched = neutralise_file(path, self.neutralise)
        info = macho_load_commands(path)
        is_executable = os.path.dirname(path) == str(self.macos)
        source = self.source_of(path)
        changes = []
        for name in info.deps:
            if is_system(name):
                continue
            if name.startswith('@rpath/'):
                if not self.bring_library(name[len('@rpath/'):]) and not self.exists_via_rpaths(path, info, name):
                    self.problems.append('%s: %s not found in the install tree' % (rel(path, self.bundle), name))
                continue
            replacement = self.relocate(name, path, source)
            if replacement:
                changes += ['-change', name, replacement]
            elif not (name.startswith(('@loader_path/', '@executable_path/')) and resolve_dependency(name, path, info, self.bundle, [])):
                self.problems.append('%s: cannot relocate %s' % (rel(path, self.bundle), name))
        wanted = '@executable_path/../Frameworks' if is_executable else '@loader_path/' + os.path.relpath(self.frameworks, os.path.dirname(path))
        # Keep an rpath that is relative and leads to a folder of the bundle (a wheel's own .dylibs); drop the rest. Add ours
        # only for a file that asks for @rpath libraries (a wheel's .so has no room in its header, and needs none).
        good = [r for r in info.rpaths if r.startswith(('@loader_path', '@executable_path'))
                and os.path.isdir(expand_rpath(r, path, self.bundle)) and inside(expand_rpath(r, path, self.bundle), self.bundle)]
        for rpath in info.rpaths:
            if rpath not in good:
                changes += ['-delete_rpath', rpath]
        if any(name.startswith('@rpath/') for name in info.deps) and wanted not in good:
            changes += ['-add_rpath', wanted]
        if info.ident and not info.ident.startswith('@') and is_macho(path):
            rel_name = os.path.relpath(path, self.frameworks) if inside(path, self.frameworks) else os.path.basename(path)
            changes += ['-id', '@rpath/' + rel_name]
        if changes:
            make_writable(path)
            run(['install_name_tool'] + changes + [path])
        if changes or thinned or patched:
            adhoc_sign(path)             # an edited Mach-O is killed on Apple silicon until it is signed again
        return len(changes)

    def exists_via_rpaths(self, path, info, name):
        return resolve_dependency(name, path, info, self.bundle, []) is not None

    def relocate(self, name, path, source):
        """The new name for a dependency that is not an @rpath one: an absolute path or @loader_path/@executable_path link
        into the install tree. The library is copied under Frameworks and named @rpath/<path under lib>."""
        if name.startswith('@executable_path/'):
            base = self.install / 'bin' / 'krita.app' / 'Contents' / 'MacOS'
            target = os.path.normpath(os.path.join(base, name[len('@executable_path/'):]))
        elif name.startswith('@loader_path/'):
            if source is None:
                return None
            target = os.path.normpath(os.path.join(os.path.dirname(source), name[len('@loader_path/'):]))
        else:
            target = os.path.normpath(name)
        rpath_name = self.to_bundle_name(target) if inside(target, self.install) else None
        if rpath_name is None:
            return None
        if self.bring_library(rpath_name):
            return '@rpath/' + rpath_name
        return None

    def rewrite_all(self):
        done = set()
        total = 0
        while True:
            pending = [f for f in macho_files(self.bundle) if f not in done]
            if not pending:
                break
            for path in pending:
                done.add(path)
                total += self.process(path)
        self.log('  %d Mach-O files processed (%d load-command edits)' % (len(done), total))

    def seal_frameworks(self):
        """Sign each framework as a unit (ad hoc), after the files in it: a framework's main binary only verifies once the
        framework's resources are sealed with it."""
        for framework in sorted(self.frameworks.glob('*.framework')) + sorted(self.frameworks.glob('*/*.framework')):
            run(['codesign', '--force', '--sign', '-', '--timestamp=none', framework])

    def build_launcher(self):
        """The packaged launcher has no test hooks and is built for the settings folder of this build."""
        target = self.macos / 'krita'
        run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-arch', self.arch, '-mmacosx-version-min=12',
             '-DSETTINGS_FOLDER="%s"' % settings_folder(self.source), '-o', target, ROOT / 'agent' / 'app-launcher.c'])

    def info_plist(self):
        path = self.contents / 'Info.plist'
        original = self.install / 'bin' / 'krita.app' / 'Contents' / 'Info.plist'
        with open(original, 'rb') as stream:
            plist = plistlib.load(stream)
        plist['CFBundleIdentifier'] = BUNDLE_ID
        plist['CFBundleName'] = 'Krita Agent'
        plist['CFBundleDisplayName'] = 'Krita Agent'
        plist['CFBundleExecutable'] = 'krita'
        plist.update(notices.plist_entries(self.record))
        plist['NSHumanReadableCopyright'] = ('Krita Agent is free software, GPL-3.0-or-later, built from Krita (GPL-2.0-or-later) '
                                             'and the Creative Agent (GPL-3.0). Licences and source: see Resources/LICENSES.')
        # What macOS shows in its access prompts.
        for key, what in (('NSDocumentsFolderUsageDescription', 'Documents'), ('NSDesktopFolderUsageDescription', 'Desktop'),
                          ('NSDownloadsFolderUsageDescription', 'Downloads')):
            plist[key] = 'Krita Agent opens and saves your artwork in your %s folder.' % what
        plist['NSRemovableVolumesUsageDescription'] = 'Krita Agent opens and saves your artwork on removable volumes.'
        with open(path, 'wb') as stream:
            plistlib.dump(plist, stream)
        return plist

    COMPILE_SCRIPT = (
        "import compileall, py_compile, sys\n"
        "def __main__(args):\n"
        "    bundle, folders = args[0], args[1:]\n"
        "    mode = py_compile.PycInvalidationMode.UNCHECKED_HASH\n"
        "    ok = all([compileall.compile_dir(f, quiet=1, workers=1, invalidation_mode=mode, stripdir=bundle,\n"
        "                                     prependdir='/Applications/Krita Agent.app') for f in folders])\n"
        "    sys.stderr.write('compiled-ok\\n' if ok else 'compile-failed\\n')\n")

    def compile_python(self):
        """Write every .pyc now, so Python never writes into the signed bundle (a new file would break the seal). Runs the
        bundle's own interpreter through kritarunner (the framework's python3.13 launcher needs the stripped Python.app), in a
        temporary home, after a first ad-hoc signing (a rewritten Mach-O will not load on arm64 until it is signed). Files are
        hash-based and unchecked: a copy that changes timestamps stays valid."""
        sign_bundle(self.bundle, None, log=lambda *_: None)
        require_runnable(self.bundle)
        ok, message = verify_signature(self.bundle)
        if not ok:
            raise RuntimeError('refusing to run kritarunner: the bundle does not verify (%s)' % message[-300:])
        home = tempfile.mkdtemp(prefix='krita-agent-compile-')
        try:
            stage_helper_script(home, 'compile_bundle', self.COMPILE_SCRIPT, settings_folder(self.source))
            env = {'PATH': '/usr/bin:/bin', 'HOME': home, 'CFFIXED_USER_HOME': home, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONNOUSERSITE': '1'}
            folders = [self.frameworks / 'Python.framework', self.resources / 'krita-python-libs', self.resources / 'krita' / 'pykrita']
            result = subprocess.run([str(self.macos / 'kritarunner'), '-s', 'compile_bundle', str(self.bundle)] + [str(f) for f in folders],
                                    env=env, capture_output=True, text=True, timeout=900)
            if 'compiled-ok' not in result.stderr:
                self.problems.append('compiling the Python files failed: ' + (result.stderr or result.stdout)[-400:])
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def finish_permissions(self):
        for path in self.contents.rglob('*'):
            if path.name == '.DS_Store':
                path.unlink()
        for path in macho_files(self.bundle):
            os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | 0o755)
        for path in self.resources.glob('applications/*.desktop'):
            os.chmod(path, 0o644)
        for path in self.contents.rglob('*'):
            if path.is_symlink() and not path.exists():
                path.unlink()

    def binary_commit(self):
        """The git hash the Krita executable reports (`krita --version`: "krita 6.1.0-prealpha (git 610a23d)"): the commit the
        binaries were really built from, which can be older than the checkout's HEAD when only scripts changed since."""
        require_runnable(self.bundle)
        home = tempfile.mkdtemp(prefix='krita-agent-version-')       # Qt takes CFFIXED_USER_HOME, never $HOME
        env = {'PATH': '/usr/bin:/bin', 'HOME': home, 'CFFIXED_USER_HOME': home, 'QT_QPA_PLATFORM': 'offscreen'}
        try:
            result = subprocess.run([str(self.macos / 'krita-app'), '--version'], capture_output=True, text=True, env=env, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return ''
        finally:
            shutil.rmtree(home, ignore_errors=True)
        match = re.search(r'\(git ([0-9a-f]{7,40})\)', result.stdout)
        return match.group(1) if match else ''

    def provisional_built_from(self):
        """The commit the build's own version header names (_build/libs/version/kritagitversion.h): used to refuse a stale,
        dirty or unpublished build before the copy; the executable's own answer is checked again afterwards."""
        try:
            text = (self.source / '_build' / 'libs' / 'version' / 'kritagitversion.h').read_text()
        except OSError:
            return ''
        match = re.search(r'KRITA_GIT_SHA1_STRING\s+"([0-9a-f]+)"', text)
        return match.group(1) if match else ''

    def make_record(self, built_from):
        opts = self.options
        record, problems = notices.build_record(
            self.source, built_from, ROOT, source_url=opts.get('source_url') or notices.DEFAULT_SOURCE_URL,
            allow_dirty=opts.get('allow_dirty', False), allow_stale=opts.get('allow_stale', False),
            allow_unpublished=opts.get('allow_unpublished', False))
        if opts.get('overlay_plugin'):
            record['notes'].append('plugin taken from the packaging checkout (HEAD %s), not from the install tree' % record['head'][:12])
        if problems:
            raise Refused('; '.join(problems))
        return record

    def package(self):
        self.make_record(self.provisional_built_from())              # refuse early: stale, dirty or unpublished
        self.start()
        self.log('copying executables, resources, plugins, Python ...')
        self.copy_executables()
        self.copy_resources()
        self.overlay_plugin()
        self.copy_plugins()
        self.copy_python()
        self.copy_agent_packages()
        self.copy_release()
        self.log('closing the dependency set and rewriting rpaths ...')
        self.rewrite_all()
        self.seal_frameworks()
        self.build_launcher()
        self.built_from = self.binary_commit()
        try:
            self.record = self.make_record(self.built_from)           # the executable's own answer is the commit
        except Refused:
            shutil.rmtree(self.bundle, ignore_errors=True)
            raise
        self.info_plist()
        write_notices(self)
        self.compile_python()
        self.finish_permissions()
        return self.problems

    def copy_release(self):
        """The Node companion of a release (krita-creative-agent/scripts/build-release.py): pure JS, JSON and wasm, copied to
        Resources/creative-agent-bundle/{companion,release-manifest.json,bundle-info.json}. The plugin copies it to the user's folder on first use
        (kritamcp/bundled_release.py). Node itself is not shipped: the panel fetches the pinned, SHA-256 verified one once."""
        self.release_info = None
        release = self.release
        scratch = None
        if release is None:
            scratch = Path(tempfile.mkdtemp(prefix='krita-agent-release-'))
            release = scratch / 'release'
            script = ROOT / 'creative-agent' / 'krita-creative-agent' / 'scripts' / 'build-release.py'
            if not (script.parent.parent / 'node_modules').is_dir():
                shutil.rmtree(scratch, ignore_errors=True)
                raise Refused('no release given and creative-agent/krita-creative-agent has no node_modules: run npm ci there, or '
                              'build a release with scripts/build-release.py and pass --release')
            self.log('building the companion release (build-release.py) ...')
            result = subprocess.run(['/usr/bin/python3', str(script), '--output', str(release)], capture_output=True, text=True,
                                    cwd=str(script.parent.parent), env={'PATH': '/usr/bin:/bin:/opt/homebrew/bin', 'HOME': os.environ.get('HOME', '')})
            if result.returncode != 0:
                shutil.rmtree(scratch, ignore_errors=True)
                raise Refused('build-release.py failed: %s' % (result.stderr or result.stdout).strip()[-500:])
        try:
            if not (release / 'release-manifest.json').is_file() or not (release / 'companion').is_dir():
                raise Refused('%s is not a release (no release-manifest.json and companion/)' % release)
            target = self.resources / 'creative-agent-bundle'
            target.mkdir(parents=True)
            self.copy_tree(release / 'companion', target / 'companion', symlinks=False)
            shutil.copy2(release / 'release-manifest.json', target / 'release-manifest.json')
            # When this app was built: an older app opened after a newer one must not move the user's config back (bundled_release.py).
            (target / 'bundle-info.json').write_text(json.dumps({'built_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}) + '\n')
            bundled_release = load_bundled_release()
            try:
                manifest = bundled_release.verify_companion(target)
            except bundled_release.BundledReleaseError as error:
                raise Refused('the release does not match its manifest: %s' % error)
            # The plugin reports its build from build-info.json beside its code, and the companion refuses a bridge whose build_id
            # differs: the app's plugin (installed from the build, not from the release) must carry the release's build identity.
            plugin = self.resources / 'krita' / 'pykrita' / 'kritamcp'
            if not (plugin / '__init__.py').is_file():
                raise Refused('no plugin at %s to give the release build identity to' % plugin)
            info = {key: value for key, value in manifest.items() if key not in ('files', 'node_runtime', 'dependencies')}
            (plugin / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
            self.release_info = {'build_id': manifest['build_id'], 'version': manifest.get('version', ''),
                                 'node': (manifest.get('node_runtime') or {}).get('version', '')}
        finally:
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)


def load_bundled_release():
    """The plugin's own bundled_release module: the packager checks the companion with the code that will check it on first use."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('bundled_release_for_packaging',
                                                  ROOT / 'creative-agent' / 'krita-mcp' / 'krita-plugin' / 'kritamcp' / 'bundled_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------------------------------------- notices, build

def read_licence_text(path):
    try:
        return Path(path).read_text(errors='replace')
    except OSError:
        return ''


def write_notices(packager):
    """Resources/LICENSES (README, third-party notices, licence texts) and Resources/BUILD.txt, all derived from the record
    and from what is shipped."""
    record = packager.record
    licences = packager.resources / 'LICENSES'
    licences.mkdir(parents=True, exist_ok=True)
    for text in sorted((ROOT / 'LICENSES').glob('*.txt')):
        if 'Commercial' in text.name:
            continue                      # a licence we do not use
        shutil.copy2(text, licences / text.name)
    for name, target in (('COPYING', 'COPYING-Krita'), ('AUTHORS', 'AUTHORS-Krita')):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, licences / target)
    for name in ('credits.txt', 'developers.txt', 'libraries.txt'):
        source = ROOT / 'krita' / 'data' / 'aboutdata' / name
        if source.exists():
            shutil.copy2(source, licences / ('Krita-' + name))
    for name, target in (('creative-agent/krita-mcp/LICENSE', 'Creative-Agent-plugin-LICENSE'),
                         ('creative-agent/krita-creative-agent/LICENSE', 'Creative-Agent-companion-LICENSE')):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, licences / target)

    vendor_root = next(iter((packager.resources / 'krita' / 'pykrita' / 'kritamcp' / '_vendor').glob('*')), None)
    wheels = notices.python_package_notices(vendor_root) if vendor_root else []
    for name, version, licence, files, carried in wheels:
        folder = licences / 'python-packages' / name
        for file in files:
            target = folder / file.relative_to(next(p for p in file.parents if p.name.endswith('.dist-info')).parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    # The licence files that sit inside the package folders (opencv's LICENSE-3RD-PARTY.txt, numpy's bundled licences).
    if vendor_root:
        for pattern in ('*/LICENSE*', '*/LICENSES_bundled*', '*/*/LICENSE*', '*/*/LICENSES_bundled*'):
            for file in vendor_root.glob(pattern):
                if file.is_file() and '.dist-info' not in str(file):
                    target = licences / 'python-packages' / 'in-package' / file.relative_to(vendor_root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)

    companion_licences = packager.resources / 'creative-agent-bundle' / 'companion' / 'THIRD_PARTY_LICENSES.txt'
    if companion_licences.is_file():
        shutil.copy2(companion_licences, licences / 'Creative-Agent-companion-THIRD-PARTY-LICENSES.txt')
    statement = notices.source_statement(record)
    extra = ('\nTHIS BUILD: ' + '; '.join(record['notes']) + '\n') if record['notes'] else ''
    readme = f"""Krita Agent {record['commit'][:12]}
=====================================================================================================

Krita Agent is a fork of Krita (https://krita.org) with the Creative Agent built in. It is free software, distributed
under the GNU General Public License, version 3 or (at your option) any later version (GPL-3.0-or-later). It is a
combined work: Krita is GPL-2.0-or-later (libraries LGPL-2.0-or-later), the Creative Agent is GPL-3.0, and the work
as a whole is distributed under the GPL-3.0-or-later. You may use, study, change and share it under those terms.
There is NO WARRANTY, to the extent permitted by law.
{extra}
CORRESPONDING SOURCE
  This application was built from {statement}.
  That public repository carries the fork's complete source tree at that commit: Krita's tree at its base commit plus
  every change we made, replayed onto the published main line. It is the corresponding source of this application and of
  the Creative Agent. The commit is also recorded in the application (Info.plist KritaAgentBuild / KritaAgentPublicCommit
  and Resources/BUILD.txt) and shown in the About box.
  The libraries listed in THIRD-PARTY-NOTICES.txt are separate projects: that file gives each one's licence and where its
  source is. If something there is hard to find, ask in the repository's issue tracker and we will point to or provide it.

YOUR PAINTINGS
  The assistant saves its paintings in ~/Library/Application Support/KritaAgent/paintings by default (a place macOS does not
  ask about). To use another folder, change "paintings_dir" (and "project_root") in
  ~/Library/Application Support/KritaAgent/creative-agent-config.json; an update of the app keeps what you set there.

WHAT IS INSIDE (THIRD-PARTY-NOTICES.txt has every component and its licence)
  Krita Agent                GPL-3.0-or-later   (Krita GPL-2.0-or-later, libraries LGPL-2.0-or-later)
  Creative Agent plugin      GPL-3.0            (Resources/krita/pykrita/kritamcp)
  Vendored Python packages   {', '.join('%s (%s)' % (n, l) for n, v, l, f, c in wheels)}
  Creative Agent companion   GPL-3.0 (JavaScript bundle in Resources/creative-agent; its npm packages: Creative-Agent-companion-THIRD-PARTY-LICENSES.txt)
  Qt 6, KDE Frameworks 6, Python, PyQt6, FFmpeg and the libraries Krita itself ships
  Full licence texts: the *.txt files in this folder.
"""
    (licences / 'README.txt').write_text(readme)

    qt = notices.qt_notice(packager.frameworks, packager.source, record)
    lines = ['THIRD-PARTY NOTICES for Krita Agent %s' % record['commit'][:12], '=' * 100, '',
             'Krita Agent (this application): GPL-3.0-or-later (GPL-3.0-or-later.txt).',
             'Krita: GPL-2.0-or-later with libraries under LGPL-2.0-or-later; credits in Krita-credits.txt and Krita-developers.txt',
             '  (upstream\'s own notice files, unchanged); source files carry SPDX licence lines and the texts are in this folder.',
             'Creative Agent (plugin kritamcp, companion, native helper): GPL-3.0 (Creative-Agent-plugin-LICENSE).', '',
             'Vendored Python packages (Resources/krita/pykrita/kritamcp/_vendor), licence expressions from their metadata:']
    for name, version, licence, files, carried in wheels:
        lines.append('  %s %s: %s' % (name, version, licence))
        lines.append('    licence files: %s' % (', '.join('python-packages/%s/%s' % (name, f.name) for f in files) or 'none in the wheel'))
        if carried:
            lines.append('    libraries the wheel carries (their licences; the wheel\'s own files above and below are the authority):')
            for relative in carried:
                lines.append('      %-52s %s' % (relative, wheel_library_licence_for(vendor_root, relative)))
    lines.append('  (python-packages/in-package/ holds licence files found inside the package folders, e.g. cv2/LICENSE-3RD-PARTY.txt.)')
    cv2_dylibs = sorted((vendor_root / 'cv2' / '.dylibs').glob('libavutil*')) if vendor_root else []
    if cv2_dylibs:
        lines += [''] + notices.ffmpeg_notice(cv2_dylibs[0], 'FFmpeg inside the OpenCV wheel (cv2/.dylibs)', recipe='the wheel is built by the OpenCV project from Homebrew\'s libraries.')
    if packager.release_info:
        lines += ['', 'Creative Agent companion %s (build %s, Resources/creative-agent-bundle): GPL-3.0 (Creative-Agent-companion-LICENSE). It is JavaScript'
                  % (packager.release_info['version'], packager.release_info['build_id'][:12]),
                  '  bundled with esbuild; the licence texts of every npm package in it are in Creative-Agent-companion-THIRD-PARTY-LICENSES.txt.',
                  '  Pyodide (MPL-2.0) and the wheels it loads (numpy BSD-3-Clause, Pillow HPND) are inside; Node.js %s (MIT, https://nodejs.org) is not shipped:'
                  % (packager.release_info['node'] or ''),
                  '  the panel downloads the official archive once and verifies its SHA-256 before using it.']
    lines += ['', 'Libraries Krita ships (upstream\'s list, krita/data/aboutdata/libraries.txt: name, project address, licence):']
    libraries_txt = ROOT / 'krita' / 'data' / 'aboutdata' / 'libraries.txt'
    lines += ['  ' + line for line in (libraries_txt.read_text().splitlines() if libraries_txt.exists() else [])]
    avutil = sorted(packager.frameworks.glob('libavutil.*.dylib'))
    lines += [''] + (notices.ffmpeg_notice(avutil[0]) if avutil else ['FFmpeg: not shipped'])
    lines += [''] + qt
    lines += ['', 'KDE Frameworks 6: LGPL-2.0-or-later / LGPL-2.1-or-later and compatible, https://invent.kde.org/frameworks .',
              'Python: PSF License, https://www.python.org . PyQt6 and PyQt6-sip (Riverbank): GPL-3.0, https://www.riverbankcomputing.com/ .',
              '', 'Every native library in Contents/Frameworks (file names; versions are in the names):']
    lines += ['  ' + name for name in sorted({p.name for p in packager.frameworks.iterdir() if not p.is_symlink()})]
    lines += ['', 'Source for any library above: its project address, or ' + statement + ' for the build recipes.']
    (licences / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(lines) + '\n')

    (packager.resources / 'BUILD.txt').write_text(notices.record_text(record))


def wheel_library_licence_for(vendor_root, relative):
    return notices.wheel_library_licence(Path(relative).name)


# ------------------------------------------------------------------------------------------------------------- signing

NESTED_SUFFIXES = ('.framework', '.app', '.xpc', '.plugin')


def nested_bundle_parts(path, top):
    """The nested bundle directories a file lives in, outermost first (the top bundle itself is not one)."""
    relative = Path(path).relative_to(top).parts
    found = []
    for index, part in enumerate(relative[:-1]):
        if part.endswith(NESTED_SUFFIXES):
            found.append(str(Path(top).joinpath(*relative[:index + 1])))
    return found


def signing_groups(files, top):
    """{owner: [files]}: files in the same outermost nested bundle share an owner (signed serially); a loose file owns itself."""
    groups = {}
    for f in files:
        nested = nested_bundle_parts(f, top)
        groups.setdefault(nested[0] if nested else f, []).append(f)
    return groups


def nested_bundles(files, top):
    """Every nested bundle directory that holds a Mach-O file, innermost (deepest) first: the order they are sealed in."""
    found = {d for f in files for d in nested_bundle_parts(f, top)}
    return sorted(found, key=lambda d: -d.count(os.sep))


def sign_bundle(bundle, identity=None, entitlements=None, log=print):
    """Sign `bundle` inside-out. `identity` is a keychain identity name; None signs ad hoc ("-"). A named identity also
    turns on the hardened runtime (the entitlements then matter); ad-hoc signing does not."""
    bundle = Path(bundle)
    if identity and not identity_available(identity):
        raise RuntimeError('signing identity %r is not in the keychain (security find-identity -p codesigning); nothing was signed'
                           % identity)
    identity_arg = identity or '-'
    entitlements = entitlements or (ROOT / 'packaging' / 'macos' / 'entitlements.plist')
    base = ['codesign', '--force', '--sign', identity_arg, '--timestamp=none']
    if identity:
        base += ['--options', 'runtime']
    with_entitlements = base + ['--entitlements', str(entitlements)]
    files = macho_files(bundle)
    macos = bundle / 'Contents' / 'MacOS'
    main_executable = str(macos / 'krita')

    def sign_one(path):
        # Entitlements belong to executables (MacOS/, a framework's bin/); libraries and plugins take the process's.
        executable = os.path.dirname(path) == str(macos) or os.sep + 'bin' + os.sep in path
        command = list(with_entitlements if executable else base)
        if os.path.dirname(path) == str(macos) and os.path.basename(path) == 'krita-app':
            command += ['--identifier', BUNDLE_ID]
        run(command + [path])

    # Files first, in parallel (they do not depend on each other); then the nested bundles; then the app.
    for path in files:
        make_writable(path)
    # Files inside one bundle (framework, app, xpc service, plugin bundle) are signed one after the other: codesign updates the
    # bundle's seal as it signs the files that belong to it, and two at once race ("No such file"). Other files, and different
    # bundles, run in parallel.
    groups = signing_groups([f for f in files if f != main_executable], bundle)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda group: [sign_one(f) for f in group], groups.values()))
    frameworks = nested_bundles(files, bundle)
    for folder in frameworks:
        run(['codesign', '--force', '--sign', identity_arg, '--timestamp=none'] + (['--options', 'runtime'] if identity else []) + [folder])
    run(with_entitlements + ['--identifier', BUNDLE_ID, str(bundle)])
    log('  signed %d files, %d nested bundles and the app (%s)' % (len(files), len(frameworks), identity or 'ad hoc'))


def identity_available(identity):
    """Is `identity` listed among the keychain's code signing identities? (Only reads the list; never changes the keychain.)"""
    listing = subprocess.run(['security', 'find-identity', '-p', 'codesigning'], capture_output=True, text=True).stdout
    return ('"%s"' % identity) in listing


def sign_and_report(bundle, identity, out=print):
    """Sign `bundle`; a missing identity prints ONE line saying what state the bundle is in and returns 1."""
    try:
        sign_bundle(bundle, identity or None)
    except RuntimeError as error:
        out('NOT SIGNED: %s. The bundle %s is left as it was: signed ad hoc by the build step, so it opens and runs, but macOS '
            'will ask again for access to folders after every rebuild.' % (str(error).split(';')[0], bundle))
        return 1
    return 0


def verify_signature(bundle):
    result = subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(bundle)], capture_output=True, text=True)
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def size_report(bundle):
    sizes = []
    for child in sorted(Path(bundle, 'Contents').iterdir()):
        if child.is_symlink():
            continue
        total = sum(f.stat().st_size for f in child.rglob('*') if f.is_file() and not f.is_symlink()) if child.is_dir() else child.stat().st_size
        sizes.append((child.name, total))
    return sizes


# ---------------------------------------------------------------------------------------------- what is written inside the files

GENERIC_MARKS = ('/_install', '/_build')


def reference_marks(extra=()):
    """What must not be written inside the app: the generic build-tree names (_install, _build) and the concrete prefixes of
    this account: the forks folder, the home folder and any path given (the install and source trees). Other people's build
    paths (/Users/runner, /Users/gitlab ...) are theirs."""
    marks = list(GENERIC_MARKS) + [str(ROOT.parent), os.path.expanduser('~')] + [str(e) for e in extra]
    return tuple(m for m in dict.fromkeys(marks) if len(m) > 6)


def concrete_marks(marks):
    return tuple(m for m in marks if m not in GENERIC_MARKS)


# After the prefixes are neutralised (see neutralise_file) what is left is "/build///.../x.cpp" and friends. The rules are
# anchored: the WHOLE string must be a path to a source file, or exactly one of the compile-time constants of Krita's build
# (PYKRITA_PYTHON_LIBRARY, which Python::libraryLoad ignores on macOS, and the version header's build folder).
SOURCE_PATH = re.compile(r'/[\w./+\- ]+\.(c|cc|cpp|cxx|h|hh|hpp|m|mm|inl|ipp|tpp)')
KNOWN_CONSTANTS = (re.compile(r'/build/*/_install/lib/libpython[\d.]+\.dylib'), re.compile(r'/build/*/_build'))
UPSTREAM_CI_PATH = re.compile(r'/Users/gitlab/\S*')                  # the machine upstream's dependencies were built on


def harmless_reference(line, concrete=()):
    """Is this string, which mentions a build tree, harmless? Never when it carries one of this account's concrete prefixes.
    Upstream's CI paths are excused token by token; a bare source-file path or an exact known constant is excused whole."""
    line = line.strip()
    if any(prefix in line for prefix in concrete):
        return False
    if SOURCE_PATH.fullmatch(line) or any(c.fullmatch(line) for c in KNOWN_CONSTANTS):
        return True
    return not any(mark in UPSTREAM_CI_PATH.sub('', line) for mark in GENERIC_MARKS)


def neutral_bytes(length):
    return b'/build' + b'/' * (length - len(b'/build'))


def neutralise_bytes(data, prefixes):
    """`data` with every occurrence of each prefix (longest first) replaced by a neutral path of the same length ("/build////"),
    so nothing moves in the file."""
    for prefix in sorted({str(p) for p in prefixes if p}, key=len, reverse=True):          # Path objects as well as strings
        raw = prefix.encode()
        if len(raw) >= 8 and raw != b'/' and raw in data:
            data = data.replace(raw, neutral_bytes(len(raw)))
    return data


def neutralise_file(path, prefixes):
    """Overwrite the build-tree and home-folder prefixes baked into a Mach-O file (assert and log messages carry the compiler's
    __FILE__, PYKRITA_PYTHON_LIBRARY the path of the build's libpython, the version header the build folder) with a same-length
    neutral path, in place. Returns True if the file changed (and so must be signed again).
    Why that is safe: none of these strings is opened at run time in the packaged app. PYKRITA_PYTHON_LIBRARY is only used on
    Linux (Python::libraryLoad is a no-op on macOS; setPath uses its file name only); the others are only printed. The file's
    layout does not change, so nothing else in the Mach-O moves."""
    with open(path, 'rb') as stream:
        data = stream.read()
    patched = neutralise_bytes(data, prefixes)
    if patched == data:
        return False
    make_writable(path)
    with open(path, 'r+b') as stream:
        stream.write(patched)
    return True


def reference_samples(data, marks):
    """Lines of `data` (bytes) that mention one of `marks` and are not harmless; at most three."""
    found = []
    needles = [m.encode() for m in marks]
    concrete = concrete_marks(marks)
    if not any(n in data for n in needles):
        return found
    for raw in re.split(rb'[\x00\n\r]', data):
        if any(n in raw for n in needles):
            line = raw.decode('utf-8', 'replace')
            if not harmless_reference(line, concrete):
                found.append(line.strip()[:160])
                if len(found) == 3:
                    break
    return found


def reference_problems(bundle, marks=None):
    """The strings of every Mach-O file and the text of every other file mentioning _install, _build, forks/ or a home
    folder, apart from harmless ones (see harmless_reference)."""
    bundle = Path(bundle)
    problems = []
    marks = tuple(marks) if marks is not None else reference_marks()

    def scan(path):
        if is_macho(path):
            out = subprocess.run(['strings', '-a', str(path)], capture_output=True)
            data = out.stdout
        else:
            try:
                if os.path.getsize(path) > 8_000_000:
                    return []
                data = Path(path).read_bytes()
            except OSError:
                return []
        return [(rel(path, bundle), sample) for sample in reference_samples(data, marks)]

    files = [os.path.join(folder, name) for folder, _, names in os.walk(bundle) for name in names
             if not os.path.islink(os.path.join(folder, name))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for hits in pool.map(scan, files):
            problems += ['%s mentions %s' % hit for hit in hits]
    return problems


def symlink_problems(bundle):
    """A symlink in the bundle that leads outside it, or nowhere."""
    problems = []
    real = os.path.realpath(str(bundle))
    for folder, dirs, names in os.walk(bundle, followlinks=False):
        for name in dirs + names:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                target = os.path.realpath(path)
                if not os.path.exists(target):
                    problems.append('%s is a symlink to nothing (%s)' % (rel(path, bundle), os.readlink(path)))
                elif not inside(target, real):
                    problems.append('%s is a symlink out of the bundle (%s)' % (rel(path, bundle), target))
    return problems


# ------------------------------------------------------------------------------------------------------------- smoke test

SMOKE_SCRIPT = (
    "import ctypes, importlib, json, os, sys\n"
    "def __main__(args):\n"
    "    out = {'imports': {}, 'sys_path': list(sys.path)}\n"
    "    for name in ('krita', 'PyQt6.QtCore', 'kritamcp', 'kritamcp.creative_docker', 'numpy', 'cv2', 'psutil', 'xxhash'):\n"
    "        try:\n"
    "            out['imports'][name] = getattr(importlib.import_module(name), '__file__', 'ok')\n"
    "        except BaseException as error:\n"
    "            out['imports'][name] = 'ERROR ' + repr(error)[:200]\n"
    "    import numpy, cv2\n"
    "    out['compute'] = [int(numpy.arange(10).sum()), float(cv2.blur(numpy.ones((8, 8), numpy.uint8) * 3, (3, 3)).mean())]\n"
    "    try:\n"
    "        import glob\n"
    "        lib = ctypes.CDLL(sorted(glob.glob(os.environ['SMOKE_CONTENTS'] + '/Frameworks/libmlt-7*.dylib'))[0])\n"
    "        for name in ('mlt_factory_init', 'mlt_profile_init', 'mlt_factory_producer'):\n"
    "            getattr(lib, name).restype = ctypes.c_void_p\n"
    "        lib.mlt_factory_producer.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]\n"
    "        lib.mlt_profile_init.argtypes = [ctypes.c_char_p]\n"
    "        repository = lib.mlt_factory_init(None)\n"
    "        profile = lib.mlt_profile_init(b'atsc_720p_25')\n"
    "        producer = lib.mlt_factory_producer(profile, b'color', b'red')\n"
    "        out['mlt'] = bool(repository) and bool(profile) and bool(producer)\n"
    "    except BaseException as error:\n"
    "        out['mlt'] = 'ERROR ' + repr(error)[:200]\n"
    "    try:\n"
    "        import kritamcp\n"
    "        from kritamcp import bundled_release as br\n"
    "        home = os.environ['SMOKE_HOME']\n"
    "        bundled = br.bundled_dir(os.path.dirname(kritamcp.__file__))\n"
    "        config = br.ensure_installed(bundled, home + '/AppData', home + '/runtimes', home + '/node') if bundled else None\n"
    "        settings = json.load(open(config)) if config else {}\n"
    "        out['companion'] = bool(settings) and os.path.isfile(settings['companion']) and settings['companion'].startswith(home)\n"
    "    except BaseException as error:\n"
    "        out['companion'] = 'ERROR ' + repr(error)[:200]\n"
    "    open(os.environ['SMOKE_OUT'], 'w').write(json.dumps(out))\n")


def sandbox_profile(deny):
    """A sandbox-exec profile that allows everything except reading or writing the given trees."""
    lines = ['(version 1)', '(allow default)']
    for path in sorted({str(Path(p).resolve()) for p in deny if p} | {str(p) for p in deny if p}):
        lines.append('(deny file-read* file-write* (subpath "%s"))' % path.replace('\\', '\\\\').replace('"', '\\"'))
    return '\n'.join(lines) + '\n'


def smoke_test(bundle, log=print, deny=(), settings=None):
    """Run the bundle's own Python headless (kritarunner) from a TEMPORARY COPY, in a clean environment (env -i), with the
    launcher's environment variables, a temporary home (Qt takes CFFIXED_USER_HOME, never $HOME) and, with `deny`, the build,
    install and source trees made unreadable (sandbox-exec). It imports krita, PyQt6, kritamcp, numpy, cv2, psutil and xxhash,
    starts MLT's factory and creates a producer, and fails on any sys.path entry outside the copy or the temporary home.
    Refuses (RuntimeError) if the bundle does not verify: nothing is executed from a bad signature. Returns the problems."""
    import json
    bundle = Path(bundle)
    ok, message = verify_signature(bundle)
    if not ok:
        raise RuntimeError('refusing to run: %s does not verify (%s)' % (bundle, message[-300:]))
    require_runnable(bundle)
    work = Path(tempfile.mkdtemp(prefix='krita-agent-smoke-'))
    try:
        copy = work / APP_NAME
        run(['/usr/bin/ditto', bundle, copy])
        require_runnable(copy)
        home = work / 'home'
        home.mkdir(parents=True)
        stage_helper_script(home, 'smoke_bundle', SMOKE_SCRIPT, settings or SETTINGS_FOLDER)
        poison = work / 'poisoned-pythonpath'                   # a PYTHONPATH the bundled Python must ignore
        poison.mkdir()
        result_file = home / 'result.json'
        contents = copy / 'Contents'
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'CFFIXED_USER_HOME': str(home), 'QT_QPA_PLATFORM': 'offscreen',
               'PYTHONPATH': str(poison), 'SMOKE_OUT': str(result_file), 'SMOKE_CONTENTS': str(contents), 'SMOKE_HOME': str(home)}
        env.update(launcher_environment(contents.resolve()))
        command = [str(contents / 'MacOS/kritarunner'), '-s', 'smoke_bundle']
        denied = [d for d in deny if d and os.path.exists(d)]
        if denied and os.path.exists('/usr/bin/sandbox-exec'):
            profile = work / 'deny.sb'
            profile.write_text(sandbox_profile(denied))
            command = ['/usr/bin/sandbox-exec', '-f', str(profile)] + command
        elif denied:
            log('  smoke: sandbox-exec is missing, the build trees were not made unreadable')
        run_result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=600)
        try:
            found = json.loads(result_file.read_text())
        except (OSError, ValueError):
            return ['kritarunner produced no result (exit %d): %s' % (run_result.returncode, run_result.stderr[-300:])]
        problems = []
        for name, value in found['imports'].items():
            if str(value).startswith('ERROR'):
                problems.append('%s: %s' % (name, value))
            elif str(value).startswith('/') and not inside(os.path.realpath(str(value)), os.path.realpath(copy)):
                problems.append('%s was imported from outside the bundle: %s' % (name, value))
        problems += sys_path_problems(found['sys_path'], copy, home, poison)
        if found.get('compute') != [45, 3.0]:
            problems.append('numpy/OpenCV computed %r' % (found.get('compute'),))
        if found.get('companion') is not True:
            problems.append('the bundled companion could not be verified and copied out on first use: %r' % (found.get('companion'),))
        if found.get('mlt') is not True:
            problems.append('MLT factory init / producer failed: %r' % (found.get('mlt'),))
        shown = [e.replace(str(copy.resolve()), '<app>').replace(str(copy), '<app>').replace(str(home.resolve()), '<temp home>').replace(str(home), '<temp home>')
                 for e in found['sys_path']]
        log('  sys.path of the bundled Python:\n    ' + '\n    '.join(shown))
        log('  smoke: %s; MLT %s; companion first-use copy %s; sys.path has %d entries%s' % (', '.join(sorted(found['imports'])), 'ok' if found.get('mlt') is True else 'FAILED',
                                                               'ok' if found.get('companion') is True else 'FAILED', len(found['sys_path']), ' (build trees unreadable)' if denied else ''))
        return problems
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------------------------------------------- main

def check_everything(bundle, extra_marks=()):
    return check_bundle(bundle) + layout_problems(bundle) + symlink_problems(bundle) + reference_problems(bundle, reference_marks(extra_marks))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    pack = sub.add_parser('package')
    pack.add_argument('install', nargs='?')
    pack.add_argument('--out', required=True)
    pack.add_argument('--packages', help='a folder with the Python packages for this machine and Python (default: install them with uv)')
    pack.add_argument('--source', help='the git checkout the install was built from (default: the install\'s parent)')
    pack.add_argument('--release', help='a krita-creative-agent release folder (scripts/build-release.py) whose companion goes in the app')
    pack.add_argument('--source-url', default=os.environ.get('KRITA_AGENT_SOURCE_URL'), help='the public repository (default: %s)' % notices.DEFAULT_SOURCE_URL)
    pack.add_argument('--allow-dirty', action='store_true', help='package a tree with uncommitted changes (stamped into the notices)')
    pack.add_argument('--allow-stale-build', action='store_true', help='package a build that is not from the checkout\'s HEAD (stamped)')
    pack.add_argument('--allow-unpublished', action='store_true', help='package a commit that is not in public/main yet (stamped)')
    pack.add_argument('--overlay-plugin', help='use this checkout\'s plugin folder (kritamcp) instead of the installed one (stamped)')
    pack.add_argument('--no-sign', action='store_true')
    check = sub.add_parser('check')
    check.add_argument('bundle')
    smoke = sub.add_parser('smoke')
    smoke.add_argument('bundle')
    smoke.add_argument('--deny', action='append', default=[], help='a folder to make unreadable during the run (repeatable)')
    signer = sub.add_parser('sign')
    signer.add_argument('bundle')
    args = parser.parse_args(argv)

    if args.command == 'check':
        problems = check_everything(args.bundle)
        for problem in problems:
            print('PROBLEM', problem)
        print('%d Mach-O files checked, %d problems' % (len(macho_files(args.bundle)), len(problems)))
        return 1 if problems else 0
    if args.command == 'smoke':
        try:
            problems = smoke_test(args.bundle, deny=args.deny)
        except RuntimeError as error:
            print('REFUSED', error)
            return 3
        for problem in problems:
            print('PROBLEM', problem)
        print('smoke test: %d problems' % len(problems))
        return 1 if problems else 0
    if args.command == 'sign':
        status = sign_and_report(args.bundle, os.environ.get('KRITA_AGENT_SIGN_IDENTITY'))
        if status == 0:
            ok, message = verify_signature(args.bundle)
            print(message)
            return 0 if ok else 1
        return status

    install = Path(args.install or ROOT.parent / 'krita-master' / '_install')
    if not (install / 'bin' / 'krita.app').is_dir():
        print('no krita.app in %s/bin: build first (agent/build-macos.sh)' % install, file=sys.stderr)
        return 2
    source = Path(args.source) if args.source else install.parent
    try:
        check_output_folder(args.out, install, source)
        Path(args.out).mkdir(parents=True, exist_ok=True)
        options = {'allow_dirty': args.allow_dirty, 'allow_stale': args.allow_stale_build,
                   'allow_unpublished': args.allow_unpublished, 'source_url': args.source_url,
                   'overlay_plugin': args.overlay_plugin}
        packager = Packager(install, args.out, args.packages, source, options=options, release=args.release)
        print('Packaging %s' % install)
        problems = packager.package()
    except Refused as error:
        print('REFUSED:', error, file=sys.stderr)
        return 2
    print('commit %s (public %s)%s' % (packager.record['commit'][:12], packager.record['public_commit'][:12] if len(packager.record['public_commit']) == 40 else 'not published',
                                       ' [%s]' % '; '.join(packager.record['notes']) if packager.record['notes'] else ''))
    for problem in problems:
        print('PROBLEM', problem)
    if not args.no_sign:
        print('signing ...')
        if sign_and_report(packager.bundle, os.environ.get('KRITA_AGENT_SIGN_IDENTITY')):
            return 1
        ok, message = verify_signature(packager.bundle)
        print('codesign --verify --deep --strict:', 'ok' if ok else 'FAILED ' + message[-300:])
        found = [] if ok else ['signature does not verify']
        found += check_everything(packager.bundle, [install, source])
        if ok:
            found += smoke_test(packager.bundle, deny=[install, source, ROOT.parent], settings=settings_folder(source))
        for problem in found:
            print('PROBLEM', problem)
        problems = problems + found
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
