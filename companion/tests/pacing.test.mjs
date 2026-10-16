import test from 'node:test';
import assert from 'node:assert/strict';
import { paceAction, stalled, parsePace, paceQuestions, levelledOff, foundMistakes, stepChecks, stepWork, handPaintedBy, callMethod, exhaustedMethods, STEP_DECISION_CAP, closeUpRegion, CLOSE_UP_SIDE } from '../src/pacing.mjs';

const steps = [
  { title: 'Construction', done_when: 'Guide lines.', checks: ['The car sits in the lower half', 'The driver\'s head is left of centre'] },
  { title: 'Block-in', done_when: 'Flat masses.', checks: ['Flat masses cover the car'] },
  { title: 'Light', done_when: 'Lit.' },
  { title: 'Detail', done_when: 'Details.' }];
const yes = p => ({ type: 'noul', noul: p });
const decide = (probabilities, finished = 0.1, mistakes = {}) => ({ answers: { ...Object.fromEntries(Object.entries(probabilities).map(([k, p]) => [k, yes(p)])),
  finished: yes(finished), ...Object.fromEntries(Object.entries(mistakes).map(([k, p]) => ['mistake_' + k, yes(p)])) } });
const run = { stepCount: 4, actionsSinceReview: 5 };

test('one request asks every visible check of the current and next steps, "finished?", and artifacts only after painting', () => {
  const q = paceQuestions({ steps, currentStep: 0 });
  assert.deepEqual(Object.keys(q), ['s0_c0', 's0_c1', 's1_c0', 's2_c0', 'finished']);
  assert.ok(Object.values(q).every(x => x.type === 'noul'), 'yes/no questions, which the decision model answers with a probability');
  assert.match(q.s2_c0.instructions, /Lit\./, 'a step without checks uses its done_when');
  assert.ok(Object.keys(paceQuestions({ steps, currentStep: 0, mistakes: true })).some(k => k.startsWith('mistake_')));
  assert.deepEqual(Object.keys(paceQuestions({ steps, currentStep: 3 })), ['s3_c0', 'finished'], 'nothing past the last step');
  assert.deepEqual(stepChecks({ checks: ['a', 'b', 'c', 'd', 'e', 'f'] }), ['a', 'b', 'c', 'd', 'e']);
});

test('the current step is the first one whose checks are not all visible', () => {
  const at = (probabilities, extra = {}) => paceAction(parsePace(decide(probabilities, extra.finished), { steps, currentStep: 0 }), { currentStep: 0, ...run, ...extra });
  const keep = at({ s0_c0: .9, s0_c1: .3, s1_c0: .1, s2_c0: .1 });
  assert.equal(keep.action, 'continue'); assert.deepEqual(keep.unmet, ["The driver's head is left of centre"]);
  assert.equal(keep.progress, 3 * (.9 + .3) / 2);
  const next = at({ s0_c0: .9, s0_c1: .8, s1_c0: .2, s2_c0: .1 });
  assert.equal(next.action, 'next_step'); assert.equal(next.step, 1); assert.ok(Math.abs(next.progress - 2.55) < 1e-9);
  assert.equal(at({ s0_c0: .9, s0_c1: .8, s1_c0: .9, s2_c0: .1 }).step, 2, 'a step the canvas already shows is skipped');
  assert.equal(at({ s0_c0: .2, s0_c1: .2, s1_c0: .2, s2_c0: .2 }, { finished: .8 }).action, 'request_review');
  assert.equal(at({ s0_c0: .2, s0_c1: .2, s1_c0: .2, s2_c0: .2 }, { finished: .8, actionsSinceReview: 2 }).action, 'continue', 'not before 3 actions');
  assert.equal(at({ s0_c0: .2, s0_c1: .2, s1_c0: .2, s2_c0: .2 }, { finished: .8, unchangedSinceReview: true }).action, 'continue', 'not an unchanged painting');
  const last = paceAction(parsePace(decide({ s3_c0: .9 }), { steps, currentStep: 3 }), { currentStep: 3, ...run });
  assert.equal(last.action, 'request_review', 'the last step shown leads to the review');
  assert.equal(paceAction({ fallback: 'timeout' }, {}).action, 'none');
});

test('artifacts count from the shipped threshold; malformed answers fall back', () => {
  const checks = { s0_c0: 1, s0_c1: 1, s1_c0: 0, s2_c0: 0 };
  const parsed = parsePace(decide(checks, 0, { stripes: .9, flat_block: .2, ellipses: 0, hard_graphic: 0, established: .99 }), { steps, currentStep: 0, mistakes: true });
  assert.deepEqual(foundMistakes(parsed).map(m => m.type), ['stripes']);
  const asked = Object.keys(paceQuestions({ steps, currentStep: 0, mistakes: true })).filter(k => k.startsWith('mistake_'));
  assert.deepEqual(asked, ['mistake_flat_block', 'mistake_stripes', 'mistake_ellipses', 'mistake_hard_graphic', 'mistake_established']);
  const severe = parsePace(decide(checks, 0, { stripes: 0, flat_block: .95, ellipses: 0, hard_graphic: 0, established: .99 }), { steps, currentStep: 0, mistakes: true });
  assert.deepEqual(foundMistakes(severe).map(m => [m.type, m.severe]), [['flat_block', true]]);
  const detail = parsePace(decide(checks, 0, { stripes: 0, flat_block: 0, ellipses: 0, hard_graphic: .95, established: .99 }), { steps, currentStep: 0, mistakes: true });
  assert.deepEqual(foundMistakes(detail).map(m => [m.type, !!m.severe]), [['hard_graphic', false]], 'crisp detail alone is reported, not undone: every labelled undo also had a flat block or ellipses');
  const early = parsePace(decide(checks, 0, { stripes: 0, flat_block: .95, ellipses: 0, hard_graphic: .9, established: .3 }), { steps, currentStep: 0, mistakes: true });
  assert.deepEqual(foundMistakes(early), [], 'a flat block-in is not damage');
  const broken = parsePace(decide(checks, 0, { stripes: .9 }), { steps, currentStep: 0, mistakes: true });
  assert.equal(broken.fallback, undefined, 'a malformed artifact answer keeps the pacing');
  assert.deepEqual(foundMistakes(broken), []);
  assert.equal(parsePace({ answers: { s0_c0: yes(1) } }, { steps, currentStep: 0 }).fallback, 'service_or_response_error');
  assert.equal(parsePace({ fallback: 'timeout' }, { steps, currentStep: 0 }).fallback, 'timeout');
});
test('a stall is two low-progress decisions in a row on the same step', () => {
  assert.equal(stalled([{ step: 0, progress: 0 }, { step: 0, progress: .5 }], 0), true);
  assert.equal(stalled([{ step: 0, progress: 0 }, { step: 1, progress: 0 }], 0), false);
  assert.equal(stalled([{ step: 0, progress: 0 }, { step: 0, progress: 2 }], 0), false);
});
test('a step levels off when Luna keeps going but its score stops rising, or after its share of decisions', () => {
  const run = scores => scores.map(progress => ({ step: 0, progress, action: 'continue' }));
  assert.equal(levelledOff(run([1.5, 1.28, 1.74, 1.56, 1.85, 1.66, 1.62, 1.75]), 0), 'plateau', 'the traced 2-hour step 1');
  assert.equal(levelledOff(run([1, 1.2, 1.4, 1.5, 1.8, 2, 2.2, 2.4]), 0), null, 'still improving');
  assert.equal(levelledOff(run([1.5, 1.6, 1.7]), 0), null, 'too few decisions to judge');
  assert.equal(levelledOff(run([0.5, 0.4]), 0), null, 'a low start gets the change-method note first');
  assert.equal(levelledOff(run([0.35, 0.34, 0.81, 0.7]), 0), 'stall', 'the traced 9-hour repair of one rectangle');
  assert.equal(levelledOff(run([0.35, 0.34, 0.81]), 0), null, 'a clear gain is not a stall');
  assert.equal(levelledOff(run([0.2, 0.5, 0.9, 1.2]), 0), null, 'still rising past 1');
  assert.equal(levelledOff([...run([1.5, 1.6, 1.5, 1.6, 1.5, 1.6, 1.5, 1.6]).map(h => ({ ...h, step: 1 })), ...run([1.5])], 0), null, 'other steps do not count');
  assert.equal(levelledOff(Array.from({ length: STEP_DECISION_CAP }, () => ({ step: 0, progress: null, action: 'none' })), 0), 'cap');
});

test('after a reference transfer, steps past the first count only with authored painting', () => {
  const all = { s0_c0: .9, s0_c1: .9, s1_c0: .9, s2_c0: .9, s3_c0: .1 };
  const at = (work, currentStep = 0) => paceAction(parsePace(decide(all), { steps, currentStep }), { currentStep, ...run, handPainted: handPaintedBy(work) });
  assert.equal(at(null).step, 3, 'no transfer: steps an existing painting shows are skipped');
  const transfer = stepWork(null, { tool: 'paint_from_reference', args: {} }, { revision: 1, step: 0 });
  assert.deepEqual(transfer, { revision: 1, transfer: true, authored: [] });
  assert.equal(at(transfer).step, 1, 'the traced run jumped from step 1 to step 5 on transfer dabs alone');
  const onStep1 = { ...at(transfer, 1) };
  assert.deepEqual([onStep1.action, onStep1.reason], ['continue', 'transfer_only']);
  const filtered = stepWork(transfer, { tool: 'paint_batch', args: { actions: [{ tool: 'apply_filter', arguments: { filter: 'gaussian blur' } }, { tool: 'adjust_layer', arguments: {} }] } }, { revision: 1, step: 1 });
  assert.deepEqual(filtered.authored, [], 'filters and layer settings are not authored painting');
  const painted = stepWork(filtered, { tool: 'paint_batch', args: { actions: [{ tool: 'paint_pass', arguments: {} }] } }, { revision: 1, step: 1 });
  assert.deepEqual(painted.authored, [1]);
  assert.equal(at(painted, 1).step, 2);
  assert.deepEqual(stepWork(painted, { tool: 'paint_pass' }, { revision: 2, step: 0 }), { revision: 2, transfer: false, authored: [0] }, 'a new plan starts fresh');
});

test('a transfer or filter that twice fails to raise the step is exhausted; authored work never is', () => {
  const blur = { tool: 'apply_filter', args: { filter: 'gaussian blur' } };
  assert.equal(callMethod(blur), 'smoothing filter');
  assert.equal(callMethod({ tool: 'apply_filter', args: { filter: 'waveletnoisereducer' } }), 'smoothing filter', 'noise reducers are the same hammer');
  assert.equal(callMethod({ tool: 'paint_batch', args: { actions: [{ tool: 'adjust_layer', arguments: {} }, { tool: 'apply_filter', arguments: { filter: 'gaussian blur' } }] } }), 'smoothing filter');
  assert.equal(callMethod({ tool: 'continue_reference_painting', args: {} }), 'reference painting');
  assert.equal(callMethod({ tool: 'paint_reference_surface', args: {} }), 'reference painting', 'a surface pass on the same rectangle is not a new method');
  assert.equal(callMethod({ tool: 'paint_pass', args: {} }), null);
  assert.equal(callMethod({ tool: 'paint_batch', args: { actions: [{ tool: 'apply_filter', arguments: { filter: 'blur' } }, { tool: 'paint_pass', arguments: {} }] } }), null, 'mixed work');
  // The traced blur loop on step 5: 0.63, then noise reducer 0.75, wavelet 0.6, blur 0.9, blur 0.84.
  const history = [{ step: 4, progress: .63, method: 'smoothing filter' }, { step: 4, progress: .75, method: 'smoothing filter' }, { step: 4, progress: .6, method: 'smoothing filter' }];
  assert.deepEqual(exhaustedMethods(history.slice(0, 2), 4), []);
  assert.deepEqual(exhaustedMethods(history, 4), ['smoothing filter']);
  assert.deepEqual(exhaustedMethods(history, 5), [], 'a new step starts fresh');
  assert.deepEqual(exhaustedMethods([{ step: 0, progress: 1 }, { step: 0, progress: 1.1, method: 'reference transfer' }, { step: 0, progress: 1.8, method: 'reference transfer' }, { step: 0, progress: 1.7, method: 'reference transfer' }], 0), [], 'misses must be in a row');
  assert.deepEqual(exhaustedMethods([{ step: 0, progress: 1 }, { step: 0, progress: 1 }, { step: 0, progress: 1 }], 0), [], 'authored work has no method');
});

test('a close-up asks texture questions of actual pixels where the call painted', () => {
  assert.match(paceQuestions({ steps, currentStep: 0, closeUp: true }).s0_c0.instructions, /CLOSE-UP \(actual pixels\)/);
  assert.doesNotMatch(paceQuestions({ steps, currentStep: 0 }).s0_c0.instructions, /CLOSE-UP/);
  const canvas = { width: 6000, height: 4500 };
  assert.deepEqual(closeUpRegion([[2900, 2200, 200, 100]], canvas), [2616, 1866, 768, 768], 'a small area gets some surroundings');
  assert.deepEqual(closeUpRegion([[600, 60, 5000, 1740]], canvas), [2316, 146, CLOSE_UP_SIDE, CLOSE_UP_SIDE], 'a huge area: its centre at actual pixels');
  assert.deepEqual(closeUpRegion([[5900, 4400, 100, 100]], canvas), [5232, 3732, 768, 768], 'kept inside the canvas');
  assert.deepEqual(closeUpRegion([[100, 100, 50, 50], [900, 300, 50, 50]], canvas), [100, 0, 850, 768], 'the union of the painted areas');
  assert.equal(closeUpRegion([[0, 0, 10, 10]], { width: 768, height: 1024 }), null, 'the whole view already shows actual pixels');
  assert.equal(closeUpRegion([null, undefined, [1, 2]], canvas), null, 'nothing says where it painted');
});
