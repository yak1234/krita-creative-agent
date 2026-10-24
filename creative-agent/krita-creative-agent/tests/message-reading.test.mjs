// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Reading the artist's messages (luna-goal-reviewer goal 2): one Luna decision on each typed message, and the policy
// that turns its answers (or the keyword rules, when Luna is off, failed or not acting) into what the host does.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readMessage, messagePolicy, SURE } from '../src/message-reading.ts';

const elements = [{ name: 'assets/02-sky.png', guess: 'Moonlit sky' }, { name: 'assets/03-towers.png', guess: 'Kremlin towers' }, { name: 'assets/05-street-light.png', guess: 'Street light' }];
function luna(answers, usage = { input_tokens: 420, output_tokens: 8, cost: 0.00009 }) {
  const requests = [];
  return { requests, decide: async request => { requests.push(request); return typeof answers === 'function' ? answers(request) : { answers, model: 'luna', elapsed_ms: 640, usage }; } };
}
const choice = (choice, p = 0.92) => ({ type: 'choice', choice, confidence: p, probabilities: { [choice]: p } });
const noul = p => ({ type: 'noul', noul: p });

test('one text decision a message: which element, one part, a negation, the reference, hand painting', async () => {
  const client = luna({ element: choice('element_2'), one_part: noul(0.9), negation: noul(0.05), reference: choice('neither', 0.8), hand_painting: noul(0.1) });
  const reading = await readMessage({ client, text: 'Travaille sur les tours du Kremlin.', elements });
  const [request] = client.requests;
  assert.equal(request.purpose, 'read-message');
  assert.ok(request.parts.every(p => typeof p === 'string'), 'text only: no image');
  assert.ok(request.parts.some(p => p.includes('Travaille sur les tours du Kremlin.')));
  assert.deepEqual(Object.keys(request.questions), ['element', 'one_part', 'negation', 'reference', 'hand_painting']);
  assert.deepEqual(Object.keys(request.questions.element.criteria), ['none', 'element_1', 'element_2', 'element_3']);
  assert.match(request.questions.element.criteria.element_2, /Kremlin towers/);
  assert.match(request.questions.element.instructions, /any language/);
  assert.deepEqual(Object.keys(request.questions.reference.criteria), ['change', 'return', 'neither']);
  assert.deepEqual(reading.element, { name: 'assets/03-towers.png', confidence: 0.92 });
  assert.equal(reading.one_part, 0.9); assert.equal(reading.negation, 0.05); assert.equal(reading.hand_painting, 0.1);
  assert.deepEqual(reading.reference, { choice: 'neither', confidence: 0.8 });
  assert.deepEqual([reading.elapsed_ms, reading.cost, reading.input_tokens], [640, 0.00009, 420]);
  const plain = luna({ one_part: noul(0.2), negation: noul(0.1), reference: choice('neither'), hand_painting: noul(0.1) });
  const none = await readMessage({ client: plain, text: 'Paint the sky.', elements: [] });
  assert.ok(!('element' in plain.requests[0].questions), 'no element question without folder elements');
  assert.equal(none.element, null);
});

test('a fallback, a thrown error or an odd answer is no reading, never a guess', async () => {
  const timeout = await readMessage({ client: luna(() => ({ fallback: 'timeout', elapsed_ms: 4000 })), text: 'x', elements });
  assert.equal(timeout.fallback, 'timeout');
  const thrown = await readMessage({ client: { decide: async () => { throw new Error('x'); } }, text: 'x', elements });
  assert.equal(thrown.fallback, 'service_or_response_error');
  const odd = await readMessage({ client: luna({ element: choice('element_9'), one_part: noul(2), negation: noul(0.1), reference: choice('maybe'), hand_painting: noul(0.1) }), text: 'x', elements });
  assert.equal(odd.element, null, 'an element that is not listed'); assert.equal(odd.one_part, null); assert.equal(odd.reference, null);
});

const read = (over = {}) => ({ element: null, one_part: 0.1, negation: 0.1, reference: { choice: 'neither', confidence: 0.9 }, hand_painting: 0.1, elapsed_ms: 1, cost: 0, input_tokens: 0, ...over });
const policy = (reading, text, { act = true, planned = [] } = {}) => messagePolicy({ reading, act, text, elements, planned });

test('Luna acting (Guide) and sure: the named element is targeted, and added when it is not in the plan yet', () => {
  const towers = read({ element: { name: 'assets/03-towers.png', confidence: 0.92 }, one_part: 0.9 });
  assert.deepEqual(policy(towers, 'Arbeite an den Türmen des Kreml.'), { source: 'luna', target: 'assets/03-towers.png', add: ['assets/03-towers.png'], ask_add: [], part: false, departure: 'neither', hand_painting: false });
  assert.deepEqual(policy(towers, 'Work on the Kremlin towers.', { planned: ['assets/03-towers.png'] }).add, [], 'already in the plan: targeted only');
});

test('negations and general remarks add nothing: Luna says none, or is unsure', () => {
  for (const [text, reading] of [['Don’t paint the sky.', read({ element: { name: null, confidence: 0.9 }, negation: 0.95 })],
    ['Leave the towers alone.', read({ element: { name: null, confidence: 0.88 }, negation: 0.97 })],
    ['The light is too harsh.', read({ element: { name: null, confidence: 0.8 }, reference: { choice: 'change', confidence: 0.8 } })],
    ['Hmm, the towers?', read({ element: { name: 'assets/03-towers.png', confidence: SURE - 0.1 } })]]) {
    const p = policy(reading, text);
    assert.deepEqual([p.target, p.add, p.ask_add, p.part], [null, [], [], false], text);
  }
});

test('a part named that is no element (or with no folder): the painter is asked to ask for its area', () => {
  assert.equal(policy(read({ element: { name: null, confidence: 0.9 }, one_part: 0.9 }), 'Paint the river.').part, true);
  assert.equal(policy(read({ element: null, one_part: 0.85 }), 'Paint the sky.').part, true);
  assert.equal(policy(read({ element: null, one_part: 0.85, negation: 0.9 }), 'Don’t paint the sky.').part, false, 'not for a part to leave alone');
  assert.equal(policy(read({ element: null, one_part: 0.5 }), 'Paint the sky.').part, false, 'unsure');
});

test('the reference and hand painting: Luna’s sure answers; unsure ones are left to the keyword rules (null)', () => {
  assert.equal(policy(read({ reference: { choice: 'change', confidence: 0.9 } }), 'x').departure, 'departure');
  assert.equal(policy(read({ reference: { choice: 'return', confidence: 0.9 } }), 'x').departure, 'return');
  assert.equal(policy(read({ reference: { choice: 'change', confidence: 0.5 } }), 'x').departure, null);
  assert.equal(policy(read({ hand_painting: 0.9 }), 'x').hand_painting, true);
  assert.equal(policy(read({ hand_painting: 0.5 }), 'x').hand_painting, null);
});

test('Luna off or failed: the keyword rules, which target a planned element and ask before adding one; never a step added', () => {
  const off = policy(null, 'Refine the Kremlin towers.', { act: false });
  assert.deepEqual(off, { source: 'keywords', target: null, add: [], ask_add: ['assets/03-towers.png'], part: false, departure: null, hand_painting: null });
  assert.equal(policy(null, 'Now the towers.', { act: false, planned: ['assets/03-towers.png'] }).target, 'assets/03-towers.png');
  assert.deepEqual(policy(null, 'Don’t paint the sky, leave the towers alone.', { act: false }).ask_add, [], 'the keywords’ negation rule');
  const failed = policy(read({ fallback: 'timeout', element: null }), 'Refine the Kremlin towers.');
  assert.equal(failed.source, 'keywords'); assert.deepEqual(failed.add, []);
});

test('Evaluate (Luna not acting): the reference answer still counts, as the departure check always has; the rest is the keywords’', () => {
  const p = policy(read({ element: { name: 'assets/03-towers.png', confidence: 0.95 }, reference: { choice: 'change', confidence: 0.9 }, hand_painting: 0.95 }), 'Refine the Kremlin towers.', { act: false });
  assert.deepEqual(p, { source: 'keywords', target: null, add: [], ask_add: ['assets/03-towers.png'], part: false, departure: 'departure', hand_painting: null });
});
