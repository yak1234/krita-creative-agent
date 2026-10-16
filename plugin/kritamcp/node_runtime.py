"""Managed Node runtime, fetched on first use and shared by every release (like uv's Python).

A release pins `{"version": "22.23.2", "archives": {"darwin-arm64": {"file": ..., "sha256": ...}, ...}}`.
`ensure()` downloads the official nodejs.org archive once, refuses it unless the SHA-256
matches, unpacks it under runtimes/node-v<version>-<platform>/ and returns bin/node.
Standard library only: this runs inside Krita's Python, in install.py and in build-release.py.
"""
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

DIST = 'https://nodejs.org/dist'
OVERRIDE = 'CREATIVE_AGENT_NODE'        # a developer's own Node 22+, bypassing the managed runtime
MARKER = '.creative-agent-verified'


# Krita's bundled Python has no CA bundle (urllib fails with CERTIFICATE_VERIFY_FAILED); macOS curl
# trusts the system keychain. The archive is verified by SHA-256 either way.
CURL = '/usr/bin/curl'


def download_with_curl(url, target, progress=None):
    import time
    # Use the system trust store even if the host process points these at an unusable bundle.
    env = {k: v for k, v in os.environ.items() if k not in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE')}
    process = subprocess.Popen([CURL, '--fail', '--silent', '--show-error', '--location', '--max-time', '600', '--output', str(target), url],
                               stderr=subprocess.PIPE, env=env)
    while process.poll() is None:
        if progress and target.exists(): progress(target.stat().st_size, 0)
        time.sleep(0.25)
    if process.returncode:
        raise ValueError('The Node runtime could not be downloaded: ' + process.stderr.read().decode(errors='replace').strip()[-300:])
    if progress: progress(target.stat().st_size, target.stat().st_size)


def default_root():
    return Path.home() / 'Library' / 'Application Support' / 'Creative Agent' / 'runtimes'


def platform_key(system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'amd64': 'x64'}.get((machine or platform.machine()).lower())
    if system != 'darwin' or not machine:
        raise ValueError('The managed Node runtime supports macOS on Apple silicon or Intel.')
    return 'darwin-' + machine


def runtime_dir(spec, root=None, key=None):
    return Path(root or default_root()) / ('node-v%s-%s' % (spec['version'], key or platform_key()))


def node_path(spec, root=None, key=None):
    return runtime_dir(spec, root, key) / 'bin' / 'node'


def is_ready(spec, root=None, key=None):
    """True when the pinned runtime is unpacked and was verified against this archive hash."""
    key = key or platform_key()
    directory = runtime_dir(spec, root, key)
    try:
        return (directory / 'bin' / 'node').is_file() and (directory / MARKER).read_text().strip() == spec['archives'][key]['sha256']
    except (OSError, KeyError):
        return False


def resolve(spec, root=None):
    """The node to run: the override if set, else the managed path (which may not exist yet)."""
    override = os.environ.get(OVERRIDE)
    if override:
        return Path(override)
    return node_path(spec, root)


def ensure(spec, root=None, progress=None, opener=None, base_url=DIST, key=None):
    """Return bin/node for `spec`, downloading and verifying it first if needed.

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
        if opener is None and Path(CURL).is_file():
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
        # The archive is the verified official build, so the system tar may unpack it (it keeps npm's symlinks).
        subprocess.run(['/usr/bin/tar', '-xzf', str(target), '-C', str(work)], check=True, capture_output=True)
        unpacked = work / ('node-v%s-%s' % (spec['version'], key))
        if not (unpacked / 'bin' / 'node').is_file():
            raise ValueError('The Node archive did not contain bin/node.')
        (unpacked / MARKER).write_text(archive['sha256'] + '\n')
        destination = runtime_dir(spec, root, key)
        if destination.exists():
            shutil.rmtree(destination)          # an unverified or damaged earlier attempt
        unpacked.rename(destination)
        return destination / 'bin' / 'node'
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


def spec_from_shasums(version, shasums_text, keys=('darwin-arm64', 'darwin-x64')):
    """Build a release spec from nodejs.org's SHASUMS256.txt for `version`."""
    sums = {}
    for line in shasums_text.splitlines():
        parts = line.split()
        if len(parts) == 2: sums[parts[1]] = parts[0]
    archives = {}
    for key in keys:
        name = 'node-v%s-%s.tar.gz' % (version, key)
        if name not in sums: raise ValueError('SHASUMS256.txt has no ' + name)
        archives[key] = {'file': name, 'sha256': sums[name]}
    return {'version': version, 'archives': archives}


def fetch_spec(version, opener=None, base_url=DIST):
    with (opener or urllib.request.urlopen)('%s/v%s/SHASUMS256.txt' % (base_url, version), timeout=30) as response:
        return spec_from_shasums(version, response.read().decode())
