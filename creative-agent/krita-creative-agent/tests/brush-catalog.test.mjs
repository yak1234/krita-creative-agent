// Measured brush catalog: consistent with itself, in the painter's prompt, and on every list_brushes result. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { CATALOG, brushCards, brushGuide } from '../src/brush-catalog.mjs';
import { PAINTING_INSTRUCTIONS } from '../src/prompt.mjs';
import { paintingTools } from '../src/tools.mjs';
import { agentMoveInstructions } from '../src/studio.mjs';
import { readdirSync, readFileSync } from 'node:fs';

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

test('the painter finds an existing area with a seed instead of measuring it', () => {
  assert.match(PAINTING_INSTRUCTIONS, /seed step/);
});

// The painter prompt in sections, with a job → Krita feature guide; worked examples live in skills.
const PROMPT_BASELINE = 13330;          // PAINTING_INSTRUCTIONS.length before the sections (krita-native-tools Task 5)
const section = name => {
  const start = PAINTING_INSTRUCTIONS.indexOf(`<${name}>`), end = PAINTING_INSTRUCTIONS.indexOf(`</${name}>`);
  assert.ok(start >= 0 && end > start, `section ${name}`);
  return PAINTING_INSTRUCTIONS.slice(start, end);
};

test('the painter prompt is organised in named sections and does not grow', () => {
  const order = ['role', 'choosing_a_tool', 'tool_calling', 'protection'].map(name => PAINTING_INSTRUCTIONS.indexOf(`<${name}>`));
  assert.ok(order.every(i => i >= 0), 'every section present');
  assert.deepEqual([...order].sort((a, b) => a - b), order, 'in this order');
  assert.ok(PAINTING_INSTRUCTIONS.length <= PROMPT_BASELINE, `${PAINTING_INSTRUCTIONS.length} > ${PROMPT_BASELINE}`);
});

test('choosing a tool puts Krita’s features before strokes', () => {
  const guide = section('choosing_a_tool');
  for (const name of ['seed', 'split_by_color', 'fill_region', 'create_layer', 'apply_filter', 'clone_layer', 'krita_action', 'colortoalpha'])
    assert.ok(guide.includes(name), name);
  assert.match(guide, /mask/);
  assert.match(guide, /strokes for marks, edges, texture and detail/);
  assert.match(guide, /Flips: transform_layer with a negative scale/, 'flips work on any Krita, with or without vetted actions');
});

test('tool calling: name the Krita method first, and do not look again without a change', () => {
  const rules = section('tool_calling');
  assert.match(rules, /name the Krita method/i);
  assert.match(rules, /without a change/);
});

test('every bundled skill has a trigger line in the prompt', () => {
  const skills = readdirSync(new URL('../skills/', import.meta.url), { withFileTypes: true }).filter(d => d.isDirectory()).map(d => d.name);
  assert.ok(skills.includes('repaint-area') && skills.includes('repeat-motif'));
  for (const name of skills) assert.ok(PAINTING_INSTRUCTIONS.includes(`load the \`${name}\` skill`), name);
});

test('the worked examples are skills with their trigger in the description', () => {
  const read = name => readFileSync(new URL(`../skills/${name}/SKILL.md`, import.meta.url), 'utf8');
  for (const name of ['repaint-area', 'repeat-motif']) {
    const text = read(name);
    assert.match(text, new RegExp(`^---\\nname: ${name}\\ndescription: .*Use (when|for) `, 'm'), name);
  }
  const repaint = read('repaint-area');
  for (const step of ['seed', 'split_by_color', 'fill_region', 'apply_filter', 'clip_to', 'sky', 'windows', 'street']) assert.ok(repaint.includes(step), step);
  const repeat = read('repeat-motif');
  for (const step of ['clone_layer', 'offset', 'krita_action', 'mirrorNodeX', 'transform_layer']) assert.ok(repeat.includes(step), step);
  assert.match(read('paint-sky'), /seed|split_by_color/);
  assert.match(read('fix-region'), /seed|split_by_color/);
});

test('batch guidance no longer sends a sky or mass to stroke recipes', () => {
  const text = agentMoveInstructions('subject');
  assert.doesNotMatch(text, /For a sky, background or large mass, use paint_recipe/);
  assert.match(text, /fill_region/);
});

test('guidance moved out of the prompt was moved, not dropped', () => {
  const painting = section('painting');
  for (const kept of [/not facial anatomy/, /opaque/, /forehead, nose, lips and chin/, /shoulder slope and hand contact/, /cubic curves or pressure strokes/])
    assert.match(painting, kept);
});

test('a hard-edged patch is repaired from its own edge, never through a rectangle on clouds', () => {
  const fix = readFileSync(new URL('../skills/fix-region/SKILL.md', import.meta.url), 'utf8');
  assert.match(fix, /seed step inside the patch/);
  assert.match(fix, /grow/);
  assert.match(fix, /never a rectangle/i);
});

test('an area that already has form is refined, not replaced', () => {
  assert.match(section('choosing_a_tool'), /already has form.*add to it/s);
  const repaint = readFileSync(new URL('../skills/repaint-area/SKILL.md', import.meta.url), 'utf8');
  assert.match(repaint, /Refine or replace/);
  const fix = readFileSync(new URL('../skills/fix-region/SKILL.md', import.meta.url), 'utf8');
  assert.match(fix, /keep the forms around it/);
});

test('the protection section asks for a named area before a broad pass over a focal feature', () => {
  const protection = section('protection');
  assert.match(protection, /before a broad pass over a focal feature/);
  assert.match(protection, /propose_protection/);
  for (const skill of ['repaint-area', 'fix-region', 'paint-sky'])
    assert.match(readFileSync(new URL(`../skills/${skill}/SKILL.md`, import.meta.url), 'utf8'), /propose_protection for any focal feature/, skill);
});
