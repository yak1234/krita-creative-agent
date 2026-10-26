"""Build a Mac release from pinned installed packages. Node is not bundled: the release pins an official
Node version and its archive checksums, and the panel fetches that runtime once (plugin/kritamcp/node_runtime.py)."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = '22.23.2'


def runtime_module(plugin):
    spec = importlib.util.spec_from_file_location('node_runtime', Path(plugin) / 'kritamcp' / 'node_runtime.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def hash_file(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): checksum.update(block)
    return checksum.hexdigest()


def inventory(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink(): raise ValueError('Release contains a symlink: ' + str(path.relative_to(directory)))
        if path.is_file(): result[str(path.relative_to(directory))] = hash_file(path)
    return result


def verify_node(node):
    details = json.loads(subprocess.check_output([str(node), '-p', 'JSON.stringify({platform:process.platform,architecture:process.arch,node:process.version})'], text=True))
    if details['platform'] != 'darwin' or details['architecture'] not in ('arm64', 'x64'):
        raise ValueError('Provide a standalone macOS Node runtime for this architecture.')
    if int(details['node'].lstrip('v').split('.')[0]) < 22: raise ValueError('Node 22 or newer is required.')
    libraries = subprocess.check_output(['/usr/bin/otool', '-L', str(node)], text=True).splitlines()[1:]
    for library in libraries:
        dependency = library.strip().split(' (', 1)[0]
        if not dependency.startswith(('/usr/lib/', '/System/Library/')):
            raise ValueError('Node depends on a non-system library; use an official standalone distribution: ' + dependency)
    return details


BANNER = ("import { createRequire as __cr } from 'node:module'; import { fileURLToPath as __fu } from 'node:url'; "
          "import { dirname as __dn, join as __jn } from 'node:path'; const require = __cr(import.meta.url); "
          # CommonJS code in the bundle reads __dirname, which ES modules lack: Photon loads photon_rs_bg.wasm
          # from it, so without it every prompt image fails to resize and is dropped.
          "const __dirname = __dn(__fu(import.meta.url)); "
          # Pi finds its package.json (version, templates) through this override when bundled.
          "process.env.PI_PACKAGE_DIR ??= __jn(__dn(__fu(import.meta.url)), '..', 'pi-package');")


def bundle_image_resizing(dependency_root, companion, esbuild, root, pi_ai):
    """Pi decodes and resizes every prompt image (canvas, references, reviews) with Photon, in a worker it
    finds beside the module (./image-resize-worker.js) or in process. A bundle has neither the worker nor
    photon_rs_bg.wasm, so every image would be dropped as "could not be resized": ship both. Pi looks for the
    wasm in the working directory, which the panel sets to companion/src."""
    pi = next((folder / '@earendil-works/pi-coding-agent' for folder in (dependency_root,)
               if (folder / '@earendil-works/pi-coding-agent/dist/utils/image-resize-worker.js').exists()), None)
    wasm = next(iter(sorted(dependency_root.glob('**/@silvia-odwyer/photon-node/photon_rs_bg.wasm'))), None)
    if pi is None or wasm is None: raise ValueError("Pi's image resize worker or Photon's wasm is missing; run npm ci.")
    result = subprocess.run([str(esbuild), str(pi / 'dist/utils/image-resize-worker.js'), '--bundle', '--platform=node', '--format=esm',
                             '--target=node22', '--outfile=' + str(companion / 'src/image-resize-worker.js'), '--log-level=warning',
                             '--legal-comments=none', '--banner:js=' + BANNER],
                            cwd=root, text=True, capture_output=True, env={**os.environ, 'NODE_PATH': str(pi_ai)})
    if result.returncode or 'warning' in result.stderr.lower():
        raise ValueError('Bundling the image resize worker failed or warned: ' + (result.stderr or result.stdout)[-2000:])
    shutil.copy2(wasm, companion / 'src/photon_rs_bg.wasm')


# Packages the bundle leaves outside and loads from node_modules beside it: VTracer (the mass map, guide-masses.ts) reads
# its WebAssembly from its own folder. Pure JS and wasm, no install script, no dependencies.
EXTERNAL_PACKAGES = ('@visioncortex/vtracer',)


def copy_external_packages(dependency_root, companion, names=EXTERNAL_PACKAGES):
    """Copies each external package whole (without source maps) into the companion's node_modules."""
    for name in names:
        source = Path(dependency_root) / name
        if not (source / 'package.json').is_file():
            raise ValueError('%s is missing; run npm ci.' % name)
        shutil.copytree(source, Path(companion) / 'node_modules' / name, ignore=shutil.ignore_patterns('*.map'))


EXTERNAL_CHECK = r'''
const vt = require(process.argv[1]);
const svg = vt.convertPixels(new Uint8Array(64).fill(255), 4, 4, { hierarchical: 'cutout', mode: 'polygon' });
if (!svg.includes('<svg')) { console.error('no svg'); process.exit(1); }
'''


def validate_external_packages(node, companion):
    """VTracer loads its WebAssembly with this Node from the release layout and traces a tiny image."""
    package = (Path(companion) / 'node_modules' / '@visioncortex' / 'vtracer').resolve()
    result = subprocess.run([str(node), '-e', EXTERNAL_CHECK, str(package)], text=True, capture_output=True, timeout=60,
                            env={'PATH': str(Path(node).parent) + ':/usr/bin:/bin'})
    if result.returncode:
        raise ValueError('VTracer did not load from the release: ' + (result.stdout + result.stderr)[-2000:])


def copy_onnxruntime(dependency_root, companion, platform, arch):
    """Element shapes run ONNX Runtime's Node package in their worker (src/shapes/onnx.ts). It ships every platform's
    binaries (about 300 MB unpacked): copy it with this platform's only, without its install scripts, and its one
    dependency at run time, onnxruntime-common. Returns the binaries' folder, <platform>/<arch>."""
    source = Path(dependency_root) / 'onnxruntime-node'
    keep = '%s/%s' % (platform, arch)
    if not list(source.glob('bin/napi-*/%s/onnxruntime_binding.node' % keep)):
        raise ValueError('onnxruntime-node has no binary for %s; run npm ci on that platform.' % keep)
    target = Path(companion) / 'node_modules' / 'onnxruntime-node'
    def ignore(folder, names):
        parts = Path(folder).relative_to(source).parts
        if not parts: return [name for name in names if name == 'script']                       # install scripts (CUDA download)
        if len(parts) == 2 and parts[0] == 'bin': return [name for name in names if name != platform]   # bin/napi-v6
        if len(parts) == 3 and parts[0] == 'bin': return [name for name in names if name != arch]       # bin/napi-v6/<platform>
        return [name for name in names if name.endswith(('.map', '.d.ts'))]
    shutil.copytree(source, target, ignore=ignore)
    # npm ships the library twice (libonnxruntime.1.dylib and libonnxruntime.1.30.0.dylib, identical, ~40 MB each): the
    # binding loads the short name, so a longer-named identical copy is left out.
    binaries = sorted((path for path in target.glob('bin/napi-*/%s/*' % keep) if path.is_file()), key=lambda path: (len(path.name), path.name))
    seen = {}
    for path in binaries:
        digest = hash_file(path)
        if digest in seen: path.unlink()
        else: seen[digest] = path
    shutil.copytree(Path(dependency_root) / 'onnxruntime-common', Path(companion) / 'node_modules' / 'onnxruntime-common',
                    ignore=shutil.ignore_patterns('*.map', '*.d.ts'))
    return keep


def bundle_shape_worker(root, companion, esbuild, dependency_root, arch):
    """The element-shapes worker runs as its own process (src/shapes/worker.ts): bundled beside main.mjs as
    src/shapes-worker.mjs, where src/shapes/index.ts looks for it in a release, with ONNX Runtime left outside the bundle."""
    result = subprocess.run([str(esbuild), str(root / 'src/shapes/worker.ts'), '--bundle', '--platform=node', '--format=esm', '--target=node22',
                             '--outfile=' + str(companion / 'src/shapes-worker.mjs'), '--external:onnxruntime-node', '--log-level=warning',
                             '--legal-comments=none', '--banner:js=' + BANNER], cwd=root, text=True, capture_output=True)
    if result.returncode or 'warning' in result.stderr.lower():
        raise ValueError('Bundling the shape worker failed or warned: ' + (result.stderr or result.stdout)[-2000:])
    copy_onnxruntime(dependency_root, companion, 'darwin', arch)


def bundle_upscale_worker(root, companion, esbuild):
    """The goal-sharpening worker runs as its own process too (src/upscale/worker.ts): bundled beside main.mjs as
    src/upscale-worker.mjs, where src/upscale/index.ts looks for it in a release, using the same ONNX Runtime the shape
    worker's bundle_shape_worker copies (call that first)."""
    result = subprocess.run([str(esbuild), str(root / 'src/upscale/worker.ts'), '--bundle', '--platform=node', '--format=esm', '--target=node22',
                             '--outfile=' + str(companion / 'src/upscale-worker.mjs'), '--external:onnxruntime-node', '--log-level=warning',
                             '--legal-comments=none', '--banner:js=' + BANNER], cwd=root, text=True, capture_output=True)
    if result.returncode or 'warning' in result.stderr.lower():
        raise ValueError('Bundling the sharpening worker failed or warned: ' + (result.stderr or result.stdout)[-2000:])


UPSCALE_CHECK = r'''
const { fork } = require('node:child_process');
const child = fork(process.argv[1], ['--model', process.argv[2]], { serialization: 'advanced', execArgv: [], stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
let stderr = ''; child.stderr.on('data', d => { stderr += d; });
const timer = setTimeout(() => { console.log(JSON.stringify({ error: 'no answer', stderr })); child.kill(); process.exit(1); }, 30000);
child.on('message', reply => { clearTimeout(timer); console.log(JSON.stringify(reply)); child.kill(); process.exit(0); });
child.on('exit', code => { clearTimeout(timer); console.log(JSON.stringify({ error: 'exited ' + code, stderr })); process.exit(1); });
child.send({ id: 1, op: 'upscale', rgba: new Uint8Array(0), width: 0, height: 0, outputs: {}, max_pixels: 1 });
'''


def validate_upscale_worker(node, companion):
    """The bundled sharpening worker starts from the release layout and loads onnxruntime-node (it imports it on start):
    asked to sharpen nothing, it must answer invalid, not fail to load."""
    with tempfile.TemporaryDirectory(prefix='creative-validate-upscale-') as home:
        result = subprocess.run([str(node), '-e', UPSCALE_CHECK, str(Path(companion) / 'src/upscale-worker.mjs'), str(Path(home) / 'no-model')],
                                cwd=str(Path(companion) / 'src'), text=True, capture_output=True, timeout=60,
                                env={'HOME': home, 'PATH': str(Path(node).parent) + ':/usr/bin:/bin'})
    try: reply = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError): reply = {}
    error = reply.get('error')
    if not isinstance(error, dict) or error.get('code') != 'invalid':
        raise ValueError('The bundled sharpening worker did not start with onnxruntime-node: ' + (result.stdout + result.stderr)[-2000:])


WORKER_CHECK = r'''
const { fork } = require('node:child_process');
const child = fork(process.argv[1], ['--model', process.argv[2], '--idle-ms', '20000'], { serialization: 'advanced', execArgv: [], stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
let stderr = ''; child.stderr.on('data', d => { stderr += d; });
const timer = setTimeout(() => { console.log(JSON.stringify({ error: 'no answer', stderr })); child.kill(); process.exit(1); }, 30000);
child.on('message', reply => { clearTimeout(timer); console.log(JSON.stringify(reply)); child.kill(); process.exit(0); });
child.on('exit', code => { clearTimeout(timer); console.log(JSON.stringify({ error: 'exited ' + code, stderr })); process.exit(1); });
child.send({ id: 1, op: 'shape', image_id: 'none', prompt: { box: [0, 0, 1, 1] } });
'''


def validate_shape_worker(node, companion):
    """The bundled shape worker starts with this Node from the release layout and loads onnxruntime-node (the worker imports
    it on start): asked for a shape of nothing it has studied, it must answer not_studied, not fail to load."""
    with tempfile.TemporaryDirectory(prefix='creative-validate-worker-') as home:
        result = subprocess.run([str(node), '-e', WORKER_CHECK, str(Path(companion) / 'src/shapes-worker.mjs'), str(Path(home) / 'no-model')],
                                cwd=str(Path(companion) / 'src'), text=True, capture_output=True, timeout=60,
                                env={'HOME': home, 'PATH': str(Path(node).parent) + ':/usr/bin:/bin'})
    try: reply = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError): reply = {}
    error = reply.get('error')
    if not isinstance(error, dict) or error.get('code') != 'not_studied':
        raise ValueError('The bundled shape worker did not start with onnxruntime-node: ' + (result.stdout + result.stderr)[-2000:])


def bundle_companion(root, dependency_root, companion, lock, arch):
    esbuild = dependency_root / '.bin' / 'esbuild'
    if not esbuild.exists(): raise ValueError('esbuild is missing; run npm ci (it is a pinned devDependency).')
    # Pi's pi-ai sits where npm put it (nested under pi-coding-agent); the release entry imports it by name.
    # NODE_PATH is esbuild's last resort, so Pi's own imports still resolve to the same copy.
    pi_ai = next((folder for folder in (dependency_root, dependency_root / '@earendil-works/pi-coding-agent/node_modules')
                  if (folder / '@earendil-works/pi-ai/package.json').exists()), None)
    if pi_ai is None: raise ValueError('@earendil-works/pi-ai is missing; run npm ci.')
    result = subprocess.run([str(esbuild), str(root / 'src/release-entry.mjs'), '--bundle', '--platform=node', '--format=esm', '--target=node22',
                             '--outfile=' + str(companion / 'src/main.mjs'), '--external:pyodide', *['--external:' + name for name in EXTERNAL_PACKAGES], '--log-level=warning', '--legal-comments=none', '--banner:js=' + BANNER],
                            cwd=root, text=True, capture_output=True, env={**os.environ, 'NODE_PATH': str(pi_ai)})
    if result.returncode or 'warning' in result.stderr.lower():
        raise ValueError('Bundling the companion failed or warned: ' + (result.stderr or result.stdout)[-2000:])
    bundle_image_resizing(dependency_root, companion, esbuild, root, pi_ai)
    copy_external_packages(dependency_root, companion)
    bundle_shape_worker(root, companion, esbuild, dependency_root, arch)
    bundle_upscale_worker(root, companion, esbuild)
    shutil.copy2(root / 'src/visual-check-questions.json', companion / 'src/visual-check-questions.json')
    shutil.copy2(root / 'src/brush-catalog.json', companion / 'src/brush-catalog.json')
    shutil.copy2(root / 'src/downloaded-models.json', companion / 'src/downloaded-models.json')   # the notices list them
    shutil.copy2(root / 'src/texture-catalogue.json', companion / 'src/texture-catalogue.json')   # texture-library.ts reads it
    # Python for image assets: the sandbox runner beside main.mjs, Pyodide itself, the bundled skills
    # and the wheels the scripts import, fetched now so an artist's Mac never downloads them.
    shutil.copy2(root / 'src/pyodide-runner.mjs', companion / 'src/pyodide-runner.mjs')
    shutil.copytree(dependency_root / 'pyodide', companion / 'node_modules/pyodide', ignore=shutil.ignore_patterns('*.map', '*.html', '*.d.ts'))
    shutil.copytree(root / 'skills', companion / 'skills', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(root / 'effects', companion / 'effects')   # the bundled custom effects and policy.yaml (src/effects/library.ts, policy.ts)
    fetch = ("import(process.argv[1]).then(async ({loadPyodide}) => { const py = await loadPyodide({packageCacheDir: process.argv[2]});"
             " await py.loadPackage(process.argv[3].split(',')); })")
    subprocess.run([shutil.which('node') or 'node', '-e', fetch, (companion / 'node_modules/pyodide/pyodide.mjs').as_uri(),
                    str(companion / 'pyodide-packages'), 'numpy,pillow'], check=True, timeout=300, capture_output=True)
    (companion / 'pi-package').mkdir()
    shutil.copy2(dependency_root / '@earendil-works/pi-coding-agent/package.json', companion / 'pi-package/package.json')
    # Bundled code keeps its licenses: one file with every shipped package's license text.
    sections = []
    for name, entry in sorted(lock['packages'].items()):
        if not name or entry.get('dev'): continue
        folder = dependency_root.parent / name
        licenses = sorted(p for p in folder.glob('*') if p.is_file() and p.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')))
        text = '\n'.join(p.read_text(errors='replace').strip() for p in licenses) or 'License: ' + str(entry.get('license', 'see package'))
        sections.append('%s@%s\n%s' % (name.removeprefix('node_modules/'), entry.get('version', ''), text))
    (companion / 'THIRD_PARTY_LICENSES.txt').write_text(('\n\n' + '=' * 72 + '\n\n').join(sections) + '\n')


def validate_companion(node, companion):
    with tempfile.TemporaryDirectory(prefix='creative-validate-') as home:
        config = Path(home) / 'config.json'
        config.write_text(json.dumps({'output': str(Path(home) / 'out'), 'bridge_url': 'http://127.0.0.1:9', 'prevent_idle_sleep': False}))
        process = subprocess.Popen([str(node), str(companion / 'src/main.mjs')], cwd=companion / 'src', text=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={'HOME': home, 'PATH': str(node.parent) + ':/usr/bin:/bin', 'KRITA_CREATIVE_CONFIG': str(config)})
        seen = set()
        try:
            import selectors, time
            selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 60
            while not {'ready', 'build'} <= seen and time.monotonic() < deadline and process.poll() is None:
                if selector.select(timeout=1):
                    line = process.stdout.readline()
                    try: seen.add(json.loads(line).get('type'))
                    except ValueError: pass
            if not {'ready', 'build'} <= seen:
                process.kill()
                raise ValueError('The bundled companion did not start: ' + process.stderr.read()[-2000:])
            process.stdin.write(json.dumps({'type': 'shutdown'}) + '\n'); process.stdin.flush()
            process.wait(timeout=30)
        finally:
            if process.poll() is None: process.kill()


MACHO_MAGICS = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}


def is_macho(path):
    """A Mach-O file (thin or universal; a fat header with 30 or more architectures is a Java class)."""
    if path.is_symlink() or not path.is_file(): return False
    with path.open('rb') as stream: head = stream.read(8)
    if head[:4] not in MACHO_MAGICS: return False
    return head[:4] not in (b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca') or int.from_bytes(head[4:8], 'big') < 30


def signing_identity(given=None, environment=None):
    """The Developer ID to sign the companion's native files with: the one given, else KRITA_AGENT_SIGN_IDENTITY (which
    agent/package-app.sh sets); None (an empty value too) leaves them as npm shipped them."""
    environment = os.environ if environment is None else environment
    return given or environment.get('KRITA_AGENT_SIGN_IDENTITY') or None


def sign_native_files(companion, identity, runner=subprocess.run):
    """With a named identity, sign every Mach-O file of the companion (onnxruntime-node's binaries) as a notarized app needs:
    a secure timestamp and the hardened runtime. This happens BEFORE the manifest is written: the plugin checks the companion
    byte for byte against it on first run, so the manifest must record the signed bytes. Returns the files signed."""
    if not identity: return []
    signed = []
    for path in sorted(Path(companion).rglob('*')):
        if not is_macho(path): continue
        os.chmod(path, path.stat().st_mode | 0o200)
        result = runner(['codesign', '--force', '--sign', identity, '--timestamp', '--options', 'runtime', str(path)], capture_output=True, text=True)
        if result.returncode:
            raise ValueError('Signing %s failed: %s' % (path.relative_to(companion), (result.stderr or result.stdout).strip()[-500:]))
        signed.append(path)
    return signed


def finish_release(staging, package, details, node_spec, packages):
    """Stamp the build identity and write the manifest of every file (signed native files included: sign them first)."""
    companion = staging / 'companion'
    # The digest covers physical payloads. Derived manifests are excluded
    # from their own digest and then separately covered by the file list.
    old_info = companion / 'build-info.json'
    if old_info.exists(): old_info.unlink()
    payload = inventory(staging)
    build_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    info = {'version': package['version'], 'protocol_version': 2, 'build_id': build_id,
            'platform': 'darwin', 'architecture': details['architecture'], 'node': 'v' + node_spec['version'], 'validation': 'staged-sdk-import-passed',
            'live_krita_verified': False, 'clean_mac_verified': False,
            'krita_support': 'Krita 5.2/5.3 candidate; exact-version live compatibility validation required'}
    (staging / 'plugin/kritamcp').mkdir(parents=True, exist_ok=True)
    for target in (companion / 'build-info.json', staging / 'plugin/kritamcp/build-info.json'):
        target.write_text(json.dumps(info, indent=2) + '\n')
    manifest = {**info, 'node_runtime': node_spec, 'dependencies': packages, 'files': inventory(staging)}
    (staging / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def build(destination, node=None, root=ROOT, plugin=None, node_spec=None, dependencies=None, runtime_cache=None, identity=None):
    destination, root = Path(destination).resolve(), Path(root).resolve()
    plugin = Path(plugin).resolve() if plugin else root.parent / 'krita-mcp/krita-plugin'
    if destination.exists(): raise ValueError('Choose a new release output folder; existing files are never overwritten.')
    runtime = runtime_module(plugin)
    node_spec = node_spec or runtime.fetch_spec(NODE_VERSION)
    # Validate the staged companion with the exact runtime artists will get, unless one is given.
    node = Path(node).resolve() if node else runtime.ensure(node_spec, root=runtime_cache or Path(tempfile.gettempdir()) / 'creative-agent-build-runtimes')
    details = verify_node(node)
    if details['node'].lstrip('v') != node_spec['version'] and not os.environ.get('CREATIVE_AGENT_ALLOW_NODE_MISMATCH'):
        raise ValueError('Validate with the pinned Node ' + node_spec['version'] + ', not ' + details['node'] + '.')
    package = json.loads((root / 'package.json').read_text())
    lock_path = root / 'package-lock.json'
    if not lock_path.is_file(): raise ValueError('A registry package-lock.json is required. Run npm ci from the approved lockfile.')
    lock = json.loads(lock_path.read_text())
    if lock.get('packages', {}).get('', {}).get('dependencies') != package['dependencies']:
        raise ValueError('package.json dependencies differ from the approved lockfile.')
    dependency_root = Path(dependencies).resolve() if dependencies else root / 'node_modules'
    if not (dependency_root / '.package-lock.json').is_file():
        raise ValueError('Use a complete npm ci dependency tree; development package symlinks are not a release input.')
    for name, entry in lock['packages'].items():
        if not name: continue
        if entry.get('link') or not entry.get('resolved', '').startswith('https://registry.npmjs.org/'):
            raise ValueError('Use registry dependencies in the release lockfile: ' + name)
        installed_manifest = dependency_root / name.removeprefix('node_modules/') / 'package.json'
        if not installed_manifest.is_file():
            if entry.get('optional'): continue
            raise ValueError('Locked dependency is absent: ' + name)
        if json.loads(installed_manifest.read_text())['version'] != entry['version']:
            raise ValueError('Installed dependency differs from the lockfile: ' + name)
    for candidate in dependency_root.rglob('*'):
        if candidate.is_symlink() and '.bin' not in candidate.parts:
            raise ValueError('Use physical npm ci dependencies, not development symlinks: ' + str(candidate.relative_to(dependency_root)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.creative-release-', dir=destination.parent))
    try:
        companion = staging / 'companion'; (companion / 'src').mkdir(parents=True)
        shutil.copy2(root / 'package.json', companion)
        shutil.copy2(lock_path, companion)
        packages = {}
        for name, version in package['dependencies'].items():
            source = dependency_root / name
            installed = json.loads((source / 'package.json').read_text())
            if installed['version'] != version: raise ValueError('Dependency version differs from package.json: ' + name)
            packages[name] = installed['version']
        # One bundled file instead of ~17,500 node_modules files (~180 MB → ~14 MB).
        bundle_companion(root, dependency_root, companion, lock, details['architecture'])
        # Signed now, before the checks below load them and before the manifest records their bytes (sign_native_files).
        sign_native_files(companion, signing_identity(identity))
        shutil.copytree(plugin / 'kritamcp', staging / 'plugin/kritamcp',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'creative-agent-config.json', 'build-info.json', '.DS_Store'))
        shutil.copy2(plugin / 'kritamcp.desktop', staging / 'plugin/kritamcp.desktop')
        shutil.copy2(root / 'scripts/install.py', staging / 'install.py')
        # Start the bundled companion in an isolated home, as the panel would. A module the
        # bundle missed, or an asset it cannot find, fails here instead of on an artist's Mac.
        validate_companion(node, companion)
        validate_shape_worker(node, companion)
        validate_upscale_worker(node, companion)
        validate_external_packages(node, companion)
        manifest = finish_release(staging, package, details, node_spec, packages)
        staging.rename(destination)
        return {key: manifest[key] for key in ('version','build_id','platform','architecture','node','validation','live_krita_verified','clean_mac_verified')}
    finally:
        if staging.exists(): shutil.rmtree(staging)


def prune_builds(output, keep):
    """Keep the newest `keep` release bundles beside `output` (each holds Node and node_modules, ~290 MB).
    Only sibling folders containing a release-manifest.json are considered."""
    output = Path(output).resolve()
    siblings = [p for p in output.parent.iterdir() if p.is_dir() and (p / 'release-manifest.json').is_file()]
    siblings.sort(key=lambda p: (p == output, p.stat().st_mtime), reverse=True)
    removed = []
    for old in siblings[max(keep, 1):]:
        shutil.rmtree(old); removed.append(old.name)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--node', type=Path, help='Node used only to validate the staged companion (default: the pinned managed runtime)')
    parser.add_argument('--node-spec', type=Path, help='Pinned runtime spec JSON (default: fetched from nodejs.org SHASUMS256.txt)')
    parser.add_argument('--dependencies', type=Path, help='Complete physical node_modules from npm ci; defaults to the source checkout')
    parser.add_argument('--sign-identity', help='Developer ID Application identity to sign the native files with before the manifest is written (default: KRITA_AGENT_SIGN_IDENTITY; none: left as npm shipped them)')
    parser.add_argument('--keep-builds', type=int, default=2, help='Release bundles to keep beside --output, including this one (default 2)')
    args = parser.parse_args()
    try:
        spec = json.loads(args.node_spec.read_text()) if args.node_spec else None
        result = build(args.output, args.node, node_spec=spec, dependencies=args.dependencies, identity=args.sign_identity)
        result['pruned_builds'] = prune_builds(args.output, args.keep_builds)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as error: raise SystemExit(str(error))


if __name__ == '__main__': main()
