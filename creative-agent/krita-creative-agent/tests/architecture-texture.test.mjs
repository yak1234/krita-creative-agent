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

test('an automatic pass that fails is told to the painter, never failing the refine, and finish_move stays blocked', async () => {
  const { handlers, host } = setup();
  host.native = async () => { throw new Error('Krita rejected the texture pixels.'); };
  const changed = await handlers.tool_result({ type: 'tool_result', toolCallId: 'r1', toolName: 'refine_to_goal', input: {}, isError: false, content: [{ type: 'text', text: '{}' }], details: {} });
  assert.match(changed.content.at(-1).text, /could not|rejected/i);
  assert.equal((await handlers.tool_call({ type: 'tool_call', toolCallId: 'f', toolName: 'finish_move', input: {} })).block, true);
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
  assert.match(host.metRefusal(move), /texture pass has not run/);
  move.texture = { step: 'id:s3' };
  assert.equal(host.metRefusal(move), null);
  assert.equal(host.metRefusal({ number: 5, step: 2, step_key: 'id:s1' }), null, 'sky and moon: nothing owed');
  assert.equal(studioState({ found: false }).planStepHost().metRefusal({ number: 4, step: 1, step_key: 'id:s3' }), null, 'no found areas: nothing to texture');
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
