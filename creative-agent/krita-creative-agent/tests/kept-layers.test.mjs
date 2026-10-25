// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Layer plan (openspec layer-plan goals 1, 4 and 6): what a kept move's work becomes when Met merges it, and the painter's
// one-line view of the layer stack. Pure functions: no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { keptLayer, stackSummary } from '../src/kept-layers.ts';

test('a kept plan step merges into one layer named after it; the underpainting is locked', () => {
  assert.deepEqual(keptLayer({ title: 'Underpainting from the goal image', scope: 'whole composition' }, { number: 2 }), { name: 'Underpainting', lock: true });
  assert.deepEqual(keptLayer({ title: 'Block in the masses', kind: 'underpainting' }, { number: 2 }), { name: 'Underpainting', lock: true });
  assert.deepEqual(keptLayer({ title: 'Finish' }, { number: 3 }), { name: 'Finish', lock: false });
  assert.deepEqual(keptLayer({ title: 'Refine: Domed church and bell tower' }, { number: 4 }), { name: 'Refine: Domed church and bell tower', lock: false });
  assert.deepEqual(keptLayer({ title: 'Moonlit sky (assets/01-moonlit-sky.png)', scope: 'assets/01-moonlit-sky.png' }, { number: 5 }), { name: 'Moonlit sky', lock: false });
  assert.deepEqual(keptLayer({ title: 'Crisp accents' }, { number: 6 }), { name: 'Crisp accents', lock: false });
});

test('a kept move outside the plan keeps its move name', () => {
  assert.deepEqual(keptLayer(undefined, { number: 7, title: 'Towers' }), { name: 'Move 7 · Towers', lock: false });
  assert.deepEqual(keptLayer(undefined, { number: 8 }), { name: 'Move 8 · kept', lock: false });
  assert.equal(keptLayer(undefined, { number: 9, title: 'x'.repeat(200) }).name.length, 'Move 9 · '.length + 80);
});

const layer = (name, extra = {}) => ({ id: name, name, type: 'paintlayer', depth: 0, visible: true, editable_by_agent: true, ...extra });

test('the painter sees the top-level stack, bottom to top, with the locked base and where its move paints', () => {
  const layers = [layer('Background'), layer('Underpainting', { editable_by_agent: false }), layer('Finish'),
    layer('Creative Agent · move-4', { type: 'grouplayer' }), layer('Sky 1', { depth: 1 }), layer('Sky 2', { depth: 1, visible: false })];
  const text = stackSummary(layers, { move: 4 });
  assert.equal(text, '6 layers. Top level, bottom to top: Background · Underpainting (locked) · Finish · Creative Agent · move-4 (group of 2, 1 hidden). '
    + 'This move paints in its own group "Creative Agent · move-4" at the top; when the artist keeps it, it merges into one layer. Never paint on a locked layer.');
  assert.equal(stackSummary(layers.slice(0, 3), { move: 5 }), '3 layers. Top level, bottom to top: Background · Underpainting (locked) · Finish. '
    + 'This move paints in a new group "Creative Agent · move-5" at the top; when the artist keeps it, it merges into one layer. Never paint on a locked layer.');
  assert.equal(stackSummary([layer('Background')], {}), '1 layer. Top level, bottom to top: Background.', 'no move: no move line, no lock line');
  assert.equal(stackSummary([], { move: 1 }), undefined);
  assert.equal(stackSummary(undefined, { move: 1 }), undefined);
});

test('a long stack names the top-level layers nearest the top, and says how many are below', () => {
  const layers = Array.from({ length: 30 }, (_, i) => layer('Layer ' + (i + 1)));
  const text = stackSummary(layers, {});
  assert.match(text, /^30 layers\. Top level, bottom to top: 18 more below · Layer 19 · .* · Layer 30\.$/);
  assert.ok(text.length < 400);
});
