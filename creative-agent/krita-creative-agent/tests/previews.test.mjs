import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readdir, rm, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { prunePreviews, pruneAllPreviews, removeRebuildable } from '../src/previews.mjs';

const view = n => 'view-' + n.toString(16).padStart(32, '0') + '.png';

async function study(root, id, count) {
  const directory = join(root, id), previews = join(directory, '.previews');
  await mkdir(previews, { recursive: true });
  for (let n = 0; n < count; n++) {
    const file = join(previews, view(n));
    await writeFile(file, Buffer.alloc(100));
    await utimes(file, 1000 + n, 1000 + n);          // older files have lower numbers
  }
  return directory;
}

test('prune keeps referenced, latest-pass and newest previews and deletes the rest', async () => {
  const root = await mkdtemp(join(tmpdir(), 'previews-'));
  try {
    const directory = await study(root, 'a', 30);
    await writeFile(join(directory, 'study.json'), JSON.stringify({ last_image: '.previews/' + view(0) }));
    await mkdir(join(directory, 'reviews'));
    await writeFile(join(directory, 'reviews', 'r.json'), JSON.stringify({ image: join(directory, '.previews', view(1)) }));
    const passes = [2, 4, 6].map(n => ({ before_path: '.previews/' + view(n), after_path: '.previews/' + view(n + 1) }));
    await writeFile(join(directory, '.passes.json'), JSON.stringify(passes));
    const dry = await prunePreviews(directory, { keepPasses: 2, keepRecent: 5, dryRun: true });
    assert.equal((await readdir(join(directory, '.previews'))).length, 30, 'a dry run deletes nothing');
    const result = await prunePreviews(directory, { keepPasses: 2, keepRecent: 5 });
    assert.deepEqual(result, dry);
    const left = (await readdir(join(directory, '.previews'))).sort();
    // study + review (0, 1), the last two passes (4-7) and the five newest (25-29); pass 2-3 is too old
    assert.deepEqual(left, [0, 1, 4, 5, 6, 7, 25, 26, 27, 28, 29].map(view));
    assert.equal(result.removed, 19); assert.equal(result.bytes, 1900); assert.equal(result.kept, 11);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('prune handles JPEG views like PNG ones', async () => {
  const root = await mkdtemp(join(tmpdir(), 'previews-'));
  try {
    const directory = join(root, 'a'), previews = join(directory, '.previews');
    await mkdir(previews, { recursive: true });
    const jpg = n => view(n).replace('.png', '.jpg');
    for (let n = 0; n < 4; n++) { await writeFile(join(previews, jpg(n)), Buffer.alloc(10)); await utimes(join(previews, jpg(n)), 1000 + n, 1000 + n); }
    await writeFile(join(directory, 'goal.json'), JSON.stringify({ image: '.previews/' + jpg(0) }));
    const result = await prunePreviews(directory, { keepRecent: 1 });
    assert.deepEqual((await readdir(previews)).sort(), [jpg(0), jpg(3)]);
    assert.equal(result.removed, 2);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('prune all skips the active study and folders without previews', async () => {
  const root = await mkdtemp(join(tmpdir(), 'previews-'));
  try {
    await study(root, 'old', 10); await study(root, 'active', 10); await mkdir(join(root, 'empty'));
    const totals = await pruneAllPreviews(root, { active: 'active', keepRecent: 2 });
    assert.deepEqual(totals, { studies: 1, kept: 2, removed: 8, bytes: 800 });
    assert.equal((await readdir(join(root, 'active', '.previews'))).length, 10);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('rebuildable files go: stored stroke plans and reduced references; jobs and attachments stay', async () => {
  const root = await mkdtemp(join(tmpdir(), 'previews-'));
  try {
    const directory = join(root, 'chat'), plans = join(directory, 'reference-paintings'), reduced = join(directory, '.model-references');
    await mkdir(plans, { recursive: true }); await mkdir(reduced);
    await writeFile(join(plans, 'a'.repeat(32) + '.plan.json'), Buffer.alloc(500));
    await writeFile(join(plans, 'a'.repeat(32) + '.json'), '{}');
    await writeFile(join(reduced, 'x-1568.jpg'), Buffer.alloc(50));
    await writeFile(join(directory, 'reference-1.png'), Buffer.alloc(10));
    assert.deepEqual(await removeRebuildable(directory, { dryRun: true }), { removed: 2, bytes: 550 });
    assert.deepEqual(await removeRebuildable(directory), { removed: 2, bytes: 550 });
    assert.deepEqual(await readdir(plans), ['a'.repeat(32) + '.json']);
    assert.deepEqual((await readdir(directory)).sort(), ['reference-1.png', 'reference-paintings']);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('a closed chat keeps only previews its record points to and the two newest', async () => {
  const root = await mkdtemp(join(tmpdir(), 'previews-'));
  try {
    const directory = await study(root, 'closed', 30);
    await writeFile(join(directory, '.passes.json'), JSON.stringify([{ before_path: '.previews/' + view(10), after_path: '.previews/' + view(11) }]));
    const record = JSON.stringify({ study: { last_image: 'chat:.previews/' + view(5) } });
    const result = await prunePreviews(directory, { extraText: record });
    assert.deepEqual((await readdir(join(directory, '.previews'))).sort(), [5, 28, 29].map(view), 'pass pictures go too');
    assert.equal(result.removed, 27);
  } finally { await rm(root, { recursive: true, force: true }); }
});
