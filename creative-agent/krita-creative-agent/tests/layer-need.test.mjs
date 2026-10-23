import test from 'node:test';
import assert from 'node:assert/strict';
import { LAYER_NEEDS, NEED_HINTS, layerNeedCheck, paintedRole } from '../src/layer-need.mjs';

const client = answer => { const requests = []; return { requests, async decide(r) { requests.push(r); return { elapsed_ms: 1, usage: { cost: 0 }, ...answer(r) }; } }; };

test('Luna picks the layer an area needs next; the host maps it to craft', async () => {
  assert.deepEqual(LAYER_NEEDS, ['flat','shadow','light','texture','glow','depth','accents','done']);
  assert.ok(LAYER_NEEDS.every(need => NEED_HINTS[need]), 'every choice has a hint');
  const luna = client(() => ({ answers: { need: { type: 'choice', choice: 'texture', confidence: 0.82 } } }));
  const result = await layerNeedCheck({ client: luna, canvas: { type: 'image' }, reference: { type: 'image' }, area: 'the woman’s fur coat' });
  assert.deepEqual([result.need, result.confidence], ['texture', 0.82]);
  assert.match(result.hint, /clip_to and blend_mode overlay/);
  const [request] = luna.requests;
  assert.equal(request.purpose, 'choose-next-layer');
  assert.deepEqual(Object.keys(request.questions.need.criteria), LAYER_NEEDS);
  assert.match(request.questions.need.instructions, /the woman.s fur coat/);
  assert.deepEqual(request.parts.filter(p => typeof p === 'string'), ['REFERENCE (what the painting aims for):', 'CANVAS (the painting now):']);
});

test('fallbacks and unknown choices give no advice', async () => {
  assert.equal((await layerNeedCheck({ client: client(() => ({ fallback: 'timeout' })), canvas: {}, area: 'sky' })).fallback, 'timeout');
  assert.equal((await layerNeedCheck({ client: client(() => ({ answers: { need: { type: 'choice', choice: 'sparkle' } } })), canvas: {}, area: 'sky' })).fallback, 'service_or_response_error');
});

test('the painter’s call is read as the layer job it did', () => {
  const batch = actions => ({ tool: 'paint_batch', args: { actions: actions.map(([tool, args]) => ({ tool, arguments: args })) } });
  assert.equal(paintedRole(batch([['fill_region', { clip_base: true }], ['create_layer', { clip_to: '$1', blend_mode: 'multiply' }]])), 'flat');
  assert.equal(paintedRole({ tool: 'create_layer', args: { clip_to: 'a', blend_mode: 'multiply' } }), 'shadow');
  assert.equal(paintedRole({ tool: 'fill_region', args: { clip_to: 'a', blend_mode: 'add' } }), 'light');
  assert.equal(paintedRole({ tool: 'paint_recipe', args: { clip_to: 'a', blend_mode: 'overlay' } }), 'texture');
  assert.equal(paintedRole({ tool: 'set_layer', args: { layer_id: 'a', style: { outer_glow: {} } } }), 'glow');
  assert.equal(paintedRole({ tool: 'apply_filter', args: { filter: 'gaussian blur' } }), 'depth');
  assert.equal(paintedRole({ tool: 'paint_pass', args: { strokes: [] } }), 'strokes');
  assert.equal(paintedRole({ tool: 'observe_canvas', args: {} }), null);
});

test('the decision’s probabilities come back with the choice, for the ask-when-done nudge', async () => {
  const probabilities = { texture: 0.3, done: 0.27, accents: 0.2 };
  const luna = client(() => ({ answers: { need: { type: 'choice', choice: 'texture', confidence: 0.3, probabilities } } }));
  assert.deepEqual((await layerNeedCheck({ client: luna, canvas: {}, area: 'sky' })).probabilities, probabilities);
});
