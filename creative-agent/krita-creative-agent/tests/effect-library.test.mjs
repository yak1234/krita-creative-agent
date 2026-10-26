// The effect library (openspec custom-effects): bundled and own folders, skipping, saving and resetting. Every test removes its folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadEffects, saveEffect, removeEffect, resetEffects } from '../src/effects/library.ts';
import { parseRecipe } from '../src/effects/recipe.ts';
import { StudioRuntime } from '../src/studio.mjs';

const recipe = (name, cue = 'a cue') => `name: ${name}\ncue: ${cue}\nblocks:\n  - { block: noise }\n`;

async function withFolders(run) {
  const root = await mkdtemp(join(tmpdir(), 'effect-library-'));
  try {
    const bundled = join(root, 'bundled'), own = join(root, 'own');
    await mkdir(bundled); await mkdir(own);
    await run({ bundled, own, root });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test('a broken recipe is skipped with its file named and the others load', () => withFolders(async ({ bundled, own }) => {
  await writeFile(join(bundled, 'fog.yaml'), recipe('fog'));
  await writeFile(join(bundled, 'policy.yaml'), 'candidates: 3\n');
  await writeFile(join(bundled, 'bad.yaml'), 'name: bad\ncue: c\nblocks:\n  - { block: smoke }\n');
  await writeFile(join(own, 'mine.yaml'), recipe('mine'));
  await writeFile(join(own, 'notes.txt'), 'ignored');
  const { effects, skipped } = await loadEffects({ bundled, own });
  assert.deepEqual([...effects.keys()].sort(), ['fog', 'mine']);
  assert.equal(skipped.length, 1);
  assert.match(skipped[0], /^bad\.yaml: blocks\[0\]\.block/);
  assert.equal(effects.get('mine').source, 'own');
  assert.equal(effects.get('fog').file, join(bundled, 'fog.yaml'));
}));

test('missing folders are an empty library', async () => {
  const { effects, skipped } = await loadEffects({ bundled: join(tmpdir(), 'no-such-bundled-folder'), own: join(tmpdir(), 'no-such-own-folder') });
  assert.equal(effects.size, 0);
  assert.deepEqual(skipped, []);
});

test('own effects override bundled ones by name', () => withFolders(async ({ bundled, own }) => {
  await writeFile(join(bundled, 'fog.yaml'), recipe('fog', 'bundled cue'));
  await writeFile(join(own, 'my-fog.yaml'), recipe('fog', 'own cue'));
  const { effects } = await loadEffects({ bundled, own });
  assert.equal(effects.size, 1);
  assert.equal(effects.get('fog').cue, 'own cue');
  assert.equal(effects.get('fog').source, 'own');
}));

test('save writes atomically, round-trips, remove deletes, bad names are refused', () => withFolders(async ({ own, root }) => {
  const parsed = parseRecipe(recipe('rain-2'), 'x.yaml');
  const file = await saveEffect(join(own, 'deeper'), { ...parsed.recipe, auto_kept: true });
  assert.equal(file, join(own, 'deeper', 'rain-2.yaml'));
  assert.deepEqual(await readdir(join(own, 'deeper')), ['rain-2.yaml']);       // no temp file left
  const back = parseRecipe(await readFile(file, 'utf8'), 'rain-2.yaml');
  assert.equal(back.recipe.auto_kept, true);
  assert.equal((await loadEffects({ bundled: join(root, 'none'), own: join(own, 'deeper') })).effects.get('rain-2').cue, 'a cue');
  for (const name of ['../evil', 'Rain', 'a/b', '', 'a b', 'x.yaml']) {
    await assert.rejects(saveEffect(own, { ...parsed.recipe, name }), /lowercase/, name);
    await assert.rejects(removeEffect(own, name), /lowercase/, name);
  }
  await assert.rejects(saveEffect(own, { ...parsed.recipe, cue: 'c'.repeat(200) }), /cue/);
  assert.deepEqual(await readdir(own), ['deeper']);
  assert.equal(await removeEffect(join(own, 'deeper'), 'rain-2'), true);
  assert.equal(await removeEffect(join(own, 'deeper'), 'rain-2'), false);
}));

test('remove finds the effect by its name, in whatever file, and says false when nothing was removed', () => withFolders(async ({ own }) => {
  await writeFile(join(own, 'my-rain.yaml'), recipe('rain'));                 // rain, in a file named otherwise
  await writeFile(join(own, 'rain.yaml'), recipe('drizzle'));                 // a file named rain holding drizzle
  await writeFile(join(own, 'rain.texture.png'), 'png');
  assert.equal(await removeEffect(own, 'rain'), true);
  assert.deepEqual((await readdir(own)).sort(), ['rain.yaml'], 'rain and its texture gone; drizzle stays');
  assert.equal(await removeEffect(own, 'rain'), false, 'nothing named rain is left');
  assert.equal(await removeEffect(join(own, 'no-such-folder'), 'rain'), false);
  assert.equal(await removeEffect(own, 'drizzle'), true);
  assert.deepEqual(await readdir(own), []);
}));

test('reset deletes only the artist\'s folder', () => withFolders(async ({ bundled, own }) => {
  await writeFile(join(bundled, 'fog.yaml'), recipe('fog'));
  await writeFile(join(own, 'a.yaml'), recipe('a'));
  await writeFile(join(own, 'b.yaml'), recipe('b'));
  await writeFile(join(own, 'keep.txt'), 'not a recipe');
  await writeFile(join(own, 'a.texture.png'), 'a kept texture');
  assert.equal(await resetEffects(own), 2);
  assert.deepEqual(await readdir(own), ['keep.txt'], 'recipes and their textures, nothing else');
  assert.deepEqual(await readdir(bundled), ['fog.yaml']);
  assert.equal(await resetEffects(join(own, 'missing')), 0);
}));

test('Reset custom effects (the panel\'s reset_effects): the artist\'s folder emptied and the count said', () => withFolders(async ({ bundled, root }) => {
  const own = join(root, 'data', 'effects');
  await mkdir(own, { recursive: true });
  await writeFile(join(bundled, 'fog.yaml'), recipe('fog'));
  await writeFile(join(own, 'rain.yaml'), recipe('rain'));
  await writeFile(join(own, 'mist.yaml'), recipe('mist'));
  const events = [];
  const studio = { config: { data_dir: join(root, 'data') }, emit: e => events.push(e) };
  await StudioRuntime.prototype.resetEffects.call(studio);
  assert.deepEqual(await readdir(own), []);
  assert.deepEqual(await readdir(bundled), ['fog.yaml'], 'the bundled effects stay');
  assert.deepEqual(events, [{ type: 'action', seconds: 0, message: 'Reset custom effects: removed 2 of your effects. Fog and snow stay.' }]);
  events.length = 0;
  await StudioRuntime.prototype.resetEffects.call(studio);
  assert.deepEqual(events, [{ type: 'action', seconds: 0, message: 'Reset custom effects: you had no effects of your own to remove.' }]);
  events.length = 0;
  await StudioRuntime.prototype.resetEffects.call({ config: {}, emit: e => events.push(e) });
  assert.deepEqual(events, [{ type: 'action', seconds: 0, message: 'Reset custom effects: you had no effects of your own to remove.' }], 'no data folder: nothing to remove');
}));
