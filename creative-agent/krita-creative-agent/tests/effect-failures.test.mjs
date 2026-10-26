// When a build starts (openspec custom-effects, failures.ts): the same effect failing twice in a chat, by Luna's "effect met"
// decision or a redo; never on an Undo alone, never for an effect the library covers, never after Discard, one at a time.
// No files are written.
import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { EffectFailures, classifyEffect, effectAsked, effectMet, libraryEffectFor, redoOf, sameEffect, tokenEffort } from '../src/effects/failures.ts';
import { DEFAULT_POLICY, readPolicy } from '../src/effects/policy.ts';
import { loadEffects } from '../src/effects/library.ts';
import { EFFECTS_DIR } from '../src/tools.mjs';

const policy = readPolicy(join(EFFECTS_DIR, 'policy.yaml'));
const IMAGE = { type: 'image', data: 'iVBORw0KGgo=', mimeType: 'image/png' };

test('a request names an effect by its words', () => {
  assert.equal(effectAsked('Add thick fog over the river'), 'fog');
  assert.equal(effectAsked('a misty morning, please'), 'fog');
  assert.equal(effectAsked('Make it rain on the square'), 'rain');
  assert.equal(effectAsked('god rays through the window'), 'light rays');
  assert.equal(effectAsked('smoke from the chimneys, then snow'), 'smoke', 'the first named');
  assert.equal(effectAsked('Paint the castle walls redder'), null);
  assert.equal(effectAsked('the snowman by the door'), null, 'whole words only');
  assert.ok(sameEffect('mist', 'fog'));
  assert.ok(sameEffect('snowfall', 'snow'));
  assert.ok(!sameEffect('rain', 'snow'));
  assert.ok(sameEffect('aurora borealis', 'aurora'));
});

test('things that are not effects are not effects', () => {
  for (const text of ['paint the rose petals pinker', 'make the fire station door redder', 'stars on the flag', 'a dust jacket on the book',
    'rain boots by the door', 'a snow globe on the shelf', 'the fire escape on the left', 'paint the steam engine black'])
    assert.equal(effectAsked(text), null, text);
  assert.equal(effectAsked('falling petals over the garden'), 'falling petals', 'the effect, as a phrase');
  assert.equal(effectAsked('a starry sky above the towers'), 'starry sky');
  assert.equal(effectAsked('light shafts through the trees'), 'light rays');
  assert.equal(effectAsked('embers rising from the fire'), 'sparks');
  assert.equal(effectAsked('a fire in the hearth'), 'fire', 'fire, not a fire station');
});

test('a kept effect is recognised by its name and cue words', () => {
  const library = [{ name: 'aurora-curtain', cue: 'green aurora curtains, northern lights' }, { name: 'glow-worms', cue: 'glow worms; tiny glowing lights' }];
  assert.equal(effectAsked('add glow worms in the meadow', library), 'glow-worms');
  assert.equal(effectAsked('tiny glowing lights in the grass', library), 'glow-worms');
  assert.equal(effectAsked('northern lights over the hills', library), 'aurora-curtain', 'the library effect before the built-in aurora');
  assert.equal(effectAsked('add glow worms in the meadow'), null, 'without the library: not a known effect');
});

test('a token effort counts as a failure, a substantial move does not', () => {
  assert.equal(policy.token_effort, 40);
  assert.equal(tokenEffort({ strokes: 12 }, policy), true, 'the live snow move: 12 strokes, called done');
  assert.equal(tokenEffort({ strokes: 120 }, policy), false, 'many strokes');
  assert.equal(tokenEffort({ strokes: 0, unstroked: 1 }, policy), false, 'a fill');
  assert.equal(tokenEffort({ strokes: 3, effect_calls: 1, effect_painted: 14000 }, policy), false, 'paint_snow painted thousands of flakes');
  assert.equal(tokenEffort({ effect_calls: 1, effect_painted: 0 }, policy), true, 'an effect tool that painted nothing');
  assert.equal(tokenEffort({ strokes: 12 }, { ...policy, token_effort: 0 }), false, '0: off');
});

test('the same effect twice is due, once is not', () => {
  assert.equal(policy.failures_before_build, 2);
  const log = new EffectFailures();
  log.record('rain', true, 'move-1');
  assert.equal(log.due('rain', policy), false, 'once is not');
  log.record('rain', false, 'move-2');
  assert.equal(log.due('rain', policy), false, 'a met move is no failure');
  log.record('drizzle', true, 'move-3');
  assert.equal(log.due('rain', policy), true, 'twice, by its words, is');
  assert.equal(log.due('smoke', policy), false, 'another effect is not');
  log.record('rain', true, 'move-3');
  assert.equal(log.failures('rain'), 2, 'one place counts once');
});

test('a redo of an effect called done counts as a failure', () => {
  const finished = { number: 4, finished: true, effect: 'rain' };
  assert.deepEqual(redoOf(effectAsked('More rain, it is barely there'), finished, true), { effect: 'rain', at: 'move-4' });
  assert.deepEqual(redoOf('rain', { number: 2, finished: true, summary: 'Rain: slanted streaks over the street' }, true),
    { effect: 'rain', at: 'move-2' }, 'the painter named it in its summary');
  // Luna judged move 4 met; the artist asking again makes it a failure (one place, counted once).
  const log = new EffectFailures();
  log.record('rain', false, 'move-4');
  const redo = redoOf('rain', finished, true);
  log.record(redo.effect, true, redo.at);
  assert.equal(log.failures('rain'), 1);
  assert.equal(redoOf('rain', { ...finished, finished: false }, true), null, 'a move the painter did not finish is no redo');
  assert.equal(redoOf('fog', finished, true), null, 'another effect is no redo');
  assert.equal(redoOf(null, finished, true), null);
});

test('an Undo alone does not count', () => {
  const finished = { number: 4, finished: true, effect: 'rain' };
  // The Undo button's retry repaints the same request, but it is not the artist's typed message.
  assert.equal(redoOf('rain', finished, false), null);
  const log = new EffectFailures();
  log.record('rain', true, 'move-4');
  assert.equal(log.due('rain', policy), false);
});

test('a library effect whose cue matches is used, not built', async () => {
  const { effects } = await loadEffects({ bundled: EFFECTS_DIR, own: '' });
  assert.equal(libraryEffectFor('mist', effects.values()), 'fog', 'fog\'s cue names mist');
  assert.equal(libraryEffectFor('snow', effects.values()), 'snow');
  assert.equal(libraryEffectFor('blizzard', effects.values()), 'snow');
  assert.equal(libraryEffectFor('rain', effects.values()), null, 'rain is not in the library: it may be built');
  assert.equal(libraryEffectFor('aurora', [{ name: 'aurora', cue: 'northern lights over the sky' }]), 'aurora', 'by name');
});

test('after Discard the effect is not built again unless /new-effect', () => {
  const log = new EffectFailures();
  log.record('rain', true, 'move-1'); log.record('rain', true, 'move-2');
  assert.equal(log.due('rain', policy), true);
  log.discarded('rain');
  assert.equal(log.due('rain', policy), false);
  log.record('drizzle', true, 'move-3');
  assert.equal(log.due('rain', policy), false, 'more failures do not bring it back');
  assert.ok(log.isDiscarded('downpour'), 'by its words');
  log.record('smoke', true, 'move-4'); log.record('smoke', true, 'move-5');
  assert.equal(log.due('smoke', policy), true, 'another effect still builds');
});

test('one build at a time', () => {
  const log = new EffectFailures();
  for (const at of ['move-1', 'move-2']) { log.record('rain', true, at); log.record('smoke', true, at); }
  assert.equal(log.due('rain', policy), true);
  log.building = 'rain';
  assert.equal(log.due('rain', policy), false, 'not the same one twice');
  assert.equal(log.due('smoke', policy), false, 'nor another while it builds');
  log.building = null;
  assert.equal(log.due('smoke', policy), true);
  log.launched('smoke');
  assert.equal(log.building, 'smoke');
  assert.equal(log.failures('smoke'), 0, 'a build uses up the failures that started it');
  log.building = null;
  log.record('smoke', true, 'move-3');
  assert.equal(log.due('smoke', policy), false, 'one new failure is not enough');
  log.record('smoke', true, 'move-2');
  assert.equal(log.due('smoke', policy), false, 'nor an old place judged again');
  log.record('smoke', true, 'move-4');
  assert.equal(log.due('smoke', policy), true, 'two new failures are');
  assert.equal(log.due('rain', { ...DEFAULT_POLICY, failures_before_build: 3 }), false, 'the policy sets how many');
});

test('a Luna failure is not a failure', async () => {
  const asked = [];
  const answering = noul => ({ async decide(request) { asked.push(request); return { answers: { met: { type: 'noul', noul } }, model: 'm', elapsed_ms: 1, usage: { input_tokens: 1, output_tokens: 1, cost: 0 } }; } });
  assert.equal(await effectMet({ client: answering(0.9), request: 'add rain', before: IMAGE, after: IMAGE }), true);
  assert.equal(await effectMet({ client: answering(0.1), request: 'add rain', before: IMAGE, after: IMAGE }), false);
  const [first] = asked;
  assert.equal(first.purpose, 'effect-met');
  assert.equal(Object.keys(first.questions).length, 1, 'one question');
  assert.equal(first.questions.met.type, 'noul');
  assert.match(first.questions.met.instructions, /token effort/);
  assert.ok(first.parts.some(p => typeof p === 'string' && p.includes('"add rain"')), 'the request, quoted');
  assert.equal(first.parts.filter(p => p === IMAGE).length, 2, 'before and after');
  for (const client of [null, { decide: async () => ({ fallback: 'timeout', elapsed_ms: 4000 }) }, { decide: async () => { throw new Error('offline'); } },
    { decide: async () => ({ answers: { met: { type: 'refusal' } }, model: 'm', elapsed_ms: 1, usage: { input_tokens: 0, output_tokens: 0, cost: 0 } }) }])
    assert.equal(await effectMet({ client, request: 'add rain', before: IMAGE, after: IMAGE }), null);
  assert.equal(await effectMet({ client: answering(0.1), request: 'add rain', before: null, after: IMAGE }), null, 'no before view: no judgement');
  const log = new EffectFailures();
  for (const at of ['move-1', 'move-2']) { const met = await effectMet({ client: null, request: 'add rain', before: IMAGE, after: IMAGE }); if (met !== null) log.record('rain', !met, at); }
  assert.equal(log.failures('rain'), 0);
});

test('with Decision checks on, Luna reads which effect a request asks for; unsure or failing falls back to the words', async () => {
  const asked = [];
  const choosing = (choice, confidence = 0.9) => ({ async decide(request) { asked.push(request);
    const keys = Object.keys(request.questions.effect.criteria);
    const key = choice === 'none' ? 'none' : keys.find(k => request.questions.effect.criteria[k] === `The effect: ${choice}.`);
    return { answers: { effect: { type: 'choice', choice: key, confidence } }, model: 'm', elapsed_ms: 1, usage: { input_tokens: 1, output_tokens: 1, cost: 0 } }; } });
  const library = [{ name: 'glow-worms', cue: 'glow worms' }];
  assert.deepEqual(await classifyEffect({ client: choosing('rain'), text: 'make it pour', library }), { effect: 'rain' });
  assert.deepEqual(await classifyEffect({ client: choosing('glow-worms'), text: 'little lights in the grass', library }), { effect: 'glow-worms' }, 'a kept effect is a choice');
  assert.deepEqual(await classifyEffect({ client: choosing('none'), text: 'paint the fire station door redder', library }), { effect: null });
  assert.equal(asked[0].purpose, 'effect-asked'); assert.equal(Object.keys(asked[0].questions).length, 1, 'one question');
  assert.equal(asked[0].questions.effect.type, 'choice');
  assert.equal(await classifyEffect({ client: choosing('rain', 0.3), text: 'make it pour', library }), null, 'unsure: the words decide');
  assert.equal(await classifyEffect({ client: { decide: async () => ({ fallback: 'timeout', elapsed_ms: 1 }) }, text: 'rain', library }), null);
  assert.equal(await classifyEffect({ client: { decide: async () => { throw new Error('offline'); } }, text: 'rain', library }), null);
  assert.equal(await classifyEffect({ client: null, text: 'rain', library }), null);
});
