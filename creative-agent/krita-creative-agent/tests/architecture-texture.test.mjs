// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The architecture texture Pi extension (extensions/architecture-texture.ts): its tool, the automatic pass after
// refine_to_goal in an architectural refine step, and the hook that keeps such a step from finishing without it. A fake
// `pi`, a fake host and a fake planner; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import architectureTexture, { architecturalParts, textureRequired } from '../extensions/architecture-texture.ts';

const area = (x, y, w, h) => ({ mask_path: `/chat/.shapes/found-${x}-${y}.png`, bounds: [x, y, w, h] });
const CHURCH_STEP = { key: 'id:s3', label: 'church and street', parts: [
  { name: '03-church.png', guess: 'the church', area: area(2000, 800, 900, 1400) },
  { name: '05-street.png', guess: 'cobbled street', area: area(0, 3600, 6000, 900) }] };
const SKY_STEP = { key: 'id:s1', label: 'sky and moon', parts: [{ name: '01-sky.png', guess: 'Moonlit sky', area: area(0, 0, 6000, 1500) },
  { name: '02-moon.png', guess: 'Moon', area: area(4000, 200, 400, 400) }] };

function setup({ step = CHURCH_STEP, reply = null } = {}) {
  const tools = {}, handlers = {}, calls = [], records = [];
  let done = false;
  const host = {
    step: () => step,
    done: () => done,
    record: entry => { records.push(entry); done = true; },
    canvas: () => ({ width: 6000, height: 4500 }),
    view: async () => ({ label: 'CANVAS', picture: { data: 'AAAA', mimeType: 'image/jpeg' } }),
    reader: async () => (reply ? async () => ({ text: JSON.stringify(reply), cost: 0.001, model: 'fake/qwen' }) : null),
    maps: async material => ({ color: 'Y29sb3Vy', displacement: 'ZGlzcA==', ...(material.maps.ao ? { ao: 'YW8=' } : {}), ...(material.detail_from ? { detail_from: material.detail_from } : {}) }),
    native: async (params, id) => {
      calls.push({ params, id });
      const details = { status: 'ok', layer_id: 'T1', layer_type: 'texture', texture: { parts: params.parts.map(p => ({ name: p.name, ms: 900 })) }, image_path: '/chat/view.png' };
      return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
    },
  };
  architectureTexture(host)({ registerTool: t => { tools[t.name] = t; }, on: (name, handler) => { handlers[name] = handler; } });
  return { tools, handlers, calls, records, host, setStep: s => { step = s; } };
}

test('architectural parts by their names; a step of sky and moon has none', () => {
  assert.deepEqual(architecturalParts(CHURCH_STEP).map(p => [p.name, p.kind]), [['the church', 'church'], ['cobbled street', 'street']]);
  assert.deepEqual(architecturalParts(SKY_STEP), []);
  // A part with no found area of its own takes the step's area only when every part of the step is architecture.
  const shared = { key: 'k', label: 'buildings', area: area(0, 0, 100, 100), parts: [{ name: 'a', guess: 'Historic buildings' }, { name: 'b', guess: 'bridge' }] };
  assert.deepEqual(architecturalParts(shared).map(p => p.area.bounds), [[0, 0, 100, 100], [0, 0, 100, 100]]);
  const mixed = { ...shared, parts: [{ name: 'a', guess: 'Historic buildings' }, { name: 'b', guess: 'river' }] };
  assert.deepEqual(architecturalParts(mixed), []);
  assert.equal(textureRequired(CHURCH_STEP, false), true);
  assert.equal(textureRequired(CHURCH_STEP, true), false);
  assert.equal(textureRequired(SKY_STEP, false), false);
  assert.equal(textureRequired(null, false), false);
});

test('the tool: the planner chooses, the host clamps, one plugin call bakes one "Texture: <part>" layer', async () => {
  const reply = { parts: [{ part: 'the church', materials: [{ id: 'Bricks008', weight: 1 }], tile_px: { near: 220, far: 220 }, strength: 0.9, blend: 'overlay' }] };
  const { tools, calls, records } = setup({ reply });
  assert.match(tools.texture_architecture.description, /never/i);
  const result = await tools.texture_architecture.execute('call-1', {}, undefined);
  assert.equal(calls.length, 1);
  const sent = calls[0].params;
  assert.equal(sent.name, 'Texture: church and street');
  assert.deepEqual(sent.parts.map(p => p.name), ['the church', 'cobbled street']);
  assert.equal(sent.parts[0].strength, 0.3, 'clamped to the artist’s 30%');
  assert.deepEqual(sent.parts[0].inside_shape, CHURCH_STEP.parts[0].area);
  assert.deepEqual(Object.keys(sent.materials).sort(), ['Bricks008', 'PavingStones046']);
  assert.equal(records.length, 1);
  assert.equal(records[0].step, 'id:s3');
  const told = JSON.parse(result.content.filter(c => c.type === 'text').at(-1).text);
  assert.equal(told.texture.parts[1].source, 'default');
});

test('the painter may set a part itself: still clamped to the part’s materials', async () => {
  const { tools, calls } = setup();
  await tools.texture_architecture.execute('call-2', { parts: [{ part: 'cobbled street', materials: [{ id: 'Snow013', weight: 1 }], strength: 0.2 }, { part: 'the church', materials: [{ id: 'Snow013' }] }] });
  const [church, street] = calls[0].params.parts;
  assert.deepEqual(street.materials, [{ id: 'Snow013', weight: 1 }], 'snow lies on the street');
  assert.notEqual(church.materials[0].id, 'Snow013', 'never on a church: the default instead');
});

test('a step without architecture: the tool says so and paints nothing', async () => {
  const { tools, calls } = setup({ step: SKY_STEP });
  await assert.rejects(tools.texture_architecture.execute('call-3', {}), /no architectural part/i);
  assert.equal(calls.length, 0);
});

test('after refine_to_goal in an architectural refine step the host runs the pass itself, once', async () => {
  const { handlers, calls } = setup();
  const event = { type: 'tool_result', toolCallId: 'r1', toolName: 'refine_to_goal', input: {}, isError: false, content: [{ type: 'text', text: '{"refine":{}}' }], details: {} };
  const changed = await handlers.tool_result(event);
  assert.equal(calls.length, 1);
  assert.match(changed.content.map(c => c.text ?? '').join(' '), /texture/i);
  await handlers.tool_result({ ...event, toolCallId: 'r2' });
  assert.equal(calls.length, 1, 'once a step');
  assert.equal(await handlers.tool_result({ ...event, toolCallId: 'r3', toolName: 'paint_finish' }), undefined);
});

test('a failed refine, or a sky step, runs nothing', async () => {
  const { handlers, calls, setStep } = setup();
  await handlers.tool_result({ type: 'tool_result', toolCallId: 'r1', toolName: 'refine_to_goal', input: {}, isError: true, content: [], details: {} });
  setStep(SKY_STEP);
  await handlers.tool_result({ type: 'tool_result', toolCallId: 'r2', toolName: 'refine_to_goal', input: {}, isError: false, content: [], details: {} });
  assert.equal(calls.length, 0);
});

test('finish_move is blocked until an architectural step has its texture pass; then it goes through', async () => {
  const { handlers, tools, setStep } = setup();
  const call = { type: 'tool_call', toolCallId: 'f1', toolName: 'finish_move', input: { summary: 'church' } };
  const blocked = await handlers.tool_call(call);
  assert.equal(blocked.block, true);
  assert.match(blocked.reason, /texture_architecture/);
  await tools.texture_architecture.execute('t', {});
  assert.equal(await handlers.tool_call(call), undefined);
  setStep(SKY_STEP);
  assert.equal(await handlers.tool_call(call), undefined);
  assert.equal(await handlers.tool_call({ ...call, toolName: 'paint_pass' }), undefined);
});

test('an automatic pass that fails is told to the painter, never failing the refine; the honest attempt is recorded, so the step can finish', async () => {
  const { handlers, host, records } = setup();
  host.native = async () => { throw new Error('Krita rejected the texture pixels.'); };
  const changed = await handlers.tool_result({ type: 'tool_result', toolCallId: 'r1', toolName: 'refine_to_goal', input: {}, isError: false, content: [{ type: 'text', text: '{}' }], details: {} });
  assert.match(changed.content.at(-1).text, /could not|rejected/i);
  assert.match(records[0].failed, /rejected/);
  assert.equal(await handlers.tool_call({ type: 'tool_call', toolCallId: 'f', toolName: 'finish_move', input: {} }), undefined, 'never a loop');
});

test('the automatic pass runs under the run’s signal: Stop ends it before anything is painted', async () => {
  const { handlers, host, calls } = setup();
  const seen = [];
  const maps = host.maps;
  host.maps = async (material, signal) => { seen.push(signal); return maps(material); };
  const controller = new AbortController();
  const event = { type: 'tool_result', toolCallId: 'r1', toolName: 'refine_to_goal', input: {}, isError: false, content: [], details: {} };
  await handlers.tool_result(event, { signal: controller.signal });
  assert.ok(seen.length && seen.every(s => s === controller.signal));
  const stopped = setup();
  const abort = new AbortController(); abort.abort();
  await stopped.handlers.tool_result(event, { signal: abort.signal });
  assert.equal(stopped.calls.length, 0, 'nothing painted after Stop');
  assert.equal(calls.length, 1);
});

// The studio's side (studio.mjs textureStep, textureHost and the Met refusal) on a fake studio state.
import { StudioRuntime } from '../src/studio.mjs';

function studioState({ found = true } = {}) {
  const steps = [{ title: 'Finish' }, { title: 'Refine: church and street', parts: ['03-church.png', '05-street.png'], id: 's3' }, { title: 'Refine: sky and moon', parts: ['01-sky.png'], id: 's1' }];
  const state = Object.create(StudioRuntime.prototype);
  Object.assign(state, {
    mode: 'agent', currentMove: { number: 4, step: 1 }, study: { folder: { root: '/f' } },
    goal: { brief: { steps }, current_step: 1, ...(found ? { step_part_areas: { 'id:s3': [
      { name: '03-church.png', mask_path: '/chat/.shapes/found-a.png', bounds: [2000, 800, 900, 1400] },
      { name: '05-street.png', mask_path: '/chat/.shapes/found-b.png', bounds: [0, 3600, 6000, 900] }] } } : {}) },
    planSteps: { keyAt: i => 'id:' + steps[i].id, indexOf: key => steps.findIndex(s => 'id:' + s.id === key) },
    folderElements: () => [{ name: '01-sky.png', guess: 'Moonlit sky' }, { name: '03-church.png', guess: 'the church' }, { name: '05-street.png', guess: 'cobbled street' }],
    folderStudy: { noteOf: name => (name === '03-church.png' ? 'white church with green domes' : undefined) },
  });
  return state;
}

test('studio: a refine-part step gives its parts, their found areas and notes; other steps none', () => {
  const studio = studioState();
  const step = studio.textureStep(1);
  assert.equal(step.key, 'id:s3');
  assert.equal(step.label, 'church and street');
  assert.deepEqual(step.parts.map(p => [p.guess, p.area?.bounds]), [['the church', [2000, 800, 900, 1400]], ['cobbled street', [0, 3600, 6000, 900]]]);
  assert.equal(step.parts[0].note, 'white church with green domes');
  assert.equal(studio.textureStep(0), null);
  assert.deepEqual(architecturalParts(studio.textureStep(2)), []);
});

test('studio: Met of an architectural refine move is refused until the move has its texture', () => {
  const studio = studioState();
  const host = studio.planStepHost();
  const move = { number: 4, step: 1, step_key: 'id:s3', status: 'ready' };
  assert.match(host.metRefusal(move), /texture pass has not run.*Met again/);
  assert.equal(host.metRefusal(move), null, 'the artist pressed Met again: kept without it, never a loop');
  const textured = { number: 6, step: 1, step_key: 'id:s3', status: 'ready', texture: { step: 'id:s3' } };
  assert.equal(host.metRefusal(textured), null);
  assert.equal(host.metRefusal({ number: 5, step: 2, step_key: 'id:s1' }), null, 'sky and moon: nothing owed');
  assert.equal(studioState({ found: false }).planStepHost().metRefusal({ number: 4, step: 1, step_key: 'id:s3' }), null, 'no found areas: nothing to texture');
});

test('studio: a continue move on a step already textured by an earlier move of it does not texture it again', () => {
  const studio = studioState();
  studio.goal.moves = [{ number: 3, step: 1, step_key: 'id:s3', status: 'kept', texture: { step: 'id:s3' } }, studio.currentMove];
  assert.equal(studio.textureHost().done(), true);
  studio.goal.moves[0].status = 'undone';
  assert.equal(studio.textureHost().done(), false, 'an undone move’s texture is gone with it');
});

test('studio: the texture host reads the step’s goal brushwork record (goal 8)', () => {
  const studio = studioState();
  const record = { step: 'id:s3', goal: 'abc', ms: 1, parts: [{ part: 'the church', pattern: 'Goal brushwork: the church', energy: 9, size: 128, scale: 2 }] };
  studio.goal.step_brushwork = { 'id:s3': record };
  assert.deepEqual(studio.textureHost().brushwork('id:s3'), record);
  assert.equal(studio.textureHost().brushwork('id:s9'), null);
});

test('studio: the texture host records the pass on the Agent move', () => {
  const studio = studioState();
  studio.persist = async () => {};
  const host = studio.textureHost();
  assert.equal(host.done(), false);
  host.record({ step: 'id:s3', parts: [], ms: 5, auto: true });
  assert.equal(host.done(), true);
  assert.equal(studio.currentMove.texture.step, 'id:s3');
});

test('a step with planned materials uses them and asks the model only for the parts they leave out', async () => {
  let asked = null;
  const step = { ...CHURCH_STEP, materials: [{ aspect: 'walls', id: 'ph_castle_brick_02_red' }] };
  const { tools, calls, host } = setup({ step });
  host.reader = async () => async ({ prompt }) => { asked = prompt; return { text: '{"parts":[]}', cost: 0, model: 'fake/qwen' }; };
  const result = await tools.texture_architecture.execute('p1', {});
  assert.deepEqual(calls[0].params.parts[0].materials, [{ id: 'ph_castle_brick_02_red', weight: 1 }]);
  assert.doesNotMatch(asked, /the church/, 'the church was planned: not asked');
  assert.match(asked, /cobbled street/);
  const told = JSON.parse(result.content.filter(c => c.type === 'text').at(-1).text);
  assert.deepEqual(told.texture.parts.map(p => p.source), ['plan', 'default']);
  const both = setup({ step: { ...CHURCH_STEP, materials: [{ aspect: 'walls', id: 'Bricks008' }, { aspect: 'ground', id: 'PavingStones150' }] } });
  both.host.reader = async () => { throw new Error('the model must not be asked'); };
  await both.tools.texture_architecture.execute('p2', {});
  assert.deepEqual(both.calls[0].params.parts.map(p => p.materials[0].id), ['Bricks008', 'PavingStones150']);
});

import { refineGrain, GRAIN_STRENGTH, architecturalParts as partsOf } from '../extensions/architecture-texture.ts';

test('a part with goal brushwork carries that pattern too, at its own tile size, after its material (goal 8)', async () => {
  const reply = { parts: [{ part: 'the church', materials: [{ id: 'Bricks008', weight: 1 }], tile_px: { near: 220, far: 220 }, strength: 0.2 }] };
  const { host } = setup({ reply });
  host.patterns = async materials => Object.fromEntries(Object.keys(materials).map(id => [id, 'Texture: ' + id]));
  const church = partsOf(host.step())[0];
  host.brushwork = key => ({ step: key, goal: 'abc', ms: 5, parts: [{ part: church.name, pattern: 'Goal brushwork: the church', energy: 9, size: 128, scale: 2.5 }] });
  const grain = await refineGrain(host);
  const ours = grain.filter(g => g.inside_shape.bounds.join() === church.area.bounds.join());
  assert.deepEqual(ours.map(g => g.pattern), ['Texture: Bricks008', 'Goal brushwork: the church']);
  assert.equal(ours[1].tile_px, 320, 'the pattern covers its goal crop: size x scale canvas px');
  assert.equal(ours[1].strength, GRAIN_STRENGTH);
  host.brushwork = () => null;
  assert.ok((await refineGrain(host)).every(g => !g.pattern.startsWith('Goal brushwork')), 'no record: the material alone');
});

test('the refine’s form strokes carry each architectural part’s material as a Krita pattern, one decision for both passes', async () => {
  const reply = { parts: [{ part: 'the church', materials: [{ id: 'Bricks008', weight: 1 }], tile_px: { near: 220, far: 220 }, strength: 0.2 }] };
  const { host, tools, calls } = setup({ reply });
  let asked = 0, registered = null;
  const reader = host.reader;
  host.reader = async () => { asked++; return reader(); };
  const memory = new Map();
  host.decided = key => memory.get(key);
  host.remember = (key, decision) => memory.set(key, decision);
  host.patterns = async materials => { registered = Object.keys(materials).sort(); return Object.fromEntries(Object.keys(materials).map(id => [id, 'Texture: ' + id])); };
  const grain = await refineGrain(host);
  assert.deepEqual(registered, ['Bricks008', 'PavingStones046']);
  assert.deepEqual(grain.map(g => [g.pattern, g.inside_shape.bounds, g.strength]), [['Texture: Bricks008', [2000, 800, 900, 1400], GRAIN_STRENGTH],
    ['Texture: PavingStones046', [0, 3600, 6000, 900], GRAIN_STRENGTH]]);
  assert.equal(grain[0].tile_px, 220);
  await tools.texture_architecture.execute('t', {});
  assert.equal(asked, 1, 'the texture pass reuses the decision');
  assert.equal(calls[0].params.parts[0].materials[0].id, 'Bricks008');
  const sky = setup({ step: SKY_STEP });
  sky.host.patterns = async () => ({});
  assert.equal(await refineGrain(sky.host), null);
  const stock = setup();
  assert.equal(await refineGrain(stock.host), null, 'no patterns (stock Krita): no grain');
});

// Luna picks each part's material by look at the step's first paint (src/luna-materials.ts): the decision takes its result.
import { decideTextures } from '../extensions/architecture-texture.ts';

test('the paint-time decision asks Luna for the step’s materials first and uses its picks; a failure keeps the plan’s', async () => {
  const { host } = setup({ step: { ...CHURCH_STEP, materials: [{ aspect: 'walls', id: 'Bricks085' }, { aspect: 'ground', id: 'PavingStones150' }] } });
  let asked = null;
  host.lunaMaterials = async (step, parts) => { asked = parts.map(p => p.name); return [{ aspect: 'walls', id: 'ph_old_sandstone_02', source: 'luna' }, { aspect: 'ground', id: 'PavingStones150' }]; };
  host.reader = async () => { throw new Error('the model must not be asked'); };
  const decision = await decideTextures(host, host.step());
  assert.deepEqual(asked, ['the church', 'cobbled street']);
  assert.deepEqual(decision.chosen.map(c => [c.materials[0].id, c.source]), [['ph_old_sandstone_02', 'luna'], ['PavingStones150', 'plan']]);
  host.lunaMaterials = async () => { throw new Error('offline'); };
  const kept = await decideTextures(host, host.step());
  assert.deepEqual(kept.chosen.map(c => c.materials[0].id), ['Bricks085', 'PavingStones150']);
});

import { chooseByLook } from '../src/luna-materials.ts';

test('studio: Luna’s picks go into the plan step once a revision, with probabilities and cost in the diagnostics; offline keeps the plan', async () => {
  const studio = studioState(), records = [];
  studio.goal.revision = 3;
  studio.goal.brief.steps[1].materials = [{ aspect: 'walls', id: 'Bricks085', material: 'red brick' }];
  Object.assign(studio, { persist: async () => {}, publish: () => {}, diagnostics: { record: r => records.push(r) }, lastObservation: { width: 6000, height: 4500 } });
  let calls = 0;
  studio.lunaChoose = async input => { calls++; return chooseByLook({ ...input, client: { decide: async ({ questions }) => {
    const letters = Object.keys(questions.material.criteria);
    return { answers: { material: { type: 'choice', choice: letters[1], probabilities: Object.fromEntries(letters.map((l, i) => [l, i === 1 ? 0.8 : 0.2 / (letters.length - 1)])) } }, model: 'fake', elapsed_ms: 5, usage: { input_tokens: 800, output_tokens: 3, cost: 0.002 } };
  } }, crops: async parts => parts.map(() => ({ type: 'image', data: 'AAAA', mimeType: 'image/jpeg' })), swatch: async () => ({ type: 'image', data: 'AAAA', mimeType: 'image/jpeg' }) }); };
  const host = studio.textureHost(), step = host.step();
  const materials = await host.lunaMaterials(step, architecturalParts(step));
  assert.equal(calls, 1);
  assert.ok(materials.some(m => m.source === 'luna'));
  assert.deepEqual(studio.goal.brief.steps[1].materials, materials, 'the plan card shows Luna’s picks');
  const record = records.find(r => r.type === 'luna_materials');
  assert.equal(record.step, 'id:s3');
  assert.ok(record.parts.every(p => p.cost === 0.002 && Object.keys(p.probabilities).length > 0));
  await host.lunaMaterials(host.step(), architecturalParts(host.step()));
  assert.equal(calls, 1, 'once a plan revision');
  studio.goal.revision = 4;
  studio.lunaChoose = async () => { throw new Error('offline'); };
  const before = structuredClone(studio.goal.brief.steps[1].materials);
  assert.deepEqual(await host.lunaMaterials(host.step(), architecturalParts(host.step())), before);
});

import { refineDabs } from '../extensions/architecture-texture.ts';

test('the refine’s form strokes in an architectural part are stamped with its goal dabs; none without them (goal 9)', async () => {
  const { host } = setup();
  const [church, street] = partsOf(host.step());
  assert.equal(await refineDabs(host), null, 'no brushwork record: plain strokes');
  host.brushwork = key => ({ step: key, goal: 'abc', ms: 5, parts: [
    { part: church.name, pattern: 'Goal brushwork: the church', energy: 9, size: 128, scale: 2.5, dabs: ['Goal dab: the church 1', 'Goal dab: the church 2'] },
    { part: street.name, pattern: null, energy: 1, size: 0, scale: 2.5, reason: 'flat', dabs: [] }] });
  assert.deepEqual(await refineDabs(host), [{ tips: ['Goal dab: the church 1', 'Goal dab: the church 2'], inside_shape: { mask_path: church.area.mask_path, bounds: church.area.bounds } }],
    'the street gave no dab: its strokes stay plain');
  // Sky, water, people, vehicles, trees never: only the step's architectural parts are looked up.
  const sky = setup({ step: SKY_STEP });
  sky.host.brushwork = key => ({ step: key, goal: 'abc', ms: 5, parts: [{ part: 'Moonlit sky', pattern: null, energy: 0, size: 0, scale: 1, dabs: ['Goal dab: Moonlit sky 1'] }] });
  assert.equal(await refineDabs(sky.host), null);
});

test('studio: the refine’s dabs come from the step’s goal brushwork record (goal 9)', async () => {
  const studio = studioState();
  assert.equal(await studio.refineDabs(), null);
  studio.goal.step_brushwork = { 'id:s3': { step: 'id:s3', goal: 'abc', ms: 1, parts: [{ part: 'the church', pattern: null, energy: 9, size: 0, scale: 2, dabs: ['Goal dab: the church 1'] }] } };
  assert.deepEqual(await studio.refineDabs(), [{ tips: ['Goal dab: the church 1'], inside_shape: { mask_path: '/chat/.shapes/found-a.png', bounds: [2000, 800, 900, 1400] } }]);
});
