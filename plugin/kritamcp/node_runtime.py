"""Managed Node runtime, fetched on first use and shared by every release (like uv's Python).

A release pins `{"version": "22.23.2", "archives": {"darwin-arm64": {"file": ..., "sha256": ...}, ...}}`,
keyed by nodejs.org's own platform names (darwin-, linux-, win- with x64 or arm64).
`ensure()` downloads the official archive once (.tar.gz on macOS, .tar.xz on Linux, .zip on
Windows), refuses it unless the SHA-256 matches, unpacks it under
runtimes/node-v<version>-<key>/ and returns its node (bin/node, or node.exe on Windows).
Standard library only: this runs inside Krita's Python, in install.py and in build-release.py.
"""
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DIST = 'https://nodejs.org/dist'
OVERRIDE = 'CREATIVE_AGENT_NODE'        # a developer's own Node 22+, bypassing the managed runtime
MARKER = '.creative-agent-verified'


KEYS = ('darwin-arm64', 'darwin-x64', 'linux-arm64', 'linux-x64', 'win-arm64', 'win-x64')
EXTENSIONS = {'darwin': '.tar.gz', 'linux': '.tar.xz', 'win': '.zip'}


def find_curl():
    # Krita's bundled Python has no CA bundle (urllib fails with CERTIFICATE_VERIFY_FAILED). The system
    # curl trusts the system store: the keychain on macOS, Schannel on Windows 10+ (System32\curl.exe).
    # The archive is verified by SHA-256 either way; without curl, urllib is tried.
    if os.name == 'nt':
        bundled = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'curl.exe'
        return str(bundled) if bundled.is_file() else None
    return '/usr/bin/curl' if Path('/usr/bin/curl').is_file() else shutil.which('curl')


CURL = find_curl()


def download_with_curl(url, target, progress=None):
    import time
    # Use the system trust store even if the host process points these at an unusable bundle.
    env = {k: v for k, v in os.environ.items() if k not in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE')}
    with subprocess.Popen([CURL, '--fail', '--silent', '--show-error', '--location', '--max-time', '600', '--output', str(target), url],
                          stderr=subprocess.PIPE, env=env) as process:
        while process.poll() is None:
            if progress and target.exists(): progress(target.stat().st_size, 0)
            time.sleep(0.25)
        error = process.stderr.read().decode(errors='replace').strip()[-300:]
    if process.returncode:
        raise ValueError('The Node runtime could not be downloaded: ' + error)
    if progress: progress(target.stat().st_size, target.stat().st_size)


def default_root(system=None, environ=None, home=None):
    """Per-user app data, beside the installer's releases folder: one shared runtime per Node version."""
    system, environ, home = (system or platform.system()).lower(), os.environ if environ is None else environ, Path(home or Path.home())
    if system == 'windows':
        return Path(environ.get('LOCALAPPDATA') or home / 'AppData' / 'Local') / 'Creative Agent' / 'runtimes'
    if system == 'linux':
        return Path(environ.get('XDG_DATA_HOME') or home / '.local' / 'share') / 'creative-agent' / 'runtimes'
    return home / 'Library' / 'Application Support' / 'Creative Agent' / 'runtimes'


def platform_key(system=None, machine=None):
    """nodejs.org's name for this platform, such as darwin-arm64, linux-x64 or win-x64."""
    system = {'darwin': 'darwin', 'linux': 'linux', 'windows': 'win'}.get((system or platform.system()).lower())
    machine = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'amd64': 'x64'}.get((machine or platform.machine()).lower())
    if not system or not machine:
        raise ValueError('The managed Node runtime supports macOS, Windows and Linux on 64-bit Intel/AMD or ARM.')
    return system + '-' + machine


def archive_name(version, key):
    return 'node-v%s-%s%s' % (version, key, EXTENSIONS[key.split('-')[0]])


def runtime_dir(spec, root=None, key=None):
    return Path(root or default_root()) / ('node-v%s-%s' % (spec['version'], key or platform_key()))


def executable(key):
    """Where node sits inside an unpacked archive: Windows zips keep node.exe at the top."""
    return Path('node.exe') if key.startswith('win-') else Path('bin') / 'node'


def node_path(spec, root=None, key=None):
    key = key or platform_key()
    return runtime_dir(spec, root, key) / executable(key)


def is_ready(spec, root=None, key=None):
    """True when the pinned runtime is unpacked and was verified against this archive hash."""
    key = key or platform_key()
    directory = runtime_dir(spec, root, key)
    try:
        return (directory / executable(key)).is_file() and (directory / MARKER).read_text().strip() == spec['archives'][key]['sha256']
    except (OSError, KeyError):
        return False


def unpack(archive, directory):
    """Unpack a verified official archive. A zip (Windows) needs no system tool; a tarball uses the
    system tar, which keeps npm's symlinks and detects gzip or xz itself, and falls back to tarfile."""
    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if member.startswith(('/', '\\')) or '..' in Path(member).parts:
                    raise ValueError('The Node archive contains an unsafe path: ' + member)
            bundle.extractall(directory)
        return
    tar = '/usr/bin/tar' if Path('/usr/bin/tar').is_file() else shutil.which('tar')
    if tar:
        subprocess.run([tar, '-xf', str(archive), '-C', str(directory)], check=True, capture_output=True)
        return
    import tarfile
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts or (member.issym() and Path(member.linkname).is_absolute()):
                raise ValueError('The Node archive contains an unsafe path: ' + member.name)
        bundle.extractall(directory)


def resolve(spec, root=None):
    """The node to run: the override if set, else the managed path (which may not exist yet)."""
    override = os.environ.get(OVERRIDE)
    if override:
        return Path(override)
    return node_path(spec, root)


def ensure(spec, root=None, progress=None, opener=None, base_url=DIST, key=None):
    """Return the node executable for `spec`, downloading and verifying it first if needed.

    progress(done_bytes, total_bytes) is called while downloading. Raises ValueError on a
    hash mismatch or an unusable archive; nothing partial is left in place.
    """
    override = os.environ.get(OVERRIDE)
    if override:
        if not Path(override).is_file():
            raise ValueError(OVERRIDE + ' points to a missing file.')
        return Path(override)
    key = key or platform_key()
    root = Path(root or default_root())
    if is_ready(spec, root, key):
        return node_path(spec, root, key)
    archive = spec['archives'].get(key)
    if not archive:
        raise ValueError('This release has no Node runtime for ' + key + '.')
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='.node-', dir=root))
    try:
        target = work / archive['file']
        url = '%s/v%s/%s' % (base_url, spec['version'], archive['file'])
        if opener is None and CURL and Path(CURL).is_file():
            download_with_curl(url, target, progress)
        else:
            with (opener or urllib.request.urlopen)(url, timeout=60) as response, target.open('wb') as stream:
                total, done = int(response.headers.get('Content-Length') or 0), 0
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    stream.write(block); done += len(block)
                    if progress: progress(done, total)
        checksum = hashlib.sha256()
        with target.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''): checksum.update(block)
        if checksum.hexdigest() != archive['sha256']:
            raise ValueError('The downloaded Node runtime does not match its pinned checksum; it was discarded.')
        unpack(target, work)
        unpacked = work / ('node-v%s-%s' % (spec['version'], key))
        if not (unpacked / executable(key)).is_file():
            raise ValueError('The Node archive did not contain ' + executable(key).as_posix() + '.')
        (unpacked / MARKER).write_text(archive['sha256'] + '\n')
        destination = runtime_dir(spec, root, key)
        if destination.exists():
            shutil.rmtree(destination)          # an unverified or damaged earlier attempt
        unpacked.rename(destination)
        return destination / executable(key)
    except subprocess.CalledProcessError as error:
        raise ValueError('The Node archive could not be unpacked: ' + (error.stderr or b'').decode(errors='replace')[-300:])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def prune(keep_versions, root=None):
    """Remove managed runtimes whose version no installed release still pins."""
    root = Path(root or default_root())
    removed = []
    for directory in (root.iterdir() if root.is_dir() else []):
        if directory.is_dir() and directory.name.startswith('node-v'):
            version = directory.name[len('node-v'):].rsplit('-', 2)[0]
            if version not in keep_versions:
                shutil.rmtree(directory, ignore_errors=True); removed.append(directory.name)
    return removed


def spec_from_shasums(version, shasums_text, keys=KEYS):
    """Build a release spec from nodejs.org's SHASUMS256.txt for `version`."""
    sums = {}
    for line in shasums_text.splitlines():
        parts = line.split()
        if len(parts) == 2: sums[parts[1]] = parts[0]
    archives = {}
    for key in keys:
        name = archive_name(version, key)
        if name not in sums: raise ValueError('SHASUMS256.txt has no ' + name)
        archives[key] = {'file': name, 'sha256': sums[name]}
    return {'version': version, 'archives': archives}


def fetch_spec(version, opener=None, base_url=DIST):
    with (opener or urllib.request.urlopen)('%s/v%s/SHASUMS256.txt' % (base_url, version), timeout=30) as response:
        return spec_from_shasums(version, response.read().decode())
