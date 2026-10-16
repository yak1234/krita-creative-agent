import test from 'node:test';
import assert from 'node:assert/strict';
import { score } from '../scripts/calibrate-luna-artifacts.mjs';

const none = { splice: false, duplicate: false, flat_block: false, stripes: false, ellipses: false, hard_graphic: false };
const row = (probabilities, established, label) => ({ answer: { probabilities: { splice: 0, duplicate: 0, flat_block: 0, stripes: 0, ellipses: 0, hard_graphic: 0, ...probabilities }, established },
  label: { observation_id: 'o', note: 'n', blockin: false, undo: false, ...label, artifacts: { ...none, ...label.artifacts } } });

test('calibration scores flags per type, the stage answer and the undo rule against hand labels', () => {
  const report = score([
    row({ flat_block: 1 }, .99, { artifacts: { flat_block: true }, undo: true }),        // real damage, undone
    row({ flat_block: .95 }, .3, { artifacts: { flat_block: true }, blockin: true }),    // block-in: not reported, not undone
    row({ ellipses: .92 }, .98, { note: 'already in BEFORE' }),                          // false alarm on a finished painting
    row({ splice: .99 }, .99, {}),                                                       // reference-only type: never reported for ordinary passes
  ]);
  assert.deepEqual([report.types.flat_block[0.9].precision, report.types.flat_block[0.9].recall], [1, 1]);
  assert.deepEqual([report.types.splice[0.7].false_flags, report.types.ellipses[0.9].false_flags], [1, 1]);
  assert.deepEqual([report.blockin.precision, report.blockin.recall], [1, 1]);
  assert.deepEqual([report.undo.flagged, report.undo.precision, report.undo.recall], [2, 0.5, 1]);
  assert.deepEqual(report.wrong_undos.map(w => w.note), ['already in BEFORE']);
  assert.deepEqual([report.reported.flagged, report.reported.false_flags, report.reported.missed], [2, 1, 1]);
});
