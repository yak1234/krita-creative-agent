// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Materials chosen in the plan (src/plan-materials.ts, architecture-texture goal 7): per aspect of an architectural
// "Refine: <group>" step a catalogue material, checked against the catalogue (unknown ones dropped and reported), shown in
// plain words, and used by the texture pass instead of asking the model at paint time. Pure functions; no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { ASPECTS, aspectOf, cleanMaterials, cleanPlanSteps, materialsLine, materialCatalogue, plannedChoice } from '../src/plan-materials.ts';

const canvas = { width: 6000, height: 4500 };

test('aspects follow the part kinds', () => {
  assert.deepEqual([...ASPECTS], ['walls', 'roofs', 'windows', 'ground', 'trim']);
  assert.equal(aspectOf('church'), 'walls');
  assert.equal(aspectOf('dome'), 'roofs');
  assert.equal(aspectOf('street'), 'ground');
  assert.equal(aspectOf('railing'), 'trim');
});

test('planned materials: ids or material names resolved, unknown ones dropped and reported, one per aspect', () => {
  const { materials, dropped } = cleanMaterials([
    { aspect: 'walls', id: 'ph_castle_brick_02_red', scale: 'coarse' },
    { aspect: 'roofs', id: 'rusty green metal' },
    { aspect: 'walls', id: 'Bricks085' },
    { aspect: 'ground', id: 'Moon dust' },
    { aspect: 'sky', id: 'Bricks085' },
    { aspect: 'windows', id: 'Facade013', recedes: true },
  ]);
  assert.deepEqual(materials.map(m => [m.aspect, m.id]), [['walls', 'ph_castle_brick_02_red'], ['roofs', 'ph_green_metal_rust'], ['windows', 'Facade013']]);
  assert.equal(materials[0].material, 'old red castle brick');
  assert.equal(materials[0].scale, 'coarse');
  assert.equal(materials[2].recedes, true);
  assert.equal(dropped.length, 3);
  assert.ok(dropped.some(d => /Moon dust/.test(d)) && dropped.some(d => /sky/.test(d)) && dropped.some(d => /walls/.test(d)));
});

test('only an architectural refine step keeps its materials', () => {
  const steps = [{ title: 'Finish', done_when: 'x', materials: [{ aspect: 'walls', id: 'Bricks085' }] },
    { title: 'Refine: Kremlin wall and towers', done_when: 'y', materials: [{ aspect: 'walls', id: 'ph_castle_brick_02_red' }, { aspect: 'roofs', id: 'Nope' }] }];
  const { steps: cleaned, dropped } = cleanPlanSteps(steps, step => /^Refine:/.test(step.title));
  assert.equal(cleaned[0].materials, undefined);
  assert.deepEqual(cleaned[1].materials.map(m => m.id), ['ph_castle_brick_02_red']);
  assert.equal(dropped.length, 2);
  assert.match(dropped.join(' '), /step 2/);
});

test('a refine step of people, vehicles or sky only keeps no materials (live test, 2026-10-25: the woman and the car got metal and snow)', () => {
  const steps = [{ title: 'Refine: Woman back view and vintage convertible', done_when: 'x', materials: [{ aspect: 'trim', id: 'Metal027' }] },
    { title: 'Refine: Moonlit sky and historic buildings', done_when: 'y', materials: [{ aspect: 'walls', id: 'ph_large_sandstone_blocks' }] }];
  const { steps: cleaned, dropped } = cleanPlanSteps(steps, step => /^Refine:/.test(step.title));
  assert.equal(cleaned[0].materials, undefined);
  assert.match(dropped.join(' '), /step 1: .*no architecture/);
  assert.deepEqual(cleaned[1].materials.map(m => m.id), ['ph_large_sandstone_blocks']);
});

test('the planner sees each material’s look, not only its name (live test: it chose red factory brick for cream facades)', () => {
  const lines = materialCatalogue().materials;
  assert.match(lines.find(l => l.startsWith('ph_castle_brick_02_red')), /kremlin/);
  assert.match(lines.find(l => l.startsWith('ph_green_metal_rust')), /green/);
  assert.match(lines.find(l => l.startsWith('ph_large_sandstone_blocks')), /sandstone|cream|stone/);
});

test('in plain words for the plan card', () => {
  assert.equal(materialsLine([{ aspect: 'walls', id: 'ph_castle_brick_02_red' }, { aspect: 'roofs', id: 'ph_green_metal_rust' }]),
    'walls: old red castle brick; roofs: rusty green metal');
  assert.equal(materialsLine([]), '');
});

test('the catalogue for the planner: compact, every id once', () => {
  const lines = materialCatalogue();
  assert.equal(lines.materials.length, 50);
  assert.match(lines.materials.find(l => l.startsWith('Snow013')), /street/);
  assert.ok(JSON.stringify(lines).length < 9000, 'small enough to look up');
});

test('a planned material becomes a part’s choice; a part its aspect does not cover gets none', () => {
  const church = { name: 'the church', kind: 'church', bounds: [2000, 800, 900, 1400] };
  const planned = [{ aspect: 'walls', id: 'Bricks008', scale: 'coarse' }, { aspect: 'ground', id: 'PavingStones150', recedes: true }];
  const choice = plannedChoice(church, planned, canvas);
  assert.equal(choice.source, 'plan');
  assert.deepEqual(choice.materials, [{ id: 'Bricks008', weight: 1 }]);
  const street = plannedChoice({ name: 'street', kind: 'street', bounds: [0, 3600, 6000, 900] }, planned, canvas);
  assert.ok(street.tile_px.far < street.tile_px.near && street.direction_deg === -90);
  assert.equal(plannedChoice({ name: 'roofs', kind: 'roof', bounds: [0, 0, 100, 100] }, planned, canvas), null);
  // A planned material its kind may not get (brick on a street) is not used there.
  assert.equal(plannedChoice({ name: 'street', kind: 'street', bounds: [0, 3600, 6000, 900] }, [{ aspect: 'ground', id: 'Bricks085' }], canvas), null);
  // A skyscraper takes its walls and its window grid.
  const tower = plannedChoice({ name: 'Moscow City', kind: 'skyscraper', bounds: [4000, 0, 1500, 3000] },
    [{ aspect: 'walls', id: 'ph_large_sandstone_blocks' }, { aspect: 'windows', id: 'Facade013' }], canvas);
  assert.deepEqual(tower.materials.map(m => m.id), ['ph_large_sandstone_blocks', 'Facade013']);
  assert.ok(tower.strength <= 0.12, 'the window grid’s cap');
});

import { briefFromPlan } from '../src/folder-notes.ts';
import { StudioRuntime, briefSchema, normalizeBrief } from '../src/studio.mjs';
import { Value } from 'typebox/value';

test('a brief keeps a refine step’s materials through the schema, normalising, the studio’s check and PLAN.md', () => {
  const brief = { title: 'New Moscow', objective: 'o', requirements: [], freedom: [], completion: ['done'], steps: [
    { title: 'Finish', done_when: 'x', materials: [{ aspect: 'walls', id: 'Bricks085' }] },
    { title: 'Refine: Kremlin wall and towers', done_when: 'y', kind: 'refine_part', parts: ['04-kremlin.png'],
      materials: [{ aspect: 'walls', id: 'ph_castle_brick_02_red', scale: 'coarse' }, { aspect: 'roofs', id: 'Moon dust' }] }] };
  assert.ok(Value.Check(briefSchema, brief));
  const studio = Object.create(StudioRuntime.prototype);
  const { brief: checked, dropped } = studio.cleanStepMaterials(normalizeBrief(brief));
  assert.equal(checked.steps[0].materials, undefined);
  assert.deepEqual(checked.steps[1].materials.map(m => m.id), ['ph_castle_brick_02_red']);
  assert.equal(dropped.length, 2);
  const again = briefFromPlan({ title: 'New Moscow', steps: checked.steps.map(s => ({ title: s.title })) }, checked);
  assert.deepEqual(again.steps[1].materials, checked.steps[1].materials, 'an edit of PLAN.md keeps them by the step');
});
