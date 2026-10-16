import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdir, mkdtemp, readFile, readdir, realpath, rm, stat, symlink, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {canonicalInventory, installRelease, sha256, verifyBundle} from '../scripts/install-release.mjs';

async function fixture({root: existingRoot, name = 'release', main = 'export const test = true;', managed = false} = {}) {
  const root = existingRoot ?? await realpath(await mkdtemp(join(tmpdir(), 'creative-installer-test-')));
  const bundle = join(root, name);
  const files = {
    ...(managed ? {} : {'runtime/bin/node': '# test runtime', 'runtime/LICENSE': 'license'}),
    'companion/src/main.mjs': main,
    'companion/data/étoile.txt': 'unicode resource',
    'plugin/kritamcp/creative_docker.py': '# test plugin',
    'plugin/kritamcp.desktop': '[Desktop Entry]\nName=Krita MCP Bridge\n',
  };
  for (const [name, value] of Object.entries(files)) { await mkdir(dirname(join(bundle, name)), {recursive:true}); await writeFile(join(bundle,name),value); }
  const checksums = {};
  for (const name of Object.keys(files)) checksums[name] = await sha256(join(bundle,name));
  const build_id = createHash('sha256').update(canonicalInventory(checksums)).digest('hex');
  const info = {version:'1.0.0', protocol_version:2, platform:'darwin', architecture:process.arch, build_id};
  for (const name of ['companion/build-info.json','plugin/kritamcp/build-info.json']) {
    await writeFile(join(bundle,name),JSON.stringify(info)); checksums[name] = await sha256(join(bundle,name));
  }
  const node_runtime = {version:'22.23.2',archives:{['darwin-'+process.arch]:{file:`node-v22.23.2-darwin-${process.arch}.tar.gz`,sha256:'a'.repeat(64)}}};
  const manifest = {...info,...(managed?{architecture:'any',node_runtime}:{}),files:checksums}; await writeFile(join(bundle,'release-manifest.json'),JSON.stringify(manifest));
  const project = join(root, 'Artist’s paintings'); await mkdir(project,{recursive:true}); if (!existingRoot) await writeFile(join(project,'painting.kra'),'original artwork');
  return {root,bundle,project,destination:join(root,'Krita support/pykrita'),runtimeDestination:join(root,'Creative Agent/releases'),manifest};
}
const cleanup = f => rm(f.root,{recursive:true,force:true});

test('graphical installer engine verifies content and installs without touching artwork or auth',async()=>{
  const f = await fixture();
  try {
    const manifest = await verifyBundle(f.bundle);
    assert.equal(manifest.build_id,f.manifest.build_id);
    const result = await installRelease(f);
    const settings = JSON.parse(await readFile(join(f.destination,'kritamcp/creative-agent-config.json'),'utf8'));
    assert.equal(settings.project_root,f.project);
    assert.equal(settings.paintings_dir,f.project);
    assert.equal(settings.data_dir,join(f.root,'Creative Agent/data')); assert.equal(settings.output,settings.data_dir);
    assert.ok(settings.cache_dir.endsWith('Creative Agent'));
    assert.equal(settings.build_id,f.manifest.build_id);
    assert.equal(await readFile(join(f.project,'painting.kra'),'utf8'),'original artwork');
    assert.deepEqual(await readdir(f.project),['painting.kra']);
    assert.equal(result.artwork_modified,false); assert.equal(result.live_verified,false); assert.equal(result.reload_required,true);
    assert.equal(await readFile(join(f.destination,'kritamcp/creative_docker.py'),'utf8'),'# test plugin');
  } finally { await cleanup(f); }
});

test('updating keeps a complete backup and the previous state migration location',async()=>{
  const f = await fixture();
  try {
    await mkdir(join(f.destination,'kritamcp'),{recursive:true});
    await writeFile(join(f.destination,'kritamcp/creative_docker.py'),'previous plugin');
    await writeFile(join(f.destination,'kritamcp.desktop'),'previous desktop');
    await writeFile(join(f.destination,'kritamcp/creative-agent-config.json'),JSON.stringify({output:'/old/state',bridge_url:'http://127.0.0.1:5679',model_idle_timeout_ms:99000}));
    const result = await installRelease(f);
    assert.equal(await readFile(join(result.backup,'kritamcp/creative_docker.py'),'utf8'),'previous plugin');
    const settings = JSON.parse(await readFile(join(f.destination,'kritamcp/creative-agent-config.json'),'utf8'));
    assert.equal(settings.legacy_output,'/old/state'); assert.equal(settings.bridge_url,'http://127.0.0.1:5679');
    assert.equal(settings.model_idle_timeout_ms,99000);
    const again = await installRelease(f);
    assert.equal(again.release,result.release);
  } finally { await cleanup(f); }
});

test('a failure after replacing one component restores both original components',async()=>{
  const f = await fixture();
  try {
    await mkdir(join(f.destination,'kritamcp'),{recursive:true});
    await writeFile(join(f.destination,'kritamcp/creative_docker.py'),'previous plugin');
    await writeFile(join(f.destination,'kritamcp.desktop'),'previous desktop');
    await assert.rejects(installRelease(f,{afterComponent:async name=>{ if(name==='kritamcp') throw new Error('simulated volume failure'); }}),/simulated volume failure/);
    assert.equal(await readFile(join(f.destination,'kritamcp/creative_docker.py'),'utf8'),'previous plugin');
    assert.equal(await readFile(join(f.destination,'kritamcp.desktop'),'utf8'),'previous desktop');
    assert.equal(await readFile(join(f.project,'painting.kra'),'utf8'),'original artwork');
  } finally { await cleanup(f); }
});

test('tampered payload and changed installed runtime are rejected before replacing the plugin',async()=>{
  const f = await fixture();
  try {
    const result = await installRelease(f);
    await writeFile(join(result.release,'companion/src/main.mjs'),'tampered');
    await assert.rejects(installRelease(f),/installed runtime changed/);
    assert.equal(await readFile(join(f.destination,'kritamcp/creative_docker.py'),'utf8'),'# test plugin');
    await writeFile(join(f.bundle,'plugin/kritamcp/creative_docker.py'),'damaged download');
    await assert.rejects(verifyBundle(f.bundle),/damaged or changed/);
  } finally { await cleanup(f); }
});

test('manifest traversal, unknown files, symbolic links and incompatible architecture fail closed',async()=>{
  const f = await fixture();
  try {
    await assert.rejects(verifyBundle(f.bundle,{platform:'darwin',architecture:'unsupported'}),/does not support/);
    await writeFile(join(f.bundle,'unexpected.txt'),'extra'); await assert.rejects(verifyBundle(f.bundle),/inventory/); await rm(join(f.bundle,'unexpected.txt'));
    await symlink(f.project,join(f.bundle,'external')); await assert.rejects(verifyBundle(f.bundle),/symbolic link/); await rm(join(f.bundle,'external'));
    f.manifest.files['../outside'] = 'a'.repeat(64);
    await writeFile(join(f.bundle,'release-manifest.json'),JSON.stringify(f.manifest));
    await assert.rejects(verifyBundle(f.bundle),/unsafe file entry/);
  } finally { await cleanup(f); }
});

test('build-id encoding matches the Python builder for non-ASCII resource names',()=>{
  assert.equal(canonicalInventory({'étoile':'one','A':'two','🎨':'three'}),' {"A":"two","\\u00e9toile":"one","\\ud83c\\udfa8":"three"}'.trim());
});

test('updates hard-link unchanged files from the previous install and keep only recent installs',async()=>{
  const first = await fixture();
  try {
    const one = await installRelease(first);
    assert.deepEqual(one.staged,{linked:0,copied:5});
    const second = await fixture({root:first.root,name:'release-2',main:'export const version = 2;'});
    const two = await installRelease(second);
    assert.equal(two.staged.copied,2,'only the changed companion file and build info are copied');
    assert.equal((await stat(join(two.release,'runtime/bin/node'))).ino,(await stat(join(one.release,'runtime/bin/node'))).ino,'the runtime is shared, not duplicated');
    const third = await fixture({root:first.root,name:'release-3',main:'export const version = 3;'});
    const three = await installRelease({...third,keepBackups:1});
    const remaining = (await readdir(first.runtimeDestination)).filter(n=>/^[0-9a-f]{64}$/.test(n)).sort();
    assert.deepEqual(remaining,[second.manifest.build_id,third.manifest.build_id].sort(),'current and previous are kept');
    assert.deepEqual(three.pruned.releases,[first.manifest.build_id]);
    assert.equal((await readdir(dirname(three.backup))).length,1,'old plugin backups are pruned');
    assert.equal(await readFile(join(three.release,'runtime/bin/node'),'utf8'),'# test runtime','a pruned donor does not break the shared runtime');
    assert.equal(await readFile(join(first.project,'painting.kra'),'utf8'),'original artwork');
  } finally { await cleanup(first); }
});

test('a release that pins a managed Node installs without a runtime and points the panel at the shared one',async()=>{
  const f = await fixture({managed:true});
  try {
    const runtimes = join(dirname(f.runtimeDestination),'runtimes');
    await mkdir(join(runtimes,'node-v20.0.0-darwin-'+process.arch),{recursive:true});   // no longer pinned by any release
    const result = await installRelease(f);
    const settings = JSON.parse(await readFile(join(f.destination,'kritamcp/creative-agent-config.json'),'utf8'));
    assert.equal(settings.node,join(runtimes,'node-v22.23.2-darwin-'+process.arch,'bin/node'));
    assert.deepEqual(settings.node_runtime,f.manifest.node_runtime); assert.equal(settings.node_runtimes,runtimes);
    assert.deepEqual(await readdir(result.release),['companion','release-manifest.json'],'no runtime copied into the release');
    assert.deepEqual(result.pruned.runtimes,['node-v20.0.0-darwin-'+process.arch]);
  } finally { await cleanup(f); }
});
