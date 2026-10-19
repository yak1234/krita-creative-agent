// Painting weight: the shipped Pi extension that tells the painter what makes the painting heavy for Krita, from the
// `weight` observations carry (painting_weight.py). A fake `pi` and clock; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import paintingWeight, { SLOW_MS } from '../extensions/painting-weight.ts';
import { modelResultText } from '../src/tools.mjs';

const HEAVY = { level: 'too_heavy', reasons: ['10 live filter masks (wavelet noise reducer) recompute on every refresh', '147 groups each cache a projection (about 15876 MB)', 'about 21000 MB estimated in memory'],
  fixes: ['bake_filters', 'merge_kept'] };

function setup() {
  const handlers = {};
  let now = 0;
  paintingWeight({ now: () => now })({ on: (name, handler) => { handlers[name] = handler; } });
  let n = 0;
  const call = async (toolName, details, ms = 1000) => {
    const toolCallId = 'call' + ++n;
    handlers.tool_execution_start?.({ toolCallId, toolName }, {});
    now += ms;
    const changed = await handlers.tool_result({ type: 'tool_result', toolCallId, toolName, input: {}, isError: false,
      content: [{ type: 'text', text: '{"status":"ok"}' }], details }, {});
    const text = changed?.content?.slice(1).map(c => c.text).join(' ');
    return text ? JSON.parse(text).painting_weight : null;
  };
  return { call };
}

test('the painter hears once, when the level rises, what makes the painting heavy and how to work with it', async () => {
  const { call } = setup();
  const line = await call('observe_canvas', { weight: HEAVY });
  assert.match(line, /^This painting is too heavy for Krita: 10 live filter masks \(wavelet noise reducer\)/);
  assert.match(line, /fewer, larger batches/);
  assert.match(line, /do not add filter masks/);
  assert.ok(line.length <= 400, line.length);
  assert.equal(await call('observe_canvas', { weight: HEAVY }), null, 'not repeated');
});

test('a light painting says nothing', async () => {
  const { call } = setup();
  assert.equal(await call('observe_canvas', { weight: { level: 'ok', reasons: [], fixes: [] } }), null);
  assert.equal(await call('paint_batch', {}, SLOW_MS * 3), null, 'slow on a light painting is not blamed on weight');
});

test('a slow call on a heavy painting names the likely cause, once per cause', async () => {
  const { call } = setup();
  await call('observe_canvas', { weight: HEAVY });
  const slow = await call('fill_region', {}, SLOW_MS + 1000);
  assert.match(slow, /^That fill_region took 61 s: 10 live filter masks \(wavelet noise reducer\) recompute on every refresh/);
  assert.equal(await call('paint_pass', {}, SLOW_MS + 5000), null, 'the same cause is not repeated');
  assert.equal(await call('paint_pass', {}, 2000), null, 'fast calls say nothing');
});

test('the weight is host bookkeeping: it never reaches the model in the result text', () => {
  assert.ok(!modelResultText({ status: 'ok', weight: HEAVY }).includes('wavelet'));
});

test('the companion registers it for every painting session', async () => {
  const { PAINTING_WEIGHT } = await import('../src/extensions.mjs');
  assert.equal(PAINTING_WEIGHT.name, 'painting-weight');
  assert.equal(typeof PAINTING_WEIGHT.factory, 'function');
});
