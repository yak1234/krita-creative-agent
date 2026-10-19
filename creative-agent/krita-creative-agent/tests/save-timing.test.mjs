// Save timing: the shipped Pi extension that saves the painting while the model thinks. A fake `pi`, host and clock;
// writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import saveTiming, { QUIET_SAVE_MS } from '../extensions/save-timing.ts';

function setup({ painting = name => name !== 'observe_canvas' } = {}) {
  const handlers = {};
  let now = 0, saves = 0, finish = null;
  const host = { painting, checkpoint: () => { saves++; return new Promise(resolve => { finish = resolve; }); } };
  saveTiming(host, { now: () => now })({ on: (name, handler) => { handlers[name] = handler; } });
  let n = 0;
  const result = (details, { toolName = 'paint_batch', isError = false } = {}) =>
    handlers.tool_result({ type: 'tool_result', toolCallId: 'call' + ++n, toolName, input: {}, isError, content: [], details }, {});
  return { result, advance: ms => { now += ms; }, saves: () => saves, done: async () => { finish?.(); finish = null; await new Promise(r => setImmediate(r)); } };
}
const deferred = (extra = {}) => ({ checkpoint_deferred: true, unsaved_operations: 3, ...extra });

test('unsaved work is saved in the background once the quiet time has passed, never delaying the painter', async () => {
  const s = setup();
  assert.equal(await s.result(deferred()), undefined);
  assert.equal(s.saves(), 0, 'too soon after the start');
  s.advance(QUIET_SAVE_MS);
  const returned = await Promise.race([s.result(deferred()), new Promise(r => setTimeout(() => r('blocked'), 50))]);
  assert.equal(returned, undefined, 'the handler returns while the save is still running');
  assert.equal(s.saves(), 1);
});

test('one save at a time, and the clock restarts when it finishes', async () => {
  const s = setup();
  s.advance(QUIET_SAVE_MS); await s.result(deferred());
  await s.result(deferred()); await s.result(deferred());
  assert.equal(s.saves(), 1, 'a save in flight is never doubled');
  await s.done();
  await s.result(deferred());
  assert.equal(s.saves(), 1, 'just saved: wait for the quiet time again');
  s.advance(QUIET_SAVE_MS); await s.result(deferred());
  assert.equal(s.saves(), 2);
});

test('a heavy painting is saved after every call with unsaved work', async () => {
  const s = setup();
  await s.result(deferred({ weight: { level: 'heavy', reasons: [], fixes: [] } }));
  assert.equal(s.saves(), 1);
});

test('nothing to save, an inline save, an error or a non-painting call: no save', async () => {
  const s = setup();
  s.advance(QUIET_SAVE_MS);
  await s.result({ checkpoint: '/art/painting.kra', save_number: 4 });
  await s.result({ checkpoint_deferred: true, unsaved_operations: 0 });
  await s.result(deferred(), { isError: true });
  await s.result(deferred(), { toolName: 'observe_canvas' });
  assert.equal(s.saves(), 0);
  s.advance(QUIET_SAVE_MS - 1); await s.result(deferred());
  assert.equal(s.saves(), 0, 'the inline save restarted the clock');
});

test('a background save the plugin started counts as a save: no second one is asked for while it runs', async () => {
  const s = setup();
  s.advance(QUIET_SAVE_MS);
  await s.result(deferred({ save_job: { job: 3, state: 'running' } }));
  assert.equal(s.saves(), 0, 'the plugin is already saving: a checkpoint now would only wait for it');
  s.advance(QUIET_SAVE_MS - 1); await s.result(deferred());
  assert.equal(s.saves(), 0, 'the clock restarted when that save began');
  s.advance(1); await s.result(deferred({ save_job: { job: 3, state: 'done', ms: 5000 } }));
  assert.equal(s.saves(), 1, 'actions after its copy are still unsaved: saved once the quiet time has passed');
});

test('the companion registers it, with the studio checkpoint', async () => {
  const { saveTimingExtension } = await import('../src/extensions.mjs');
  const entry = saveTimingExtension({ painting: () => true, checkpoint: async () => {} });
  assert.equal(entry.name, 'save-timing'); assert.equal(typeof entry.factory, 'function');
});
