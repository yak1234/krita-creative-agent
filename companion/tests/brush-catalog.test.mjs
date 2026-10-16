// Measured brush catalog: consistent with itself, in the painter's prompt, and on every list_brushes result. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { CATALOG, brushCards, brushGuide } from '../src/brush-catalog.mjs';
import { PAINTING_INSTRUCTIONS } from '../src/prompt.mjs';
import { paintingTools } from '../src/tools.mjs';

test('every recommended or avoided preset was probed, and none is both', () => {
  const recommended = Object.values(CATALOG.jobs).flat(), avoided = Object.values(CATALOG.avoid).flat();
  for (const name of [...recommended, ...avoided]) assert.ok(CATALOG.cards[name], 'no card for ' + name);
  assert.deepEqual(recommended.filter(name => avoided.includes(name)), []);
  assert.ok(Object.keys(CATALOG.cards).length >= 150, 'the whole default library and the installed bundles');
});

test('the painter is told which presets fit which job and which to avoid', () => {
  assert.ok(PAINTING_INSTRUCTIONS.includes(brushGuide()));
  assert.match(brushGuide(), /hair strands: y\) Texture Hair/);
  assert.match(brushGuide(), /ignore the chosen colour: .*Stamp Hearts/);
});

test('list_brushes returns the whole library with a card per preset, within the plugin\'s parameters', async () => {
  const names = Array.from({ length: 154 }, (_, i) => i === 0 ? 'i) Wet Paint' : 'Preset ' + i);
  const calls = [];
  const runtime = { faulted: false, study: { directory: '/nonexistent', references: [] }, emit() {},
    async callNative(operation, params) { calls.push({ operation, params }); if (Object.keys(params).some(k => k !== 'filter')) throw new Error('ValueError: Unknown parameters'); return { status: 'ok', brushes: names, count: 154, total: 154 }; } };
  const result = await paintingTools(runtime).find(t => t.name === 'list_brushes').execute('id', {}, undefined);
  assert.deepEqual(calls[0].params, {}, 'the plugin accepts only filter (a limit failed every live call)');
  const listed = JSON.parse(result.content[0].text).brushes;
  assert.equal(listed.length, 154, 'not truncated by the result budget');
  assert.match(listed[0].card, /washed out and grainy/);
  assert.equal(listed[1].card, null, 'an unprobed preset says so');
  assert.deepEqual(brushCards(['b) Basic-1']), [{ name: 'b) Basic-1', card: CATALOG.cards['b) Basic-1'] }]);
});
