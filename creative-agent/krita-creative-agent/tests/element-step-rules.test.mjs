// What an element step may use (element-step-rules.ts): colour splits and colour selections, materials and typed strokes
// are refused unless the artist asked for them; the refusal points to the scoped transfer and accents. The calls are the
// ones the painter sent in the live chat 385b4a4f ("Moonlit sky", 2026-10-24).
import test from 'node:test';
import assert from 'node:assert/strict';
import { callKinds, askedFor, elementStepRefusal, refineSequence } from '../src/element-step-rules.ts';

const stroke = { start: [10, 10], segments: [[20, 20, 30, 30, 40, 40]], size: 8, opacity: 1, flow: 1, color: '#223344' };
const wand = { tool: 'select', args: { name: 'Sky', steps: [{ seed: [400, 80], tolerance: 45 }, { seed: [900, 60], tolerance: 45, mode: 'add' }] } };

test('the kinds a call holds, in a batch too', () => {
  assert.deepEqual(callKinds(wand), ['colour_selection']);
  assert.deepEqual(callKinds({ tool: 'select', args: { name: 'Range', steps: [{ color: '#203050', tolerance: 30 }] } }), ['colour_selection']);
  assert.deepEqual(callKinds({ tool: 'select', args: { name: 'Box', steps: [{ shape: 'polygon', points: [[0, 0], [9, 0], [9, 9]] }] } }), []);
  assert.deepEqual(callKinds({ tool: 'split_by_color', args: {} }), ['colour_split']);
  assert.deepEqual(callKinds({ tool: 'make_material', args: {} }), ['material']);
  assert.deepEqual(callKinds({ tool: 'stamp_material', args: { count: 20 } }), ['material'], 'a stamp is a material, not typed strokes twice');
  assert.deepEqual(callKinds({ tool: 'bucket_fill', args: { x: 1, y: 1, options: { mode: 'similar' } } }), ['colour_selection']);
  assert.deepEqual(callKinds({ tool: 'fill_region', args: { name: 'Sky', area: [{ seed: [5, 5] }], color: '#102030' } }), ['colour_selection']);
  assert.deepEqual(callKinds({ tool: 'fill_region', args: { name: 'Sky', area: [{ shape: 'rectangle', bounds: [0, 0, 9, 9] }], color: '#102030' } }), []);
  assert.deepEqual(callKinds({ tool: 'paint_pass', args: { strokes: [stroke] } }), ['typed_strokes']);
  assert.deepEqual(callKinds({ tool: 'paint_batch', args: { actions: [{ tool: 'select', arguments: wand.args }, { tool: 'paint_pass', arguments: { strokes: [stroke] } }] } }).sort(),
    ['colour_selection', 'typed_strokes']);
  assert.deepEqual(callKinds({ tool: 'paint_batch', args: { actions: [{ tool: 'adjust_layer', arguments: { layer_id: 'x', opacity: 0.5 } }] } }), []);
  assert.deepEqual(callKinds({ tool: 'apply_filter', args: { layer_id: 'x', filter: 'blur' } }), []);
});

test('the artist asking for it lets it through; a refusal of it does not', () => {
  assert.equal(askedFor('colour_selection', 'Use the magic wand on the sky.'), true);
  assert.equal(askedFor('colour_selection', 'Don’t use a magic wand.'), false);
  assert.equal(askedFor('colour_split', 'Split the sky by colour first.'), true);
  assert.equal(askedFor('material', 'Stamp some snow material on it.'), true);
  assert.equal(askedFor('material', 'Paint the moonlit sky.'), false);
  assert.equal(askedFor('typed_strokes', 'Paint the clouds by hand with visible brushstrokes.'), true);
  assert.equal(askedFor('typed_strokes', 'Paint the moonlit sky.'), false);
});

test('the refusal names what was refused and the sequence to use, with or without the area', () => {
  const refused = elementStepRefusal(wand, { part: 'Moonlit sky', area: true, request: 'Paint the moonlit sky.' });
  assert.match(refused, /^Nothing was painted: a selection made from colour \(a magic wand or a colour range\) is not used in an element step \(Moonlit sky\)/);
  assert.match(refused, /paint_from_reference of the goal image, the whole goal over the whole canvas: only the dabs inside the area are painted; then paint_finish and paint_accents/);
  const both = elementStepRefusal({ tool: 'paint_batch', args: { actions: [{ tool: 'split_by_color', arguments: {} }, { tool: 'paint_pass', arguments: { strokes: [stroke] } }] } },
    { part: 'Moonlit sky', area: false, request: '' });
  assert.match(both, /split_by_color and typed strokes are not used/);
  assert.match(both, /ask the artist for its area \(ask_for_selection\)/);
  assert.equal(elementStepRefusal(wand, { part: 'Moonlit sky', area: true, request: 'Select the sky with the magic wand.' }), null);
  assert.equal(elementStepRefusal({ tool: 'apply_filter', args: {} }, { part: 'Moonlit sky', area: true, request: '' }), null);
});

// Fine Finish (finish-stage goal 6, the artist 2026-10-24): after the whole-picture Finish an element or refine step does not
// underpaint the part again: it restrokes it fine at the goal's detail size, then accents. Typed strokes stay refused.
test('after the whole-picture Finish the sequence is paint_finish detail fine in the area, then paint_accents', () => {
  const refused = elementStepRefusal(wand, { part: 'Domed church', area: true, request: 'Refine the church.', finished: true });
  assert.match(refused, /paint_finish with detail "fine" in the area[^]*then paint_accents/);
  assert.doesNotMatch(refused, /paint_from_reference/);
  const asking = elementStepRefusal(wand, { part: 'Domed church', area: false, request: 'Refine the church.', finished: true });
  assert.match(asking, /ask_for_selection[^]*paint_finish with detail "fine"/);
  assert.equal(refineSequence({ area: true, finished: false }).includes('paint_from_reference'), true, 'before the Finish: as before');
  assert.match(refineSequence({ area: true, finished: true }), /more than 15% of the canvas[^]*refine_to_goal/, 'a large area is not a dead end');
  const strokes = elementStepRefusal({ tool: 'paint_pass', args: { strokes: [stroke] } }, { part: 'Domed church', area: true, request: 'Refine the church.', finished: true });
  assert.match(strokes, /typed strokes/);
});

test('refine_to_goal over the whole picture is refused in an element step without an area; with a box or the area it runs', () => {
  assert.match(elementStepRefusal({ tool: 'refine_to_goal', args: {} }, { part: 'Domed church', area: false, request: 'Refine it.', finished: true }), /refine_to_goal over the whole picture/);
  assert.equal(elementStepRefusal({ tool: 'refine_to_goal', args: {} }, { part: 'Domed church', area: true, request: 'Refine it.', finished: true }), null);
  assert.equal(elementStepRefusal({ tool: 'refine_to_goal', args: { area: { box: [0, 0, 10, 10] } } }, { part: 'Domed church', area: false, request: '', finished: true }), null);
});

// Luna's reading of the artist's message (luna-goal-reviewer goal 2): when the studio knows whether the message asked for
// hand-painted work (Luna's sure answer, else the phrases), that decides typed strokes, in any language.
test('typed strokes follow the studio’s reading of hand painting when it has one', () => {
  const typed = { tool: 'paint_pass', args: { strokes: [stroke] } };
  assert.equal(elementStepRefusal(typed, { part: 'Kremlin towers', area: true, request: 'Peins les tours à la main, avec des coups de pinceau visibles.', handPainting: true }), null);
  assert.match(elementStepRefusal(typed, { part: 'Kremlin towers', area: true, request: 'Paint the towers by hand.', handPainting: false }), /typed strokes is not used/);
  assert.equal(elementStepRefusal(typed, { part: 'Kremlin towers', area: true, request: 'Paint the towers by hand.' }), null, 'unknown: the phrases decide');
});
