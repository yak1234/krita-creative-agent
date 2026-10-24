// The test driver's copies: a project folder or reference images copied into a test chat's own folder, and the
// test-assets fixtures (a project folder prepared once, read only from its source). Files go to a temporary folder that
// is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, readdir, rm, symlink, writeFile, access, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { copyProjectFolder, copyReferences, TestAssets } from '../src/test-fixtures.ts';

async function project(root) {
  const folder = join(root, 'artist', 'moscow-painting-assets');
  await mkdir(join(folder, 'extra', 'deeper'), { recursive: true });
  for (const name of ['01-moonlit-sky.png', 'final_goal.png']) await writeFile(join(folder, name), 'png ' + name);
  await writeFile(join(folder, 'generation-prompts.json'), '{"01":"sky"}');
  await writeFile(join(folder, 'PLAN.md'), '# the artist’s plan');
  await writeFile(join(folder, 'PLAN.backup-2026-10-24.md'), 'old plan');
  await writeFile(join(folder, 'NOTES.md'), 'notes');
  await writeFile(join(folder, '.DS_Store'), 'x');
  await writeFile(join(folder, 'extra', 'a.png'), 'png a');
  await writeFile(join(folder, 'extra', 'deeper', 'b.png'), 'png b');
  await writeFile(join(root, 'secret.txt'), 'outside');
  await symlink(join(root, 'secret.txt'), join(folder, 'link.png'));
  return folder;
}
const tree = async folder => (await readdir(folder, { recursive: true })).sort();

test('a project folder is copied into the test chat’s folder: files and one level of subfolders, never links; the original untouched', async () => {
  const root = await mkdtemp(join(tmpdir(), 'test-fixtures-'));
  try {
    const source = await project(root), before = await tree(source);
    const copy = await copyProjectFolder(source, join(root, 'test-1', 'project'));
    assert.equal(copy, join(root, 'test-1', 'project', 'moscow-painting-assets'));
    assert.deepEqual(await tree(copy), ['01-moonlit-sky.png', 'NOTES.md', 'PLAN.backup-2026-10-24.md', 'PLAN.md', 'extra', 'extra/a.png', 'final_goal.png', 'generation-prompts.json']);
    assert.equal(await readFile(join(copy, 'final_goal.png'), 'utf8'), 'png final_goal.png');
    assert.deepEqual(await tree(source), before, 'nothing is written into the artist’s folder');
    await assert.rejects(copyProjectFolder(source, join(source, 'inside')), /inside the folder/, 'never a copy inside the original');
    await assert.rejects(access(join(source, 'inside')));
    await assert.rejects(copyProjectFolder(join(root, 'secret.txt'), join(root, 'test-2')), /not a folder/);
    await assert.rejects(copyProjectFolder('relative/folder', join(root, 'test-3')), /absolute/);
    await assert.rejects(copyProjectFolder(source, join(root, 'small'), { files: 3 }), /more than 3 files/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('reference images are copied into the test chat’s folder; anything else is refused', async () => {
  const root = await mkdtemp(join(tmpdir(), 'test-fixtures-'));
  try {
    const source = await project(root);
    const copies = await copyReferences([join(source, 'final_goal.png'), join(source, 'extra', 'a.png')], join(root, 'test-1', 'references'));
    assert.deepEqual(copies, [join(root, 'test-1', 'references', '1-final_goal.png'), join(root, 'test-1', 'references', '2-a.png')]);
    assert.equal(await readFile(copies[0], 'utf8'), 'png final_goal.png');
    const refuse = (paths, pattern) => assert.rejects(copyReferences(paths, join(root, 'refused')), pattern);
    await refuse(['final_goal.png'], /absolute/);
    await refuse([join(source, 'generation-prompts.json')], /PNG, JPEG or GIF/);
    await refuse([join(source, 'link.png')], /regular file/);
    await refuse([join(source, 'missing.png')], /regular file/);
    await refuse(Array(5).fill(join(source, 'final_goal.png')), /up to four/);
    await assert.rejects(access(join(root, 'refused')), 'a refused list copies nothing');
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('test assets: a fixture is prepared once from its source (images and prompts, no plan or notes), copied fresh per test, and removed', async () => {
  const root = await mkdtemp(join(tmpdir(), 'test-fixtures-'));
  try {
    const source = await project(root), before = await tree(source);
    const assets = new TestAssets(join(root, 'driver', 'test-assets'));
    assert.deepEqual(await assets.list(), []);
    const prepared = await assets.prepare(source);
    assert.equal(prepared.name, 'moscow-painting-assets'); assert.equal(prepared.prepared, true);
    const fixture = join(root, 'driver', 'test-assets', 'moscow-painting-assets');
    assert.deepEqual(await tree(fixture), ['01-moonlit-sky.png', 'extra', 'extra/a.png', 'final_goal.png', 'generation-prompts.json'],
      'a fresh plan: no PLAN.md, its backups or NOTES.md');
    assert.deepEqual(await tree(source), before, 'read only from the source');
    const mtime = (await stat(join(fixture, 'final_goal.png'))).mtimeMs;
    assert.equal((await assets.prepare(source)).prepared, false, 'prepared once');
    assert.equal((await stat(join(fixture, 'final_goal.png'))).mtimeMs, mtime);
    assert.deepEqual(await assets.list(), [{ name: 'moscow-painting-assets', folder: 'test-assets:moscow-painting-assets', files: 4 }]);
    assert.equal(await assets.resolve('test-assets:moscow-painting-assets'), fixture);
    assert.equal(await assets.resolve(join(root, 'elsewhere')), join(root, 'elsewhere'), 'a plain path is left alone');
    await assert.rejects(assets.resolve('test-assets:missing'), /creative_test_assets/);
    await assert.rejects(assets.resolve('test-assets:../artist'), /name/);
    await assert.rejects(assets.remove('../artist'), /name/);
    await assert.rejects(new TestAssets(join(source, 'test-assets')).prepare(source), /inside the folder/, 'never inside the source');
    assert.deepEqual(await assets.remove('moscow-painting-assets'), { status: 'ok', removed: 'moscow-painting-assets' });
    await assert.rejects(access(fixture));
    assert.deepEqual(await tree(source), before);
  } finally { await rm(root, { recursive: true, force: true }); }
});
