import test from 'node:test';
import assert from 'node:assert/strict';
import { unifyActions, unifyRefusal, WHOLE_CANVAS_SHARE } from '../src/unify-pass.ts';

const canvas = { width: 6000, height: 4500, layers: [{ id: 'g', name: 'City', type: 'grouplayer' }, { id: 'light', name: 'Lamp light copy', type: 'paintlayer' },
  { id: 'under', name: 'Underpainting · Coarse', type: 'paintlayer' }] };
const wholeLayers = new Set(['under']);
const stroke = (x0, y0, x1, y1) => ({ start: [x0, y0], segments: [[x0, y0, x1, y1, x1, y1]], size: 200, opacity: 1, flow: 1, color: '#808080' });

// after-the-underpainting goal 3: a traced chat ran four whole-canvas smudge transfers ("Fuse dabs", "Soften every
// mass", "Big smudge masses"...) and a filter over the underpainting.
test('whole-canvas softening is a blend or smoothing filter whose target covers at least 60% of the canvas', () => {
  assert.equal(WHOLE_CANVAS_SHARE, 0.6);
  const surface = { tool: 'paint_reference_surface', args: { name: 'Fuse dabs', reference_id: 'r', preset: 'k) Blender Basic', source: [0, 0, 1448, 1086], target: [0, 0, 6000, 4500] } };
  assert.deepEqual(unifyActions(surface, canvas).map(a => [a.what, a.share]), [['paint_reference_surface "Fuse dabs"', 1]]);
  assert.deepEqual(unifyActions({ ...surface, args: { ...surface.args, target: [0, 0, 2000, 1500] } }, canvas), [], 'a region (11%)');
  const smudge = { tool: 'paint_pass', args: { name: 'Soften every mass', preset: 'k) Blender Basic', strokes: [stroke(0, 0, 6000, 4500)] } };
  assert.equal(unifyActions(smudge, canvas)[0].what, 'smudge pass "Soften every mass"');
  assert.deepEqual(unifyActions({ ...smudge, args: { ...smudge.args, strokes: [stroke(100, 100, 1500, 1500)] } }, canvas), [], 'strokes in one element');
  assert.deepEqual(unifyActions({ ...smudge, args: { ...smudge.args, preset: 'b) Basic-1' } }, canvas), [], 'paint, not a blend');
  assert.equal(unifyActions({ tool: 'paint_pass', args: { name: 'Overlay', preset: 'b) Basic-1', smudge_overlay: true, region: [0, 0, 6000, 3000], strokes: [stroke(0, 0, 10, 10)] } }, canvas).length, 1, 'a smudge overlay over its region (67%)');
  const blur = { tool: 'apply_filter', args: { target: 'under', filter: 'blur', mode: 'copy' } };
  assert.equal(unifyActions(blur, canvas, { wholeLayers })[0].what, 'blur filter', 'no limit, on a layer a whole-canvas transfer made');
  assert.equal(unifyActions({ ...blur, args: { ...blur.args, target: 'g' } }, canvas, { wholeLayers }).length, 1, 'no limit, on a group');
  assert.deepEqual(unifyActions({ ...blur, args: { ...blur.args, target: 'light' } }, canvas, { wholeLayers }), [], 'bloom: a blur of a small light layer copy');
  assert.deepEqual(unifyActions({ ...blur, args: { ...blur.args, target: 'unknown' } }, canvas, { wholeLayers }), [], 'a layer of unknown extent');
  assert.deepEqual(unifyActions({ ...smudge, args: { ...smudge.args, selection: 'Sky' } }, canvas), [], 'a smudge pass inside a selection is scoped');
  assert.deepEqual(unifyActions({ ...smudge, args: { ...smudge.args, inside_shape: 'Woman' } }, canvas), [], 'inside an element\'s shape is scoped');
  const reach = { ...smudge, args: { ...smudge.args, strokes: [{ ...stroke(0, 0, 4400, 3600), size: 400 }] } };
  assert.equal(unifyActions(reach, canvas).length, 1, 'the strokes reach half a brush past their points (58.7% of the canvas without it)');
  assert.deepEqual(unifyActions({ ...blur, args: { ...blur.args, selection: 'Sky' } }, canvas, { wholeLayers }), [], 'scoped to a named selection');
  assert.deepEqual(unifyActions({ ...blur, args: { ...blur.args, area: [{ shape: 'ellipse', bounds: [2000, 1000, 1000, 1500] }] } }, canvas, { wholeLayers }), [], 'scoped to a small area');
  assert.equal(unifyActions({ ...blur, args: { ...blur.args, target: 'light', area: [{ shape: 'rectangle', bounds: [0, 0, 6000, 4000] }] } }, canvas).length, 1, 'an area over most of the canvas');
  assert.deepEqual(unifyActions({ ...blur, args: { ...blur.args, filter: 'colorbalance' } }, canvas, { wholeLayers }), [], 'a colour grade is not softening');
  const batch = { tool: 'paint_batch', args: { actions: [{ tool: 'paint_pass', arguments: smudge.args }, { tool: 'apply_filter', arguments: blur.args }] } };
  assert.deepEqual(unifyActions(batch, canvas, { wholeLayers }).map(a => a.index), [0, 1], 'each action of a batch, with its index');
});

test('the refusal names the earlier pass and asks for softening scoped to an element or region', () => {
  const message = unifyRefusal({ tool: 'apply_filter', what: 'blur filter', share: 0.9 }, { what: 'paint_reference_surface "Fuse dabs"' });
  assert.match(message, /paint_reference_surface "Fuse dabs"/);
  assert.match(message, /blur filter covers 90% of the canvas/);
  assert.match(message, /one element or region/);
  assert.match(message, /60%/);
});
