// Effect recipes (openspec custom-effects): the schema, the arithmetic on a recipe's own options and the caps. No Krita, no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseRecipe, evaluate, resolveBlocks } from '../src/effects/recipe.ts';

const FOG = `
name: fog
cue: low mist lying on the ground
lesson: mist thins with height
options:
  density: { default: 1, min: 0.2, max: 2, describe: how thick }
blocks:
  - block: wash
    from: bottom
    opacity: "0.5 * density"
  - block: particles
    count: "1000 * density"
    wind_deg: 5
`;

const parsed = (text, file = 'x.yaml') => parseRecipe(text, file);

test('fog parses and resolves with its defaults', () => {
  const r = parsed(FOG);
  assert.ok('recipe' in r, JSON.stringify(r));
  assert.deepEqual(r.recipe.keep_clear, ['faces', 'hair']);
  const { blocks, notes } = resolveBlocks(r.recipe, {});
  assert.deepEqual(notes, []);
  assert.deepEqual(blocks, [{ block: 'wash', from: 'bottom', opacity: 0.5 }, { block: 'particles', count: 1000, wind_deg: 5 }]);
  const more = resolveBlocks(r.recipe, { density: 2 });
  assert.equal(more.blocks[0].opacity, 1);
  const beyond = resolveBlocks(r.recipe, { density: 9, nothing: 1 });
  assert.equal(beyond.blocks[0].opacity, 1);
  assert.ok(beyond.notes.some(n => n.startsWith('density: 9 asked, 2 used')));
  assert.ok(beyond.notes.some(n => n.startsWith('nothing:')));
});

test('expressions allow only numbers, option names, + - * /, parentheses, min and max', () => {
  assert.equal(evaluate('0.5 * density', { density: 1 }), 0.5);
  assert.equal(evaluate('-(1 + 2) * 3 - 4 / 2', {}), -11);
  assert.equal(evaluate('min(density, 2) + max(1, 3, 2)', { density: 5 }), 5);
  assert.equal(evaluate(7, {}), 7);
  for (const bad of ['process.exit()', 'density.constructor', '1e9 ** 9', 'constructor', 'toString', '(0.5', '0.5)', '1 +', '', '1 / 0',
    'x', 'density[0]', '"a"', 'min(1', '1 2', 'a = 1', '`1`', '__proto__']) {
    assert.throws(() => evaluate(bad, { density: 1 }), undefined, bad);
  }
  assert.throws(() => evaluate('('.repeat(500) + '1' + ')'.repeat(500), {}));
  assert.throws(() => evaluate(NaN, {}));
});

test('a broken recipe is skipped with its file and field named', () => {
  const message = (text) => { const r = parsed(text, 'bad.yaml'); assert.ok('error' in r, text); return r.error; };
  assert.match(message(FOG.replace('block: wash', 'block: smoke')), /^bad\.yaml: blocks\[0\]\.block: .*smoke/);
  assert.match(message(FOG.replace('min: 0.2, max: 2', 'min: 3, max: 2')), /^bad\.yaml: options\.density\.min/);
  assert.match(message(FOG.replace('"0.5 * density"', '"(0.5"')), /^bad\.yaml: blocks\[0\]\.opacity: /);
  assert.match(message(FOG.replace('"0.5 * density"', '"0.5 * thickness"')), /^bad\.yaml: blocks\[0\]\.opacity: .*thickness/);
  assert.match(message(FOG.replace('from: bottom', 'from: middle')), /^bad\.yaml: blocks\[0\]\.from/);
  assert.match(message(FOG.replace('wind_deg: 5', 'windy: 5')), /^bad\.yaml: blocks\[1\]\.windy/);
  assert.match(message(FOG.replace('name: fog', 'name: Fog Bank')), /^bad\.yaml: name/);
  assert.match(message(FOG.replace('default: 1,', 'default: 5,')), /^bad\.yaml: options\.density\.default/);
  assert.match(message(FOG.replace('name: fog', 'colour: red\nname: fog')), /^bad\.yaml: colour/);
  assert.match(message('name: fog\ncue: x\n'), /^bad\.yaml: blocks/);
  assert.match(message('blocks: [\n'), /^bad\.yaml: not valid YAML/);
  assert.match(message('- 1\n- 2\n'), /^bad\.yaml: /);
  assert.match(message(FOG.replace('options:', 'options:\n  min: { default: 1, min: 0, max: 2 }')), /options\.min/);
  assert.match(message('name: t\ncue: c\nblocks:\n  - block: caps\n'), /blocks\[0\]\.part/);
  assert.match(message('name: t\ncue: c\nblocks:\n  - block: texture\n    part: x\n'), /^bad\.yaml: blocks\[0\]/);
});

test('every block parses with exactly the plugin keys', () => {
  const text = `
name: all
cue: every block
blocks:
  - { block: particles, layers: 2, density: 1, count: 10, wind_deg: -5, streak: 2, colour: local, opacity: 0.5, within: ground }
  - { block: wash, from: top, falloff: 0.3, lower_contrast: 0.2 }
  - { block: noise, scale: large }
  - { block: rays, from_point: [0.5, "0.1 + 0.1"], count: 8, spread_deg: 40 }
  - { block: rays, from: left }
  - { block: texture, area: wall, blend: screen }
  - { block: caps, part: hats, thickness: 1.5 }
`;
  const r = parsed(text);
  assert.ok('recipe' in r, JSON.stringify(r));
  const { blocks } = resolveBlocks(r.recipe, {});
  assert.deepEqual(blocks[3].from_point, [0.5, 0.2]);
  assert.equal(blocks[0].within, 'ground');
  assert.equal(blocks[5].area, 'wall');
});

test('values beyond the caps are clamped and said', () => {
  const many = Array.from({ length: 12 }, () => '  - { block: noise }').join('\n');
  const r = parsed(`name: big\ncue: c\nblocks:\n  - { block: particles, count: "1e9", layers: 9 }\n`);
  assert.ok('error' in r);                                                     // 1e9 is not a number in the reader
  const big = parsed(`name: big\ncue: c\nblocks:\n  - { block: particles, count: 1000000000, layers: 9, opacity: 7 }\n${many}\n`);
  assert.ok('recipe' in big, JSON.stringify(big));
  const { blocks, notes } = resolveBlocks(big.recipe, {});
  assert.equal(blocks.length, 8);
  assert.equal(blocks[0].count, 60000);
  assert.equal(blocks[0].layers, 3);
  assert.equal(blocks[0].opacity, 1);
  assert.ok(notes.some(n => /count: 1000000000 asked, 60000 used/.test(n)));
  assert.ok(notes.some(n => /layers: 9 asked, 3 used/.test(n)));
  assert.ok(notes.some(n => /opacity: 7 asked, 1 used/.test(n)));
  assert.ok(notes.some(n => /blocks: 13 asked/.test(n)));
  const fifty = Array.from({ length: 51 }, () => '  - { block: noise }').join('\n');
  assert.ok('error' in parsed(`name: big\ncue: c\nblocks:\n${fifty}\n`));
});

test('cue, lesson and evidence over their lengths are refused', () => {
  const head = (extra) => `name: t\ncue: ${extra.cue ?? 'ok'}\n${extra.lesson ? 'lesson: ' + extra.lesson + '\n' : ''}${extra.evidence ? 'evidence: ' + extra.evidence + '\n' : ''}blocks:\n  - { block: noise }\n`;
  assert.ok('recipe' in parsed(head({ cue: 'c'.repeat(160), lesson: 'l'.repeat(300), evidence: 'e'.repeat(300) })));
  assert.match(parsed(head({ cue: 'c'.repeat(161) }), 'f.yaml').error, /^f\.yaml: cue/);
  assert.match(parsed(head({ lesson: 'l'.repeat(301) }), 'f.yaml').error, /^f\.yaml: lesson/);
  assert.match(parsed(head({ evidence: 'e'.repeat(301) }), 'f.yaml').error, /^f\.yaml: evidence/);
});

test('YAML aliases and tags do not run anything', () => {
  assert.ok('error' in parsed('name: t\ncue: &a c\nlesson: *a\nblocks:\n  - { block: noise }\n'));
  assert.ok('error' in parsed('name: !!js/function "x"\ncue: c\nblocks:\n  - { block: noise }\n'));
});

test('every resolved number is one the plugin accepts, and resolving never throws', () => {
  const r = parsed(`name: wild\ncue: c\noptions:\n  d: { default: 2, min: 0, max: 5 }\nblocks:\n  - { block: particles, density: 1e30 }\n  - { block: wash, falloff: "999999999999 * 999999999999", lower_contrast: "1 / d" }\n  - { block: rays, from_point: [1000000000000000, "1/(d-1)"] }\n`);
  assert.ok('recipe' in r, JSON.stringify(r));
  const { blocks, notes } = resolveBlocks(r.recipe, { d: 0 });
  assert.equal(blocks[0].density, 1e12);
  assert.equal(blocks[1].falloff, 1e12);
  assert.equal(blocks[1].lower_contrast, 0.5);                // 1/d at d=0: the value at the defaults
  assert.equal(blocks[2].from_point[0], 1e12);
  assert.ok(notes.some(n => /density: 1e\+30 asked, 1000000000000 used/.test(n)));
  assert.ok(notes.some(n => /lower_contrast: division by zero/.test(n)));
  const same = resolveBlocks(r.recipe, { d: 1 });             // 1/(d-1) at 1 fails too; no throw
  assert.ok(same.notes.some(n => /from_point/.test(n)));
});

test('noise takes a band whose share is an expression clamped to 0..1; no other block takes one', () => {
  const text = share => `name: t\ncue: c\noptions:\n  h: { default: 0.4, min: 0, max: 5 }\nblocks:\n  - { block: noise, band: { from: bottom, share: ${share} } }\n`;
  const parsed = parseRecipe(text('h * 2'), 'b.yaml');
  assert.ok('recipe' in parsed);
  assert.deepEqual(resolveBlocks(parsed.recipe, {}).blocks[0].band, { from: 'bottom', share: 0.8 });
  const over = resolveBlocks(parsed.recipe, { h: 3 });
  assert.deepEqual(over.blocks[0].band, { from: 'bottom', share: 1 });
  assert.ok(over.notes.some(n => n.includes('band share')));
  assert.ok('error' in parseRecipe(text('nope'), 'b.yaml'));
  assert.ok('error' in parseRecipe(text('0.5').replace('from: bottom', 'from: middle'), 'b.yaml'));
  assert.ok('error' in parseRecipe('name: t\ncue: c\nblocks:\n  - { block: wash, band: { from: bottom, share: 0.5 } }\n', 'b.yaml'));
});

test('a part, area, within or keep_clear name that is only spaces is refused (the plugin refuses it)', () => {
  const message = (text) => { const r = parsed(text, 'blank.yaml'); assert.ok('error' in r, text); return r.error; };
  assert.match(message('name: t\ncue: c\nblocks:\n  - { block: caps, part: "   " }\n'), /^blank\.yaml: blocks\[0\]\.part: is a name, not only spaces/);
  assert.match(message('name: t\ncue: c\nblocks:\n  - { block: texture, area: " \\t" }\n'), /^blank\.yaml: blocks\[0\]\.area/);
  assert.match(message('name: t\ncue: c\nblocks:\n  - { block: wash, within: "  " }\n'), /^blank\.yaml: blocks\[0\]\.within/);
  assert.match(message('name: t\ncue: c\nkeep_clear: ["faces", " "]\nblocks:\n  - { block: wash }\n'), /^blank\.yaml: keep_clear/);
  assert.ok('recipe' in parsed('name: t\ncue: c\nkeep_clear: [faces]\nblocks:\n  - { block: caps, part: " roof " }\n'), 'words with spaces around them pass');
});
