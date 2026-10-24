// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Typed strokes after the underpainting (the artist, 2026-10-23): a few small marks per call, unless the artist asks
// for hand-painted work. Pure functions; nothing is written.
import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_MARKS, MAX_WIDTH_SHARE, typedMarks, typedStrokeRefusal, handPaintingRequested, widthCap } from '../src/typed-strokes.ts';

const canvas = { width: 6000, height: 4000 };
const stroke = size => ({ start: [10, 10], segments: [[20, 20, 30, 30, 40, 40]], size, opacity: 1, flow: 1, color: '#ffffff' });
const pass = (n, size = 8) => ({ tool: 'paint_pass', args: { name: 'Marks', preset: 'b) Basic-1', strokes: Array.from({ length: n }, () => stroke(size)) } });
const command = (tool, parameters) => ({ tool, parameters_json: JSON.stringify(parameters) });

test('the cap: twelve marks a call, each at most 2% of the canvas long side', () => {
  assert.equal(MAX_MARKS, 12); assert.equal(MAX_WIDTH_SHARE, 0.02);
  assert.equal(widthCap(canvas), 120); assert.equal(widthCap({ width: 768, height: 1024 }), 20);
  assert.equal(typedStrokeRefusal(pass(12, 120), canvas), null, 'twelve small marks pass');
  assert.match(typedStrokeRefusal(pass(13), canvas) ?? '', /13 marks/);
  assert.match(typedStrokeRefusal(pass(1, 121), canvas) ?? '', /121 px/);
  const refusal = typedStrokeRefusal(pass(40, 300), canvas) ?? '';
  assert.match(refusal, /^Nothing was painted/); assert.match(refusal, /paint_accents/); assert.match(refusal, /ask the artist/i);
  assert.match(refusal, /hand-painted/);
});

test('what counts as typed marks: passes, toolbox strokes and shapes, contours, stamps and recipes, summed over a batch', () => {
  assert.deepEqual(typedMarks(pass(3, 9)), { marks: 3, widest: 9, broad: [] });
  const toolbox = { tool: 'painting_toolbox', args: { name: 't', commands: [command('set_brush', { size: 30 }), command('curve_stroke', { start: [0, 0], segments: [[1, 1, 2, 2, 3, 3]] }),
    command('stroke', { points: [[0, 0, 1]], size: 6 }), command('draw_shape', { shape: 'ellipse', x: 0, y: 0, width: 400, height: 200, fill: true }),
    command('fill', { x: 5, y: 5, radius: 50 }), command('selection', { shape: 'rectangle', bounds: [0, 0, 10, 10] }), command('flood_fill', { x: 1, y: 1 })] } };
  assert.deepEqual(typedMarks(toolbox), { marks: 4, widest: 200, broad: ['flood_fill'] }, 'a stroke without a size takes set_brush’s');
  const contours = { tool: 'paint_contours', args: { name: 'c', preset: 'p', shapes: [{ color: '#000000', points: [[0, 0], [300, 0], [300, 40]] }] } };
  assert.deepEqual(typedMarks(contours), { marks: 1, widest: 40, broad: [] }, 'a contour is as wide as its thinner side');
  assert.deepEqual(typedMarks({ tool: 'stamp_material', args: { material: 'snow' } }), { marks: 400, widest: 0, broad: [] }, 'stamp_material: 400 dabs by default');
  assert.deepEqual(typedMarks({ tool: 'stamp_material', args: { count: 6, size: [10, 30] } }), { marks: 6, widest: 30, broad: [] });
  assert.deepEqual(typedMarks({ tool: 'paint_recipe', args: {} }), { marks: 0, widest: 0, broad: ['paint_recipe'] });
  const batch = { tool: 'paint_batch', args: { actions: [{ tool: 'paint_pass', arguments: pass(5, 10).args }, { tool: 'paint_pass', arguments: pass(8, 12).args },
    { tool: 'fill_region', arguments: {} }] } };
  assert.deepEqual(typedMarks(batch), { marks: 13, widest: 12, broad: [] });
  assert.match(typedStrokeRefusal(batch, canvas) ?? '', /13 marks/);
  assert.match(typedStrokeRefusal({ tool: 'paint_recipe', args: {} }, canvas) ?? '', /paint_recipe/);
  for (const tool of ['paint_accents', 'fill_region', 'apply_filter', 'paint_from_reference', 'adjust_layer', 'create_layer'])
    assert.equal(typedMarks({ tool, args: {} }), null, tool + ' is not typed strokes');
  assert.equal(typedStrokeRefusal({ tool: 'paint_batch', args: { actions: [{ tool: 'adjust_layer', arguments: {} }] } }, canvas), null);
  assert.equal(typedMarks({ tool: 'painting_toolbox', args: { commands: [{ tool: 'stroke', parameters_json: '{not json' }] } }).marks, 1, 'unreadable parameters still count as a mark');
});

test('handPaintingRequested: only an explicit ask for hand-painted work, never a refusal of it', () => {
  for (const text of ['Hand-paint the towers, please.', 'Paint the coat by hand', 'I want visible brushstrokes on the sky', 'Do it freehand.',
    'Use your own strokes for the car', 'paint it in your own brushstrokes'])
    assert.ok(handPaintingRequested(text), text);
  for (const text of ['Refine the towers.', 'Don’t paint it by hand.', 'no hand painting this time', 'never freehand', 'Stop the brush strokes, they look mechanical.',
    'without your own strokes', ''])
    assert.equal(handPaintingRequested(text), null, text);
});

test('the painter’s guidance states the cap: the prompt, reference-transfer and guided-trace', async () => {
  const { readFileSync } = await import('node:fs');
  const { PAINTING_INSTRUCTIONS } = await import('../src/prompt.mjs');
  const skill = name => readFileSync(new URL(`../skills/${name}/SKILL.md`, import.meta.url), 'utf8');
  const cap = new RegExp(`at most ${MAX_MARKS} small marks a call unless the artist asks for hand-painted work`);
  assert.match(PAINTING_INSTRUCTIONS, cap);
  assert.match(skill('reference-transfer'), cap);
  assert.doesNotMatch(skill('reference-transfer'), /Realism comes from your own strokes/, 'refined, not repainted');
  assert.match(skill('guided-trace'), cap);
});
