// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Goal brushwork patterns (extensions/goal-brushwork.ts, openspec architecture-texture goal 8): before an architectural
// refine step's form strokes (refine_to_goal, paint_finish) the host has the plugin cut each architectural part's goal crop
// into a "Goal brushwork: <part>" pattern, once per step and goal, and records per part which pattern it got (or none) for
// the brush texture. A fake `pi`, a fake host; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import goalBrushwork, { brushworkPattern, brushworkRequest, BRUSHWORK_TOOLS } from '../extensions/goal-brushwork.ts';

const area = (x, y, w, h) => ({ mask_path: `/chat/.shapes/found-${x}-${y}.png`, bounds: [x, y, w, h] });
const CHURCH_STEP = { key: 'id:s3', label: 'church and street', parts: [
  { name: '03-church.png', guess: 'the church', area: area(2000, 800, 900, 1400) },
  { name: '04-boat.png', guess: 'a boat', area: area(100, 3000, 400, 300) },
  { name: '05-street.png', guess: 'cobbled street', area: area(0, 3600, 6000, 900) }] };
const SKY_STEP = { key: 'id:s1', label: 'sky', parts: [{ name: '01-sky.png', guess: 'Moonlit sky', area: area(0, 0, 6000, 1500) }] };
const GOAL = { path: '/chat/goal-sharpened.png', sha256: 'a'.repeat(64), size: [5792, 4344], source: [0, 0, 5792, 4344], target: [0, 0, 6000, 4500] };

function setup({ step = CHURCH_STEP, goal = GOAL, fail = null } = {}) {
  const handlers = {}, calls = [], records = {};
  const host = {
    step: () => step,
    goal: async () => goal,
    recorded: key => records[key] ?? null,
    record: entry => { records[entry.step] = entry; },
    native: async params => {
      calls.push(params);
      if (fail) throw new Error(fail);
      return { status: 'ok', brushwork: params.parts.map(p => p.name === 'the church'
        ? { part: p.name, pattern: 'Goal brushwork: the church', energy: 9.4, size: 512, scale: 1.04, ms: 80 }
        : { part: p.name, pattern: null, energy: 1.1, size: 0, scale: 1.04, reason: 'flat', ms: 20 }) };
    },
  };
  goalBrushwork(host)({ registerTool: () => {}, on: (name, handler) => { handlers[name] = handler; } });
  const call = (toolName, id = 'c1') => handlers.tool_call({ toolName, toolCallId: id, input: {} });
  return { handlers, calls, records, call, setStep: s => { step = s; } };
}

test('the request: the architectural parts only, each with its found area, and the placed goal', () => {
  const request = brushworkRequest(CHURCH_STEP, GOAL);
  assert.deepEqual(request.goal, GOAL);
  assert.deepEqual(request.parts, [{ name: 'the church', inside_shape: CHURCH_STEP.parts[0].area },
    { name: 'cobbled street', inside_shape: CHURCH_STEP.parts[2].area }], 'the boat is not architecture');
  assert.equal(brushworkRequest(SKY_STEP, GOAL), null);
  assert.deepEqual(BRUSHWORK_TOOLS, ['refine_to_goal', 'paint_finish']);
});

test('before the refine of an architectural step: one plugin call, the record per part, never a block', async () => {
  const { calls, records, call } = setup();
  assert.equal(await call('refine_to_goal'), undefined, 'the refine always goes ahead');
  assert.equal(calls.length, 1);
  const record = records['id:s3'];
  assert.equal(record.goal, GOAL.sha256);
  assert.deepEqual(record.parts.map(p => [p.part, p.pattern, p.reason ?? null]), [['the church', 'Goal brushwork: the church', null], ['cobbled street', null, 'flat']]);
  // What the brush texture (goal 6) reads: the pattern of a part, or null for a part that has none (library only).
  assert.deepEqual(brushworkPattern(record, 'The Church'), { name: 'Goal brushwork: the church', energy: 9.4, scale: 1.04 });
  assert.equal(brushworkPattern(record, 'cobbled street'), null);
  assert.equal(brushworkPattern(record, 'the river'), null);
  assert.equal(brushworkPattern(null, 'the church'), null);
  // Once per step and goal: a later refine or finish in the step makes nothing again.
  await call('paint_finish', 'c2');
  await call('refine_to_goal', 'c3');
  assert.equal(calls.length, 1);
});

test('other tools, other steps, no goal: nothing made', async () => {
  const { calls, call, setStep } = setup();
  await call('paint_batch');
  await call('finish_move');
  setStep(SKY_STEP);
  await call('refine_to_goal');
  assert.equal(calls.length, 0);
  const none = setup({ goal: null });
  assert.equal(await none.call('refine_to_goal'), undefined);
  assert.equal(none.calls.length, 0);
  assert.equal(none.records['id:s3'], undefined);
});

test('a new goal (Sharpen-ed later) makes the patterns again', async () => {
  const { calls, records, call } = setup();
  await call('refine_to_goal');
  records['id:s3'] = { ...records['id:s3'], goal: 'b'.repeat(64) };
  await call('refine_to_goal', 'c2');
  assert.equal(calls.length, 2);
});

test('a plugin failure never fails the refine: recorded with no patterns, not retried for the same goal', async () => {
  const { calls, records, call } = setup({ fail: 'Goal brushwork patterns need Toska (Krita.createPattern).' });
  assert.equal(await call('refine_to_goal'), undefined);
  assert.match(records['id:s3'].error, /Toska/);
  assert.deepEqual(records['id:s3'].parts, []);
  assert.equal(brushworkPattern(records['id:s3'], 'the church'), null);
  await call('refine_to_goal', 'c2');
  assert.equal(calls.length, 1);
});

// The studio's side (studio.mjs brushworkHost) on a fake studio state, as architecture-texture.test.mjs builds it.
import { StudioRuntime } from '../src/studio.mjs';

function studioState() {
  const steps = [{ title: 'Finish' }, { title: 'Refine: church and street', parts: ['03-church.png', '05-street.png'], id: 's3' }];
  const state = Object.create(StudioRuntime.prototype);
  Object.assign(state, {
    mode: 'agent', currentMove: { number: 4, step: 1 }, study: { folder: { root: '/f' } },
    goal: { brief: { steps }, current_step: 1, step_part_areas: { 'id:s3': [
      { name: '03-church.png', mask_path: '/chat/.shapes/found-a.png', bounds: [2000, 800, 900, 1400] },
      { name: '05-street.png', mask_path: '/chat/.shapes/found-b.png', bounds: [0, 3600, 6000, 900] }] } },
    planSteps: { keyAt: i => 'id:' + steps[i].id, indexOf: key => steps.findIndex(s => 'id:' + s.id === key) },
    folderElements: () => [{ name: '03-church.png', guess: 'the church' }, { name: '05-street.png', guess: 'cobbled street' }],
    folderStudy: { noteOf: () => undefined },
    persist: async () => {},
  });
  return state;
}

test('studio: the brushwork host gives the painted step, keeps the record on the goal by step, calls the plugin', async () => {
  const studio = studioState(), sent = [];
  studio.callNative = async (operation, params) => { sent.push([operation, params]); return { status: 'ok', brushwork: [] }; };
  const host = studio.brushworkHost();
  assert.equal(host.step().key, 'id:s3');
  assert.equal(host.recorded('id:s3'), null);
  const record = { step: 'id:s3', goal: 'a'.repeat(64), parts: [{ part: 'the church', pattern: 'Goal brushwork: the church', energy: 9, size: 512, scale: 1 }], ms: 4 };
  host.record(record);
  assert.deepEqual(host.recorded('id:s3'), record);
  assert.deepEqual(studio.goal.step_brushwork['id:s3'], record, 'kept on the goal: the textured brushes read it there');
  await host.native({ goal: GOAL, parts: [] });
  assert.deepEqual(sent, [['brushwork_patterns', { goal: GOAL, parts: [] }]]);
  studio.goalPlacement = async () => null;
  studio.lastObservation = { width: 6000, height: 4500 };
  assert.equal(await host.goal(), null, 'no placed goal: no patterns');
  assert.ok(studio.extensionFactories().some(e => e.name === 'goal-brushwork'), 'registered with the other shipped extensions');
});

import { brushworkDabs } from '../extensions/goal-brushwork.ts';

test('a part’s goal dabs (goal 9): its brush tip names, or null when it has none', () => {
  const record = { step: 'id:s3', goal: 'a', ms: 1, parts: [
    { part: 'the church', pattern: 'Goal brushwork: the church', energy: 9, size: 128, scale: 1, dabs: ['Goal dab: the church 1'] },
    { part: 'cobbled street', pattern: null, energy: 1, size: 0, scale: 1, reason: 'flat', dabs: [] },
    { part: 'the bridge', pattern: null, energy: 1, size: 0, scale: 1 }] };
  assert.deepEqual(brushworkDabs(record, 'The  Church'), ['Goal dab: the church 1']);
  assert.equal(brushworkDabs(record, 'cobbled street'), null);
  assert.equal(brushworkDabs(record, 'the bridge'), null, 'an older plugin reports no dabs');
  assert.equal(brushworkDabs(null, 'the church'), null);
});
