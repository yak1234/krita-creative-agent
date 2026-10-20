/** Verified, rollback-safe release installation. No external package dependencies. */
import {createHash} from 'node:crypto';
import {createReadStream, lstatSync} from 'node:fs';
import {access, chmod, cp, link, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rename, rm, stat, writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import {basename, dirname, isAbsolute, join, relative, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const identityKeys = ['version', 'protocol_version', 'build_id'];
const componentInfo = ['companion/build-info.json', 'plugin/kritamcp/build-info.json'];
const requiredFiles = ['companion/src/main.mjs', 'plugin/kritamcp/creative_docker.py', 'plugin/kritamcp.desktop', ...componentInfo];
const supportedVersion = '1.0.0';
const hex = /^[a-f0-9]{64}$/;

/** nodejs.org's name for a platform (darwin-arm64, linux-x64, win-x64), as kritamcp/node_runtime.py keys a pinned runtime. */
export function runtimeKey(platform = process.platform, architecture = process.arch) {
  const system = {darwin: 'darwin', linux: 'linux', win32: 'win'}[platform];
  return system && ['x64', 'arm64'].includes(architecture) ? system + '-' + architecture : null;
}
// Where node sits in an unpacked Node: Windows keeps node.exe at the top.
const nodeFile = platform => platform === 'win32' ? 'node.exe' : 'bin/node';
/** Krita's plugin folder and this app's per-user folders on each OS (releases and runtimes share a parent). */
export function defaultLocations(platform = process.platform, env = process.env, home = homedir()) {
  if (platform === 'win32') {
    const local = env.LOCALAPPDATA || join(home, 'AppData', 'Local'), roaming = env.APPDATA || join(home, 'AppData', 'Roaming');
    return {destination: join(roaming, 'krita', 'pykrita'), runtimeDestination: join(local, 'Creative Agent', 'releases'), cacheDestination: join(local, 'Creative Agent', 'cache')};
  }
  if (platform === 'linux') {
    const data = env.XDG_DATA_HOME || join(home, '.local', 'share'), cache = env.XDG_CACHE_HOME || join(home, '.cache');
    return {destination: join(data, 'krita', 'pykrita'), runtimeDestination: join(data, 'creative-agent', 'releases'), cacheDestination: join(cache, 'creative-agent')};
  }
  // The fork's own pykrita folder (Krita Agent keeps its per-user data in ~/Library/Application Support/KritaAgent), never the
  // stock Krita's: the stock folder needs an explicit --destination.
  return {destination: join(home, 'Library/Application Support/KritaAgent/krita/pykrita'), runtimeDestination: join(home, 'Library/Application Support/Creative Agent/releases'),
    cacheDestination: join(home, 'Library/Caches/Creative Agent')};
}

/**
 * The installed Krita Agent.app that a plugin installed into the fork's pykrita folder would shadow, or null. The packaged app
 * carries the plugin; a copy in the user's own pykrita folder is found first and would hide it (and every later update of the app).
 * macOS compares paths without regard to case.
 */
export function shadowedBundledPlugin(destination, home = homedir(), applications) {
  applications = applications || ['/Applications', join(home, 'Applications')];
  const same = (a, b) => resolve(a).toLowerCase() === resolve(b).toLowerCase();
  if (!same(destination, defaultLocations('darwin', {}, home).destination)) return null;
  return applications.map(folder => join(folder, 'Krita Agent.app')).find(app => { try { return lstatSync(app).isDirectory(); } catch { return false; } }) || null;
}

export async function sha256(path) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest('hex');
}
function safeName(name) {
  return typeof name === 'string' && name.length && !isAbsolute(name) && !name.includes('\\') && !name.includes('\0') &&
    name.split('/').every(part => part && part !== '.' && part !== '..');
}
function codepointCompare(a, b) {
  const aa = Array.from(a), bb = Array.from(b);
  for (let i = 0; i < Math.min(aa.length, bb.length); i++) {
    const difference = aa[i].codePointAt(0) - bb[i].codePointAt(0);
    if (difference) return difference;
  }
  return aa.length - bb.length;
}
export function canonicalInventory(files) {
  // Matches the release builder's Python JSON encoding, including Unicode names.
  return JSON.stringify(Object.fromEntries(Object.entries(files).sort(([a], [b]) => codepointCompare(a, b))))
    .replace(/[\u007f-\uffff]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
}
async function inventory(directory, prefix = '') {
  const files = [];
  for (const entry of await readdir(join(directory, prefix), {withFileTypes: true})) {
    const name = prefix ? prefix + '/' + entry.name : entry.name;
    if (entry.isSymbolicLink()) throw new Error('The release contains an unsafe symbolic link: ' + name);
    if (entry.isDirectory()) files.push(...await inventory(directory, name));
    else if (entry.isFile()) files.push(name);
    else throw new Error('Unsupported file in release: ' + name);
  }
  return files;
}
async function exists(path) {
  try { await lstat(path); return true; } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

export async function verifyBundle(bundle, system = {platform: process.platform, architecture: process.arch}) {
  bundle = await realpath(bundle);
  const manifest = JSON.parse(await readFile(join(bundle, 'release-manifest.json'), 'utf8'));
  if (manifest.version !== supportedVersion || manifest.protocol_version !== 2 || !hex.test(manifest.build_id || ''))
    throw new Error('This release has an unsupported or invalid manifest.');
  // A release either bundles a runtime for one OS and architecture, or pins a managed Node for several;
  // a pinned release whose payload is plain JavaScript and Python may say platform "any".
  const key = runtimeKey(system.platform, system.architecture);
  const supported = manifest.node_runtime ? !!key && !!manifest.node_runtime.archives?.[key] && /^\d+\.\d+\.\d+$/.test(manifest.node_runtime.version ?? '')
    : manifest.architecture === system.architecture;
  if (!(manifest.platform === system.platform || (manifest.node_runtime && manifest.platform === 'any')) || !supported)
    throw new Error('This release does not support this computer’s processor or operating system.');
  if (!manifest.node_runtime && !Object.hasOwn(manifest.files ?? {}, 'runtime/' + nodeFile(system.platform))) throw new Error('The release is missing a required component.');
  if (!manifest.files || typeof manifest.files !== 'object' || Array.isArray(manifest.files)) throw new Error('Missing release file inventory.');
  const names = Object.keys(manifest.files);
  if (names.some(name => !safeName(name) || !hex.test(manifest.files[name]))) throw new Error('The release manifest contains an unsafe file entry.');
  if (requiredFiles.some(name => !names.includes(name))) throw new Error('The release is missing a required component.');
  const actual = (await inventory(bundle)).filter(name => name !== 'release-manifest.json').sort();
  const sortedNames = [...names].sort();
  if (actual.length !== names.length || actual.some((name, index) => name !== sortedNames[index])) throw new Error('The release file inventory does not match its manifest.');
  // Limit concurrency to keep memory and disk pressure low on an artist's Mac.
  for (let index = 0; index < names.length; index += 8) {
    await Promise.all(names.slice(index, index + 8).map(async name => {
      if (await sha256(join(bundle, name)) !== manifest.files[name]) throw new Error('The release is damaged or changed: ' + name);
    }));
  }
  for (const name of componentInfo) {
    const info = JSON.parse(await readFile(join(bundle, name), 'utf8'));
    if (identityKeys.some(key => info[key] !== manifest[key])) throw new Error('The release components have different build identities.');
  }
  const payload = Object.fromEntries(Object.entries(manifest.files).filter(([name]) => !componentInfo.includes(name)));
  if (createHash('sha256').update(canonicalInventory(payload)).digest('hex') !== manifest.build_id)
    throw new Error('The release payload does not match its build identifier.');
  return manifest;
}

async function verifyInstalledRuntime(release, manifest) {
  const expected = Object.keys(manifest.files).filter(name => name.startsWith('runtime/') || name.startsWith('companion/')).sort();
  const actual = (await inventory(release)).filter(name => name !== 'release-manifest.json').sort();
  if (actual.length !== expected.length || actual.some((name, index) => name !== expected[index])) throw new Error('The installed runtime changed. Choose a fresh runtime location.');
  for (const name of expected) if (await sha256(join(release, name)) !== manifest.files[name]) throw new Error('The installed runtime changed: ' + name);
}

// Each release bundles Node (~110 MB) and node_modules (~180 MB). Files whose hash matches
// an installed release are hard-linked from it, so a new install costs only what changed.
// Releases are immutable, so sharing inodes between them is safe.
async function installedReleases(runtimeDestination) {
  const releases = [];
  for (const name of await readdir(runtimeDestination).catch(() => [])) {
    if (!/^[0-9a-f]{64}$/.test(name)) continue;
    const dir = join(runtimeDestination, name);
    try { releases.push({ name, dir, files: JSON.parse(await readFile(join(dir, 'release-manifest.json'), 'utf8')).files ?? {}, mtime: (await stat(dir)).mtimeMs }); }
    catch { /* Not a complete release; ignored. */ }
  }
  return releases;
}
async function stageRelease(bundle, stage, manifest, donors) {
  let linked = 0, copied = 0;
  const names = Object.keys(manifest.files).filter(name => name.startsWith('runtime/') || name.startsWith('companion/'));
  for (const name of names) {
    const target = join(stage, name);
    await mkdir(dirname(target), {recursive: true});
    const donor = donors.find(d => d.files[name] === manifest.files[name]);
    if (donor) { try { await link(join(donor.dir, name), target); linked++; continue; } catch { /* Fall back to copying. */ } }
    await cp(join(bundle, name), target, {errorOnExist: true}); copied++;
  }
  await cp(join(bundle, 'release-manifest.json'), join(stage, 'release-manifest.json'));
  return {linked, copied};
}
// Keep the current release, the one it replaced, and the newest others up to `keep`;
// keep the newest `keepBackups` plugin backups. Returns what was removed.
export async function pruneInstalls({runtimeDestination, current, previous, keep = 2, backups, keepBackups = 5, runtimes}) {
  const removed = {releases: [], backups: [], runtimes: []};
  const releases = (await installedReleases(runtimeDestination)).sort((a, b) => b.mtime - a.mtime);
  const keepNames = new Set([current, previous].filter(Boolean));
  for (const release of releases) if (keepNames.size < Math.max(keep, 1)) keepNames.add(release.name);
  for (const release of releases) if (!keepNames.has(release.name)) { await rm(release.dir, {recursive: true, force: true}); removed.releases.push(release.name); }
  // Managed Node versions that no kept release pins any more.
  if (runtimes) {
    const pinned = new Set();
    for (const release of releases.filter(r => keepNames.has(r.name))) {
      try { const version = JSON.parse(await readFile(join(release.dir, 'release-manifest.json'), 'utf8')).node_runtime?.version; if (version) pinned.add(version); } catch {}
    }
    for (const name of await readdir(runtimes).catch(() => [])) {
      const match = /^node-v(\d+\.\d+\.\d+)-/.exec(name);
      if (match && !pinned.has(match[1])) { await rm(join(runtimes, name), {recursive: true, force: true}); removed.runtimes.push(name); }
    }
  }
  if (backups) {
    const entries = [];
    for (const name of await readdir(backups).catch(() => [])) { const dir = join(backups, name); try { const s = await stat(dir); if (s.isDirectory()) entries.push({dir, name, mtime: s.mtimeMs}); } catch {} }
    for (const entry of entries.sort((a, b) => b.mtime - a.mtime).slice(keepBackups)) { await rm(entry.dir, {recursive: true, force: true}); removed.backups.push(entry.name); }
  }
  return removed;
}

export async function installRelease({bundle, project, destination = defaultLocations().destination,
  runtimeDestination = defaultLocations().runtimeDestination,
  cacheDestination = defaultLocations().cacheDestination, keepReleases = 2, keepBackups = 5, allowShadow = false, applications, home = homedir()}, hooks = {}) {
  const shadowed = allowShadow ? null : shadowedBundledPlugin(resolve(destination), home, applications);
  if (shadowed) throw new Error(shadowed + ' carries the plugin: a copy in ' + resolve(destination) + ' would hide it. Update the app instead, or choose another --destination, or pass --allow-shadow.');
  bundle = await realpath(bundle); project = await realpath(project);
  if (!(await lstat(project)).isDirectory()) throw new Error('Choose an existing folder for your paintings.');
  const manifest = await verifyBundle(bundle);
  destination = resolve(destination); runtimeDestination = resolve(runtimeDestination);
  if (destination === project || runtimeDestination === project || destination === runtimeDestination)
    throw new Error('Artwork, plugins and runtime must use separate folders.');
  await mkdir(destination, {recursive: true}); await mkdir(runtimeDestination, {recursive: true});
  destination = await realpath(destination); runtimeDestination = await realpath(runtimeDestination);
  // Runtime releases are immutable; updates use new directories.
  const release = join(runtimeDestination, manifest.build_id);
  const backup = join(dirname(destination), '.creative-agent-backups', new Date().toISOString().replace(/[:.]/g, '-') + '-' + process.pid);
  const temporary = await mkdtemp(join(dirname(destination), '.creative-install-'));
  let runtimeStage, staged = null, previousBuild = null;
  try {
    await cp(join(bundle, 'plugin/kritamcp'), join(temporary, 'kritamcp'), {recursive: true, dereference: false, errorOnExist: true});
    await cp(join(bundle, 'plugin/kritamcp.desktop'), join(temporary, 'kritamcp.desktop'), {errorOnExist: true});
    if (await exists(release)) await verifyInstalledRuntime(release, manifest);
    else {
      runtimeStage = await mkdtemp(join(runtimeDestination, '.release-'));
      staged = await stageRelease(bundle, runtimeStage, manifest, await installedReleases(runtimeDestination));
      if (!manifest.node_runtime && process.platform !== 'win32') await chmod(join(runtimeStage, 'runtime/bin/node'), 0o755);
      await verifyInstalledRuntime(runtimeStage, manifest);
      await rename(runtimeStage, release); runtimeStage = undefined;
    }
    // Managed runtime: shared by releases, fetched by the panel on first start (kritamcp/node_runtime.py).
    const runtimes = join(dirname(runtimeDestination), 'runtimes');
    const node = manifest.node_runtime ? join(runtimes, `node-v${manifest.node_runtime.version}-${runtimeKey()}`, nodeFile(process.platform)) : join(release, 'runtime', nodeFile(process.platform));
    const settings = {node, ...(manifest.node_runtime ? {node_runtime: manifest.node_runtime, node_runtimes: runtimes} : {}),
      companion: join(release, 'companion/src/main.mjs'),
      // Records and app files live beside the releases, not in the artwork folder (storage-layout).
      project_root: project, paintings_dir: project, data_dir: join(dirname(runtimeDestination), 'data'), cache_dir: resolve(cacheDestination),
      output: join(dirname(runtimeDestination), 'data'), bridge_url: 'http://127.0.0.1:5678',
      build_id: manifest.build_id, protocol_version: manifest.protocol_version};
    const oldConfiguration = join(destination, 'kritamcp/creative-agent-config.json');
    if (await exists(oldConfiguration)) {
      const previous = JSON.parse(await readFile(oldConfiguration, 'utf8'));
      previousBuild = /^[0-9a-f]{64}$/.test(previous.build_id ?? '') ? previous.build_id : null;
      for (const key of ['bridge_url', 'model_idle_timeout_ms']) if (Object.hasOwn(previous, key)) settings[key] = previous[key];
      const oldState = previous.legacy_output || previous.output;
      if (typeof oldState === 'string' && resolve(oldState) !== settings.output) settings.legacy_output = oldState;
    }
    await writeFile(join(temporary, 'kritamcp/creative-agent-config.json'), JSON.stringify(settings, null, 2) + '\n', {mode: 0o600});
    await mkdir(backup, {recursive: true});
    const moved = [], installed = [];
    try {
      for (const name of ['kritamcp', 'kritamcp.desktop']) {
        const target = join(destination, name);
        if (await exists(target)) { await rename(target, join(backup, name)); moved.push(name); }
        await rename(join(temporary, name), target); installed.push(name);
        if (hooks.afterComponent) await hooks.afterComponent(name);
      }
    } catch (error) {
      const rollbackErrors = [];
      for (const name of ['kritamcp', 'kritamcp.desktop']) {
        try {
          if (installed.includes(name)) await rm(join(destination, name), {recursive: true, force: true});
          if (moved.includes(name)) await rename(join(backup, name), join(destination, name));
        } catch (rollbackError) { rollbackErrors.push(rollbackError.message); }
      }
      if (rollbackErrors.length) throw new Error('Installation stopped. Restore the backup at ' + backup + '. ' + rollbackErrors.join('; '));
      throw error;
    }
    const pruned = await pruneInstalls({runtimeDestination, current: manifest.build_id, previous: previousBuild, keep: keepReleases,
      backups: dirname(backup), keepBackups, runtimes: join(dirname(runtimeDestination), 'runtimes')}).catch(error => ({error: error.message}));
    return {destination, release, backup, project, build_id: manifest.build_id, version: manifest.version, staged, pruned,
      reload_required: true, live_verified: false, artwork_modified: false,
      next_steps: 'Save your work. Enable Krita MCP Bridge in Krita’s Python Plugin Manager if needed, then restart Krita when ready. Open Settings → Dockers → Creative Agent.'};
  } finally {
    await rm(temporary, {recursive: true, force: true});
    if (runtimeStage) await rm(runtimeStage, {recursive: true, force: true});
  }
}

async function main() {
  const args = process.argv.slice(2); const options = {};
  for (let index = 0; index < args.length; index++) {
    if (args[index] === '--verify') options.verify = true;
    else if (args[index] === '--allow-shadow') options.allowShadow = true;
    else if (['--bundle','--project','--destination','--runtime-destination'].includes(args[index])) {
      const value = args[++index]; if (!value || value.startsWith('--')) throw new Error('An installer path is missing.');
      options[args[index - 1].slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
    } else if (['--keep-releases','--keep-backups'].includes(args[index])) {
      const value = Number(args[++index]); if (!Number.isInteger(value) || value < 1) throw new Error(args[index - 1] + ' needs a whole number of at least 1.');
      options[args[index - 1] === '--keep-releases' ? 'keepReleases' : 'keepBackups'] = value;
    } else throw new Error('Unknown installer option.');
  }
  if (!options.bundle) throw new Error('A release bundle is required.');
  if (options.verify) {
    const manifest = await verifyBundle(options.bundle);
    process.stdout.write(JSON.stringify({verified: true, version: manifest.version, build_id: manifest.build_id}) + '\n');
  } else {
    if (!options.project) throw new Error('Choose a folder for your paintings.');
    process.stdout.write(JSON.stringify(await installRelease(options)) + '\n');
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stdout.write(JSON.stringify({error: error.message}) + '\n'); process.exitCode = 1; });
}
