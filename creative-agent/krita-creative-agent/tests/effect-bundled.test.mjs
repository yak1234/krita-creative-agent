// The effects Toska ships (effects/fog.yaml, snow.yaml) and the build policy (effects/policy.yaml). Writes only its own temp folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEffects } from '../src/effects/library.ts';
import { parseRecipe, resolveBlocks } from '../src/effects/recipe.ts';
import { readPolicy } from '../src/effects/policy.ts';
import { DEFAULT_WIND, DEFAULT_KEEP_CLEAR } from '../src/snow-tool.ts';

const bundled = join(dirname(fileURLToPath(import.meta.url)), '..', 'effects');
const recipe = name => {
  const parsed = parseRecipe(readFileSync(join(bundled, `${name}.yaml`), 'utf8'), `${name}.yaml`);
  assert.ok('recipe' in parsed, 'error' in parsed ? parsed.error : '');
  return parsed.recipe;
};

test('the bundled effects and policy load with nothing skipped', async () => {
  const library = await loadEffects({ bundled, own: join(tmpdir(), 'effect-bundled-no-such-folder') });
  assert.deepEqual(library.skipped, []);
  assert.deepEqual([...library.effects.keys()].sort(), ['fog', 'snow']);
  assert.ok(library.effects.get('fog').cue.includes('fog'));
  assert.deepEqual(readPolicy(join(bundled, 'policy.yaml')),
    { failures_before_build: 2, candidates: 3, retries: 1, minutes: 4, preview_side: 1024, auto_keep_min_seconds: 20, token_effort: 40 });
});

test('fog is a wash from the bottom and a large noise, both scaled by density', () => {
  const fog = recipe('fog');
  assert.deepEqual(fog.options.density, { default: 1, min: 0.3, max: 2, describe: fog.options.density.describe });
  assert.equal(fog.options.height.default, 0.4);
  assert.equal(fog.options.height.min, 0.1);
  assert.equal(fog.options.height.max, 1);
  assert.ok(Math.abs(resolveBlocks(fog, {}).blocks[0].falloff - 0.6) < 1e-9);   // the default height fades over 0.6
  const { blocks } = resolveBlocks(fog, { density: 1.5, height: 0.4 });
  assert.deepEqual(blocks.map(b => b.block), ['wash', 'noise']);
  assert.equal(blocks[0].from, 'bottom');
  assert.ok(Math.abs(blocks[0].falloff - 0.6) < 1e-9);
  assert.equal(blocks[0].lower_contrast, 0.3);
  assert.equal(blocks[0].opacity, 0.75);
  assert.equal(blocks[1].scale, 'large');
  assert.equal(blocks[1].opacity, 0.375);
  assert.deepEqual(blocks[1].band, { from: 'bottom', share: 0.4 });
  assert.deepEqual(resolveBlocks(fog, { height: 0.7 }).blocks[1].band, { from: 'bottom', share: 0.7 });
});

test('snow.yaml resolves to what paint_snow sends', () => {
  const snow = recipe('snow');
  assert.deepEqual(snow.keep_clear, DEFAULT_KEEP_CLEAR);
  const { blocks, notes } = resolveBlocks(snow, {});
  assert.deepEqual(notes, []);
  const falling = blocks.find(b => b.block === 'particles');
  assert.equal(falling.density, 1);
  assert.equal(falling.wind_deg, DEFAULT_WIND);
  assert.equal(falling.layers, 3);
  const caps = blocks.find(b => b.block === 'caps');
  assert.equal(caps.part, 'settle_on');       // the tool expands this to each part the painter names (Task 5)
  assert.equal(caps.thickness, 1);
  const heavy = resolveBlocks(snow, { density: 2, wind_deg: -20, thickness: 1.6 }).blocks;
  assert.equal(heavy.find(b => b.block === 'particles').density, 2);
  assert.equal(heavy.find(b => b.block === 'particles').wind_deg, -20);
  assert.equal(heavy.find(b => b.block === 'caps').thickness, 1.6);
});

test('readPolicy gives the defaults for a missing, broken or out-of-range file and never throws', async () => {
  const defaults = readPolicy(join(bundled, 'policy.yaml'));
  const root = await mkdtemp(join(tmpdir(), 'effect-policy-'));
  try {
    assert.deepEqual(readPolicy(join(root, 'absent.yaml')), defaults);
    await writeFile(join(root, 'broken.yaml'), 'candidates: [3\n');
    assert.deepEqual(readPolicy(join(root, 'broken.yaml')), defaults);
    await writeFile(join(root, 'list.yaml'), '- 1\n- 2\n');
    assert.deepEqual(readPolicy(join(root, 'list.yaml')), defaults);
    await writeFile(join(root, 'wild.yaml'), 'candidates: 99\nminutes: -1\nretries: "x"\npreview_side: 512\n');
    assert.deepEqual(readPolicy(join(root, 'wild.yaml')), { ...defaults, preview_side: 512 });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
