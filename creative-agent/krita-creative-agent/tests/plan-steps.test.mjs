// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Plan step controls (plan-step-controls): Skip / Restore before painting, "Good enough → next step" while a step paints,
// Met / Redo after it finishes. The module's rules with a fake host; studio.test.mjs runs them through a chat.
// Temporary folders only, removed after each test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile, writeFile, symlink, readdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { parsePlanStepCommand, planStepView, openStepFrom, closedSteps, planStepControls, recordLesson, LESSONS_FILE, stepMarksContext,
  stepIdentities, withStepIds } from '../src/plan-steps.ts';
import { stepKeys } from '../src/folder-notes.ts';

const steps = [{ title: 'Underpainting', done_when: 'a', scope: 'whole composition' }, { title: 'Sky', done_when: 'b', scope: '01-sky.png' },
  { title: 'Soften the foreground into masses', done_when: 'c' }, { title: 'Towers', done_when: 'd', scope: '04-towers.png' }];
const keys = stepKeys(steps);
const id = 'a1b2c3';

async function chatFolder(work) {
  const dir = await mkdtemp(join(tmpdir(), 'plan-steps-'));
  try { await work(dir); } finally { await rm(dir, { recursive: true, force: true }); }
}

/** A fake studio: a goal and the calls the controls make. */
function fakeHost({ mode = 'agent', busy = false, folder = true, dir = null, goal = {}, mayContinue = () => true } = {}) {
  const calls = [];
  const state = { mode, busy, move: undefined, failReject: false };
  const host = {
    calls, state,
    goal: { brief: { steps }, status: 'ready', current_step: 0, done_steps: [], moves: [], ...goal },
    getGoal: () => host.goal, mode: () => state.mode, busy: () => state.busy, currentMove: () => state.move,
    folder: () => folder, chatDirectory: () => dir, goalLikeness: () => null, mayContinue: auto => { calls.push('mayContinue ' + auto); return mayContinue(auto); },
    persist: async () => { calls.push('persist'); }, publish: () => calls.push('publish'), say: message => calls.push('say: ' + message),
    syncPlan: async () => { calls.push('syncPlan'); },
    keepMove: async move => { move.status = 'kept'; calls.push('keepMove ' + move.number + ' marks:' + JSON.stringify(host.goal.step_marks ?? {})); },
    tickFolderStep: async move => { const i = keys.indexOf(move.step_key); host.goal.done_steps = [...new Set([...host.goal.done_steps, i])];
      calls.push('tickFolderStep ' + move.number); return openStepFrom(keys, host.goal.step_marks, host.goal.done_steps); },
    rejectMove: async move => { if (state.failReject) throw new Error('reject failed'); move.status = 'undone'; calls.push('rejectMove ' + move.number); },
    retryMove: async (move, note) => { calls.push('retryMove ' + move.number + (note ? ': ' + note : '')); },
    nextStepMove: async () => { calls.push('nextStepMove ' + host.goal.current_step); },
    finish: async message => { calls.push('finish: ' + message); },
  };
  return host;
}
const command = (action, index, extra = {}) => ({ type: 'plan_step', id, action, step_key: keys[index], ...extra });
/** The studio's Keep / Undo of a move: a stepped move goes to Met / Redo. */
const reviewer = controls => (move, action, note) => action === 'keep' ? controls.met(move) : controls.redo(move, note);

test('panel commands are validated: id, action, a step key, text only for Redo', () => {
  assert.deepEqual(parsePlanStepCommand(command('skip', 2)), { id, action: 'skip', step_key: keys[2] });
  assert.deepEqual(parsePlanStepCommand(command('redo', 1, { text: '  warmer light  ' })), { id, action: 'redo', step_key: keys[1], text: 'warmer light' });
  assert.deepEqual(parsePlanStepCommand(command('redo', 1, { text: '   ' })), { id, action: 'redo', step_key: keys[1] }, 'blank text is no text');
  for (const bad of [null, 'skip', {}, command('delete', 1), { ...command('skip', 1), id: '' }, { ...command('skip', 1), id: 'x'.repeat(81) },
    { ...command('skip', 1), id: 'has space' }, { ...command('skip', 1), step_key: '' }, { ...command('skip', 1), step_key: 7 },
    { ...command('skip', 1), step_key: 'x'.repeat(401) }, command('skip', 1, { text: 'only redo has text' }), command('redo', 1, { text: 'x'.repeat(1001) }),
    command('redo', 1, { text: 5 }), { ...command('skip', 1), extra: true }])
    assert.throws(() => parsePlanStepCommand(bad), /plan step/i, JSON.stringify(bad));
});

test('without a folder, steps keep a stable id through rewording; a folder plan is known by file or title', () => {
  let n = 0; const next = () => 'n' + (++n);
  const first = withStepIds({ steps: [{ title: 'Sky', done_when: 'a' }, { title: 'Figures', done_when: 'b' }] }, null, next);
  assert.deepEqual(first.steps.map(s => s.id), ['n1', 'n2']);
  const reworded = withStepIds({ steps: [{ ...first.steps[0], title: 'A moonlit sky' }, { title: 'Figures', done_when: 'b' }, { title: 'Snow', done_when: 'c' }] }, first, next);
  assert.deepEqual(reworded.steps.map(s => s.id), ['n1', 'n2', 'n3'], 'an id is kept, or found by the old title, or new');
  const clash = withStepIds({ steps: [{ title: 'A', done_when: 'a', id: 'x' }, { title: 'B', done_when: 'b', id: 'x' }, { title: 'C', done_when: 'c', id: 'bad id!' }] }, null, next);
  assert.deepEqual(clash.steps.map(s => s.id), ['x', 'n4', 'n5'], 'ids are unique and well formed');
  assert.deepEqual(stepIdentities(reworded.steps), ['id:n1', 'id:n2', 'id:n3']);
  assert.deepEqual(stepIdentities(reworded.steps, true), stepKeys(reworded.steps), 'a folder plan uses PLAN.md\'s identities');
  assert.deepEqual(stepIdentities(steps), keys, 'a plan made before ids keeps its title keys');
});

test('skipped, met and done steps are closed; the next open step skips them', () => {
  const marks = { [keys[1]]: { skipped: true }, [keys[2]]: { met: 'good_enough' } };
  assert.deepEqual([...closedSteps(keys, marks, [0])].sort(), [0, 1, 2]);
  assert.equal(openStepFrom(keys, marks, [0], 0), 3);
  assert.equal(openStepFrom(keys, marks, [], 1), 3);
  assert.equal(openStepFrom(keys, { ...marks, [keys[3]]: { skipped: true } }, [0], 0), 4, 'none open: the plan length');
  assert.equal(openStepFrom(keys, { [keys[1]]: { redone: 2 } }, [], 1), 1, 'a redone step is still open');
});

test('the panel\'s view of each step: open, skipped, painting, finishing, finished, met, good enough, done', () => {
  const marks = { [keys[1]]: { skipped: true }, [keys[3]]: { met: 'artist', redone: 1 } };
  const base = { brief: { steps }, status: 'ready', current_step: 0, done_steps: [], step_marks: marks, moves: [] };
  const view = planStepView(base, { mode: 'agent', busy: false });
  assert.deepEqual(view.map(v => [v.index, v.key, v.title, v.state]), [[0, keys[0], 'Underpainting', 'open'], [1, keys[1], 'Sky', 'skipped'],
    [2, keys[2], 'Soften the foreground into masses', 'open'], [3, keys[3], 'Towers', 'met']]);
  assert.equal(view[3].redone, 1);
  const move = { number: 1, status: 'painting', step: 0, step_key: keys[0], calls: 1 };
  assert.equal(planStepView({ ...base, status: 'active' }, { mode: 'agent', busy: true, currentMove: move })[0].state, 'painting');
  assert.equal(planStepView({ ...base, status: 'active' }, { mode: 'agent', busy: true, currentMove: move, pending: keys[0] })[0].state, 'finishing');
  assert.equal(planStepView({ ...base, status: 'active' }, { mode: 'agent', busy: true, currentMove: { number: 2, status: 'painting' } })[0].state, 'open',
    'a move that is not a plan step paints no step');
  for (const status of ['move_ready', 'paused', 'limited'])
    assert.equal(planStepView({ ...base, status, moves: [{ ...move, status: 'ready' }] }, { mode: 'agent', busy: false })[0].state, 'finished', 'a ready move, whatever the goal\'s status: ' + status);
  assert.equal(planStepView({ ...base, status: 'move_ready', moves: [{ ...move, status: 'ready', guides_only: true }] }, { mode: 'agent', busy: false })[0].state, 'open', 'a guides move is no step\'s result');
  assert.equal(planStepView({ ...base, moves: [{ ...move, status: 'kept' }], done_steps: [0] }, { mode: 'agent', busy: false })[0].state, 'done');
  assert.equal(planStepView({ ...base, status: 'active', current_step: 2 }, { mode: 'autopilot', busy: true })[2].state, 'painting');
  assert.equal(planStepView({ ...base, status: 'active', current_step: 2 }, { mode: 'autopilot', busy: true, pending: keys[2] })[2].state, 'finishing');
  assert.equal(planStepView({ ...base, step_marks: { [keys[0]]: { met: 'good_enough' } }, done_steps: [0] }, { mode: 'agent', busy: false })[0].state, 'good_enough');
  assert.deepEqual(planStepView({ brief: null }, { mode: 'agent', busy: false }), []);
});

test('the painter is told which steps the artist skipped or marked met', () => {
  assert.deepEqual(stepMarksContext(steps, { [keys[1]]: { skipped: true }, [keys[3]]: { met: 'artist' }, 'title:gone#0': { skipped: true } }),
    { note: 'The artist skipped some plan steps and marked others met. Never paint a skipped step, never add it back to a plan, and paint nothing more for a met step.',
      steps: [{ step: 2, title: 'Sky', artist: 'skipped' }, { step: 4, title: 'Towers', artist: 'met' }] });
  assert.equal(stepMarksContext(steps, {}), undefined);
});

test('Skip before painting closes a step and moves the current step past it; Restore reopens it', async () => {
  const host = fakeHost();
  const controls = planStepControls(host), review = reviewer(controls);
  await controls.command(command('skip', 0), review);
  assert.deepEqual(host.goal.step_marks, { [keys[0]]: { skipped: true } });
  assert.equal(host.goal.current_step, 1, 'Start painting begins at the first step not skipped');
  assert.ok(host.calls.includes('syncPlan') && host.calls.includes('persist') && host.calls.includes('publish'));
  await controls.command(command('skip', 2), review);
  assert.equal(host.goal.current_step, 1);
  await assert.rejects(controls.command(command('restore', 1), review), /not skipped/);
  await controls.command(command('restore', 0), review);
  assert.deepEqual(host.goal.step_marks, { [keys[2]]: { skipped: true } });
  assert.equal(host.goal.current_step, 0, 'a restored earlier step is painted next');
  await assert.rejects(controls.command({ ...command('skip', 0), step_key: 'title:not in the plan#0' }, review), /no longer in the plan/);
});

test('Skip is refused on the step that is painting, finished or met', async () => {
  const host = fakeHost({ busy: true, goal: { status: 'active', step_marks: { [keys[3]]: { met: 'artist' } } } });
  host.state.move = { number: 1, status: 'painting', step: 0, step_key: keys[0] };
  const controls = planStepControls(host), review = reviewer(controls);
  await assert.rejects(controls.command(command('skip', 0), review), /painting/);
  await assert.rejects(controls.command(command('skip', 3), review), /already met/);
  await controls.command(command('skip', 2), review);
  assert.equal(host.goal.current_step, 0, 'skipping a later step while painting leaves the painting step current');
  host.state.busy = false; host.state.move = undefined; host.goal.status = 'move_ready'; host.goal.moves = [{ number: 1, status: 'ready', step: 0, step_key: keys[0] }];
  await assert.rejects(controls.command(command('skip', 0), review), /Met or Redo/);
});

test('Start painting with no open step left finishes instead of painting; pacing finds no step to jump to', () => {
  const closed = { [keys[0]]: { skipped: true }, [keys[1]]: { met: 'artist' }, [keys[2]]: { skipped: true }, [keys[3]]: { skipped: true } };
  const host = fakeHost({ folder: false, goal: { current_step: 0, step_marks: closed } });
  const controls = planStepControls(host);
  assert.equal(controls.settleCurrent(), false);
  assert.equal(controls.nextOpen(1), -1, 'none left');
  host.goal.step_marks = { [keys[1]]: { skipped: true }, [keys[2]]: { met: 'artist' } };
  assert.equal(controls.nextOpen(1), 3);
  assert.equal(controls.jumpNote(0, 3), ' The artist skipped or marked met steps 2, 3: paint nothing for them.');
  host.goal.step_marks = { [keys[2]]: { skipped: true } };
  assert.equal(controls.jumpNote(0, 3), ' The canvas already shows step 2. The artist skipped or marked met step 3: paint nothing for it.');
  host.goal.current_step = 3; host.goal.step_marks = { [keys[3]]: { skipped: true } };
  assert.equal(controls.settleCurrent(), true);
  assert.equal(host.goal.current_step, 0, 'a step restored before the current one is still painted');
});

test('Agent mode: Good enough lets the batch finish, refuses more painting except the move\'s own reference job, then keeps the move and starts the next open step', () => chatFolder(async dir => {
  const host = fakeHost({ busy: true, dir, goal: { status: 'active', step_marks: { [keys[1]]: { skipped: true } }, reference_jobs: { ['a'.repeat(32)]: [1], ['b'.repeat(32)]: [0] } } });
  const move = { number: 1, status: 'painting', step: 0, step_key: keys[0], calls: 2, review: { verdict: 'warned' }, review_line: 'Luna warned: seam' };
  host.state.move = move; host.goal.moves = [move];
  const controls = planStepControls(host);
  await assert.rejects(controls.command(command('good_enough', 2), reviewer(controls)), /not painting/);
  controls.beforeBatch(); controls.batchEnded();             // a batch of the step finished: counted for the lesson
  await controls.command(command('good_enough', 0), reviewer(controls));
  assert.equal(move.finished, true, 'the move ends after the turn in progress');
  assert.equal(move.good_enough, undefined, 'nothing about it is saved to act on after a resume');
  assert.equal(controls.view(host.goal)[0].state, 'finishing');
  assert.throws(() => controls.beforeBatch({ tool: 'paint_batch' }), /Nothing was painted: the artist marked this step good enough/);
  assert.throws(() => controls.beforeBatch({ tool: 'continue_reference_painting', args: { job_id: 'b'.repeat(32) } }), /good enough/, 'another move\'s job');
  assert.doesNotThrow(() => controls.beforeBatch({ tool: 'continue_reference_painting', args: { job_id: 'a'.repeat(32) } }), 'this move\'s transfer may finish');
  controls.batchEnded();
  host.state.busy = false; host.state.move = undefined; move.status = 'ready';       // the move ended
  await controls.afterRun();
  assert.deepEqual(host.goal.step_marks[keys[0]], { met: 'good_enough' });
  assert.deepEqual(host.calls.filter(c => /^(keepMove|tickFolderStep|mayContinue|nextStepMove)/.test(c)), ['keepMove 1 marks:{"' + keys[1] + '":{"skipped":true}}', 'tickFolderStep 1', 'mayContinue true', 'nextStepMove 0'],
    'kept first, then marked and ticked, then on');
  await controls.afterRun();
  assert.equal(host.calls.filter(c => c.startsWith('keepMove')).length, 1, 'once');
  const lessons = (await readFile(join(dir, LESSONS_FILE), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.equal(lessons.length, 1);
  const [lesson] = lessons;
  assert.equal(lesson.kind, 'good_enough'); assert.equal(lesson.mode, 'agent');
  assert.deepEqual(lesson.step, { number: 1, title: 'Underpainting', key: keys[0] });
  assert.equal(lesson.batches, 1); assert.equal(lesson.move, 1);
  assert.deepEqual(lesson.luna, { verdict: 'warned', line: 'Luna warned: seam' });
  assert.equal(lesson.goal_likeness, null);
  assert.ok(Date.parse(lesson.at) > 0);
}));

test('after Stop, an error or a mode switch, Good enough keeps the move and marks the step but starts nothing', async () => {
  const host = fakeHost({ busy: true, folder: false, mayContinue: auto => !auto, goal: { status: 'active' } });
  const move = { number: 1, status: 'painting', step: 0, step_key: keys[0] };
  host.state.move = move; host.goal.moves = [move];
  const controls = planStepControls(host);
  await controls.command(command('good_enough', 0), reviewer(controls));
  host.state.busy = false; host.state.move = undefined; move.status = 'ready';
  await controls.afterRun();
  assert.equal(move.status, 'kept'); assert.deepEqual(host.goal.done_steps, [0]);
  assert.deepEqual(host.goal.step_marks, { [keys[0]]: { met: 'good_enough' } });
  assert.ok(!host.calls.some(c => c.startsWith('nextStepMove')), host.calls.join('\n'));
  assert.ok(host.calls.some(c => /Press Start painting/.test(c)));
});

test('a Good enough from before a resume is never acted on', async () => {
  const host = fakeHost({ busy: true, folder: false, goal: { status: 'active' } });
  const move = { number: 1, status: 'painting', step: 0, step_key: keys[0] };
  host.state.move = move; host.goal.moves = [move];
  const controls = planStepControls(host);
  await controls.command(command('good_enough', 0), reviewer(controls));
  host.goal = { ...host.goal, moves: [{ ...move, status: 'ready' }] };      // the chat was resumed: its goal read again
  host.state.busy = false; host.state.move = undefined;
  await controls.afterRun();
  assert.ok(!host.calls.some(c => /^(keepMove|nextStepMove)/.test(c)), host.calls.join('\n'));
  assert.equal(host.goal.step_marks, undefined);
});

test('Agent mode without a folder: Good enough keeps the move, ticks the step and paints the next one not skipped', async () => {
  const host = fakeHost({ busy: true, folder: false, goal: { status: 'active', step_marks: { [keys[1]]: { skipped: true } } } });
  const move = { number: 1, status: 'painting', step: 0, step_key: keys[0], calls: 1 };
  host.state.move = move; host.goal.moves = [move];
  const controls = planStepControls(host);
  await controls.command(command('good_enough', 0), reviewer(controls));
  host.state.busy = false; host.state.move = undefined; move.status = 'ready';
  await controls.afterRun();
  assert.deepEqual(host.goal.done_steps, [0]);
  assert.equal(host.goal.current_step, 2, 'the skipped step 2 is passed over');
  assert.deepEqual(host.calls.filter(c => /^(keepMove|nextStepMove)/.test(c)), ['keepMove 1 marks:{"' + keys[1] + '":{"skipped":true}}', 'nextStepMove 2']);
  // The last open step: the plan is finished instead.
  const last = fakeHost({ busy: false, folder: false, goal: { status: 'move_ready', current_step: 3, done_steps: [0, 2], step_marks: { [keys[1]]: { skipped: true } } } });
  last.goal.moves = [{ number: 4, status: 'ready', step: 3, step_key: keys[3] }];
  const lastControls = planStepControls(last);
  await lastControls.command(command('met', 3), reviewer(lastControls));
  assert.deepEqual(last.goal.step_marks[keys[3]], { met: 'artist' });
  assert.ok(last.calls.some(c => c.startsWith('finish: ')), last.calls.join('\n'));
  assert.ok(!last.calls.some(c => c.startsWith('nextStepMove')));
});

test('Met keeps the finished step\'s move before marking it; Redo undoes it first, then counts it, then repaints the step', () => chatFolder(async dir => {
  const host = fakeHost({ dir, goal: { status: 'limited' } });
  const move = { number: 3, status: 'ready', step: 0, step_key: keys[0], calls: 4 };
  host.goal.moves = [move];
  const controls = planStepControls(host), review = reviewer(controls);
  await assert.rejects(controls.command(command('met', 1), review), /not finished/);
  host.state.failReject = true;
  await assert.rejects(controls.command(command('redo', 0, { text: 'darker' }), review), /reject failed/);
  assert.equal(host.goal.step_marks, undefined, 'a refused undo counts no redo');
  await assert.rejects(readFile(join(dir, LESSONS_FILE)), /ENOENT/, 'and keeps no lesson');
  host.state.failReject = false;
  await controls.command(command('redo', 0, { text: 'warmer light on the left' }), review);
  assert.deepEqual(host.calls.filter(c => /^(rejectMove|retryMove)/.test(c)), ['rejectMove 3', 'retryMove 3: warmer light on the left']);
  assert.deepEqual(host.goal.step_marks[keys[0]], { redone: 1 });
  move.status = 'ready';
  host.state.mode = 'ask';
  await assert.rejects(controls.command(command('met', 0), review), /switch to Agent/);
  host.state.mode = 'agent';
  await controls.command(command('met', 0), review);
  assert.deepEqual(host.goal.step_marks[keys[0]], { met: 'artist', redone: 1 });
  assert.ok(host.calls.some(c => c.startsWith('keepMove 3 marks:{"' + keys[0] + '":{"redone":1}}')), 'kept before it is marked met');
  const lessons = (await readFile(join(dir, LESSONS_FILE), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(lessons.map(l => [l.kind, l.text ?? null]), [['redo', 'warmer light on the left']], 'Met is no lesson');
  host.state.busy = true; move.status = 'ready';
  await assert.rejects(controls.command(command('met', 0), review), /Wait for the painting/);
}));

test('one Met or Redo at a time: a second answer while the first is under way is refused', async () => {
  const host = fakeHost({ folder: false, goal: { status: 'move_ready' } });
  const move = { number: 1, status: 'ready', step: 0, step_key: keys[0] };
  host.goal.moves = [move];
  let release; const held = new Promise(resolve => { release = resolve; });
  host.keepMove = async m => { await held; m.status = 'kept'; };
  const controls = planStepControls(host);
  const first = controls.met(move);
  assert.equal(controls.working(), true);
  await assert.rejects(controls.redo(move), /Wait for the painting/);
  release(); await first;
  assert.equal(controls.working(), false);
  assert.equal(controls.stepped(move), true);
  assert.equal(controls.stepped({ number: 2, status: 'ready' }), false, 'a move without a step is the move card\'s own');
});

test('Autopilot: Good enough after the batch in progress moves to the next open step and tells the painter', async () => {
  const host = fakeHost({ mode: 'autopilot', busy: true, folder: false, goal: { status: 'active', current_step: 0, step_marks: { [keys[1]]: { skipped: true } },
    pace_history: [{ step: 0, progress: 0.6, action: 'continue' }], reviews: [{ verdict: 'continue' }] } });
  const controls = planStepControls(host), review = reviewer(controls);
  controls.beforeBatch();                                      // a batch is painting when the artist presses
  await controls.command(command('good_enough', 0), review);
  assert.equal(host.goal.current_step, 0, 'nothing changes under the batch in progress');
  assert.equal(controls.view(host.goal)[0].state, 'finishing');
  controls.batchEnded();
  const response = controls.afterBatch({ content: [{ type: 'text', text: 'painted' }] });
  assert.equal(host.goal.current_step, 2);
  assert.deepEqual(host.goal.step_marks[keys[0]], { met: 'good_enough' });
  assert.match(JSON.parse(response.content.at(-1).text).host_pacing, /artist marked step 1 \("Underpainting"\) good enough.*Now paint step 3: "Soften the foreground/);
  assert.doesNotThrow(() => controls.beforeBatch());
  controls.batchEnded();
});

test('Autopilot: Good enough between batches moves on at once and redirects the next call; a run that ends drops the redirect', async () => {
  const host = fakeHost({ mode: 'autopilot', busy: true, folder: false, goal: { status: 'active', current_step: 2 } });
  const controls = planStepControls(host), review = reviewer(controls);
  await controls.command(command('good_enough', 2), review);
  assert.equal(host.goal.current_step, 3);
  assert.throws(() => controls.beforeBatch(), /Nothing was painted: the artist marked step 3 [^]*Now paint step 4/);
  assert.doesNotThrow(() => controls.beforeBatch(), 'only one call is redirected');
  controls.batchEnded();
  const last = fakeHost({ mode: 'autopilot', busy: true, folder: false, goal: { status: 'active', current_step: 3 } });
  const lastControls = planStepControls(last);
  await lastControls.command(command('good_enough', 3), reviewer(lastControls));
  last.state.busy = false;
  await lastControls.afterRun();                               // stopped before another call
  last.state.busy = true;
  assert.doesNotThrow(() => lastControls.beforeBatch(), 'the next run is not redirected by the old one');
});

test('lessons are appended in the chat folder only, never through a link or into a pipe', () => chatFolder(async dir => {
  await recordLesson(dir, { kind: 'redo', at: 'now' });
  await recordLesson(dir, { kind: 'good_enough', at: 'later' });
  assert.deepEqual((await readFile(join(dir, LESSONS_FILE), 'utf8')).trim().split('\n').map(l => JSON.parse(l).kind), ['redo', 'good_enough']);
  const outside = await mkdtemp(join(tmpdir(), 'plan-steps-outside-'));
  try {
    await rm(join(dir, LESSONS_FILE));
    await writeFile(join(outside, 'target.jsonl'), '');
    await symlink(join(outside, 'target.jsonl'), join(dir, LESSONS_FILE));
    await assert.rejects(recordLesson(dir, { kind: 'redo' }), /link/);
    assert.equal(await readFile(join(outside, 'target.jsonl'), 'utf8'), '');
    assert.deepEqual(await readdir(outside), ['target.jsonl']);
    await rm(join(dir, LESSONS_FILE));
    execFileSync('mkfifo', [join(dir, LESSONS_FILE)]);
    await assert.rejects(recordLesson(dir, { kind: 'redo' }), /not a plain file/, 'a pipe is refused without waiting for a reader');
  } finally { await rm(outside, { recursive: true, force: true }); }
}));

test('crisp-accents: a paint_accents call running at Good enough finishes, then the step closes and no more accents paint', async () => {
  const host = fakeHost({ busy: true, folder: false, goal: { status: 'active' } });
  const move = { number: 1, status: 'painting', step: 0, step_key: keys[0], calls: 1 };
  host.state.move = move; host.goal.moves = [move];
  const controls = planStepControls(host);
  assert.doesNotThrow(() => controls.beforeBatch({ tool: 'paint_accents', args: { reference_id: 'goal' } }), 'the accents call starts');
  await controls.command(command('good_enough', 0), reviewer(controls));   // the artist presses Good enough while it runs
  controls.batchEnded();                                                  // it finishes
  assert.throws(() => controls.beforeBatch({ tool: 'paint_accents', args: { reference_id: 'goal' } }), /good enough/, 'no further accents');
  host.state.busy = false; host.state.move = undefined; move.status = 'ready';
  await controls.afterRun();
  assert.deepEqual(host.goal.step_marks, { [keys[0]]: { met: 'good_enough' } });
  assert.ok(host.calls.some(c => c.startsWith('keepMove 1')), 'the move (with its Accents group) is kept');
});
