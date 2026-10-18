// Tool choice: which Krita methods a painter's calls used, scored against what a good run uses. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { methodsOf, scoreToolChoice, toolCallsFromEntries, summarizeRuns, compareReports } from '../src/tool-choice.ts';

const canvas = { width: 1000, height: 1000 };

test('methodsOf names the Krita method of each call', () => {
  const cases = [
    [{ tool: 'select', args: { name: 'Sky', steps: [{ seed: [10, 10] }] } }, ['seed']],
    [{ tool: 'select', args: { name: 'Sky', steps: [{ shape: 'rectangle', bounds: [0, 0, 5, 5] }] } }, ['select']],
    [{ tool: 'split_by_color', args: { source: 'visible' } }, ['split']],
    [{ tool: 'fill_region', args: { name: 'Sky' } }, ['fill']],
    [{ tool: 'create_layer', args: { name: 'Glow', type: 'fill', generator: 'gradient' } }, ['fill_layer']],
    [{ tool: 'create_layer', args: { name: 'Shadow', type: 'paint' } }, ['layer']],
    [{ tool: 'apply_filter', args: { target: 'L', filter: 'blur' } }, ['filter_mask']],
    [{ tool: 'apply_filter', args: { target: 'L', filter: 'blur', mode: 'copy' } }, ['filter']],
    [{ tool: 'clone_layer', args: { source: 'L', name: 'C' } }, ['clone']],
    [{ tool: 'krita_action', args: { action: 'mirrorNodeX', target: 'L' } }, ['action']],
    [{ tool: 'observe_canvas', args: {} }, ['look']],
    [{ tool: 'paint_pass', args: { name: 'Accent', strokes: [{ start: [10, 10], segments: [[12, 12, 14, 14, 20, 20]] }] } }, ['strokes']],
    [{ tool: 'paint_recipe', args: { name: 'Sky', region: [0, 0, 1000, 400] } }, ['strokes', 'strokes_mass']],
    [{ tool: 'paint_recipe', args: { name: 'Fur', region: [0, 0, 1000, 400], clip_to: '$1', blend_mode: 'overlay' } }, ['strokes']],
  ];
  for (const [call, methods] of cases) assert.deepEqual(methodsOf(call, canvas), methods, call.tool);
  assert.deepEqual(methodsOf({ tool: 'paint_batch', args: { actions: [
    { tool: 'fill_region', arguments: { name: 'Sky' } }, { tool: 'paint_recipe', arguments: { name: 'Clouds', region: [0, 0, 1000, 400] } }] } }, canvas),
  ['fill', 'strokes', 'strokes_mass'], 'a batch is its actions');
});

const sky = { id: 'moscow-sky', painting: 'new_moscow', prompt: 'Repaint the sky to look more natural.',
  good: [['seed', 'split'], ['fill', 'fill_layer']], bad: ['strokes_mass'] };

test('a sky repainted with a seed and a fill scores 1; a stroke mass is penalised', () => {
  const good = scoreToolChoice([{ tool: 'select', args: { steps: [{ seed: [1, 1] }] } }, { tool: 'fill_region', args: {} }], sky, canvas);
  assert.deepEqual(good, { used: ['seed', 'fill'], score: 1, missing: [], avoided: [] });
  const hammer = scoreToolChoice([{ tool: 'observe_canvas', args: {} }, { tool: 'paint_recipe', args: { region: [0, 0, 1000, 400] } }], sky, canvas);
  assert.deepEqual(hammer.missing, ['seed|split', 'fill|fill_layer']);
  assert.deepEqual(hammer.avoided, ['strokes_mass']);
  assert.equal(hammer.score, 0);
  const mixed = scoreToolChoice([{ tool: 'split_by_color', args: {} }, { tool: 'fill_region', args: {} }, { tool: 'paint_recipe', args: { region: [0, 0, 1000, 400] } }], sky, canvas);
  assert.ok(mixed.score > 0 && mixed.score < 1, 'the right methods, with a stroke mass on top');
});

test('tool calls are read from a chat’s session entries', () => {
  const entries = [
    { type: 'message', message: { role: 'user', content: [{ type: 'text', text: 'Repaint the sky.' }] } },
    { type: 'message', message: { role: 'assistant', content: [{ type: 'text', text: 'Seed-select the sky.' },
      { type: 'toolCall', id: 'a', name: 'select', arguments: { steps: [{ seed: [1, 1] }] } }] } },
    { type: 'message', message: { role: 'toolResult', toolCallId: 'a', content: [] } },
    { type: 'message', message: { role: 'assistant', content: [{ type: 'toolCall', id: 'b', name: 'fill_region', arguments: { name: 'Sky' } }] } },
  ];
  assert.deepEqual(toolCallsFromEntries(entries), [{ tool: 'select', args: { steps: [{ seed: [1, 1] }] } }, { tool: 'fill_region', args: { name: 'Sky' } }]);
});

test('runs are summarised as counts, with runs that changed nothing named', () => {
  const runs = [
    { run: 1, used: ['seed', 'fill'], score: 1, painted: true },
    { run: 2, used: ['split', 'fill'], score: 1, painted: true },
    { run: 3, used: ['look'], score: 0, painted: false },
  ];
  const summary = summarizeRuns(sky, runs);
  assert.deepEqual(summary.counts, { seed: 1, fill: 2, split: 1, look: 1 });
  assert.deepEqual(summary.good, { 'seed|split': '2/3', 'fill|fill_layer': '2/3' });
  assert.deepEqual(summary.bad, { strokes_mass: '0/3' });
  assert.equal(summary.mean_score, 0.67);
  assert.deepEqual(summary.changed_nothing, [3]);
});

test('comparing two reports marks a one-run difference as noise', () => {
  const report = (seed, fill) => ({ runs_per_scenario: 3, scenarios: [{ id: 'moscow-sky', good: { 'seed|split': seed, 'fill|fill_layer': fill }, bad: { strokes_mass: '0/3' }, mean_score: 0.5 }] });
  const [row] = compareReports(report('0/3', '2/3'), report('3/3', '3/3'));
  assert.equal(row.id, 'moscow-sky');
  assert.deepEqual(row.changes, [{ method: 'seed|split', before: '0/3', after: '3/3', verdict: 'changed' },
    { method: 'fill|fill_layer', before: '2/3', after: '3/3', verdict: 'noise' }]);
});
