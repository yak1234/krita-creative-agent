// Tests for the internal evaluation and training scripts; not published with the public repo.
import test from 'node:test';
import assert from 'node:assert/strict';

test('the evaluation summary compares Luna with the painter and lists disagreements to label', async () => {
  const { summarize } = await import('../scripts/evaluate-layer-need.mjs');
  const report = summarize([{ need: 'texture', painted: 'texture' }, { need: 'flat', painted: 'strokes', area: 'coat' },
    { need: 'accents', painted: 'strokes' }, { fallback: 'timeout' }]);
  assert.deepEqual([report.decisions, report.fallbacks, report.compared, report.agreement], [4, 1, 3, 0.67]);
  assert.deepEqual(report.by_need.flat.painter_did, { strokes: 1 });
  assert.deepEqual(report.to_label.map(e => e.area), ['coat']);
});
