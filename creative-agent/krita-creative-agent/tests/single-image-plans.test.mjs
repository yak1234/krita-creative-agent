// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Plans for a single goal image (openspec single-image-plans, approved by the artist 2026-10-25). Luna decides in the same
// reading whether a message asks for several steps or one thing (keywords as the fallback, a small card when unsure);
// the plan holds the stages the request names, a "Refine: <part>" step a part it names, and an "Add: <thing>" step a
// thing it adds that the goal image does not have, after the copy stages and before Accents.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readMessage } from '../src/message-reading.ts';
import { planOrNot, severalNamed, additionsNamed, refinePartsNamed, additionStep, folderPlanSteps, shapePlan, stepTool, PLAN_CARD, planFromCard, stagePolicy, orderStages } from '../src/plan-stages.ts';
import { folderStepKind } from '../src/project-folder.ts';

const DOSTOEVSKY = 'Paint this scene from the goal image: an underpainting, the finish, then refine it to the goal. Then add to it: falling snow over the whole scene, and fresh snow settled on the shoulders, hats, the posts and the rooftops';

function luna(answers) {
  const requests = [];
  return { requests, decide: async request => { requests.push(request); return { answers, model: 'luna', elapsed_ms: 500, usage: { input_tokens: 400, output_tokens: 9, cost: 0.0001 } }; } };
}
const choice = (choice, p = 0.92) => ({ type: 'choice', choice, confidence: p, probabilities: { [choice]: p } });
const noul = p => ({ type: 'noul', noul: p });
const base = { one_part: noul(0.1), negation: noul(0.1), reference: choice('neither'), hand_painting: noul(0.1) };
const reading = (answer, confidence) => ({ element: null, one_part: 0.1, negation: 0.1, reference: null, hand_painting: 0.1, stages: null, elapsed_ms: 1, cost: 0, input_tokens: 0,
  plan: answer ? { choice: answer, confidence } : null });

test('plan or not is one more question in the same single reading', async () => {
  const client = luna({ ...base, plan_steps: choice('several', 0.9) });
  const read = await readMessage({ client, text: DOSTOEVSKY, elements: [], stages: true, plan: true });
  assert.equal(client.requests.length, 1, 'one call');
  assert.ok('plan_steps' in client.requests[0].questions && 'plan_scope' in client.requests[0].questions);
  assert.deepEqual(Object.keys(client.requests[0].questions.plan_steps.criteria), ['one', 'several']);
  assert.deepEqual(read.plan, { choice: 'several', confidence: 0.9 });
  const plain = luna(base);
  assert.equal((await readMessage({ client: plain, text: 'Paint the sky.', elements: [] })).plan, null);
  assert.ok(!('plan_steps' in plain.requests[0].questions), 'not asked unless a single-image plan could be made');
});

test('keywords: several steps are two stages, a sequence word, a numbered list, a stage and an addition, or two additions', () => {
  assert.equal(severalNamed(DOSTOEVSKY), true);
  assert.equal(severalNamed('make the sky warmer'), null);
  assert.equal(severalNamed('add a little snow'), null, 'one addition is one thing');
  assert.equal(severalNamed('the underpainting and the finish'), true);
  assert.equal(severalNamed('Paint the sky, after that the river'), true);
  assert.equal(severalNamed('1. block in the city\n2. snow on the roofs'), true);
  assert.equal(severalNamed('refine the face'), null, 'one stage is one thing');
  assert.equal(severalNamed('add falling snow and settled snow on the roofs; also add a crow'), true);
});

test('keywords: the additions a message names, and the parts it asks to refine', () => {
  assert.deepEqual(additionsNamed(DOSTOEVSKY), ['falling snow over the whole scene', 'fresh snow settled on the shoulders, hats, the posts and the rooftops']);
  assert.deepEqual(additionsNamed('add a little snow'), ['a little snow']);
  assert.deepEqual(additionsNamed('Add a bird on the post.'), ['a bird on the post']);
  assert.deepEqual(additionsNamed('also add accents'), [], 'a stage is no addition');
  assert.deepEqual(additionsNamed("don't add snow"), []);
  assert.deepEqual(additionsNamed('make the sky warmer'), []);
  assert.deepEqual(refinePartsNamed(DOSTOEVSKY), [], '"refine it to the goal" names no part');
  assert.deepEqual(refinePartsNamed('Underpaint it, then refine the face and the soldiers.'), ['face', 'soldiers']);
});

test('the policy: Luna acting and sure decides, the keywords otherwise, the card when Luna is unsure and the keywords name nothing', () => {
  assert.deepEqual(planOrNot({ reading: reading('one', 0.9), act: true, text: 'make the sky warmer' }), { plan: false, source: 'luna' });
  assert.deepEqual(planOrNot({ reading: reading('several', 0.88), act: true, text: DOSTOEVSKY }), { plan: true, source: 'luna' });
  assert.deepEqual(planOrNot({ reading: reading('one', 0.95), act: true, text: 'add a little snow' }), { plan: false, source: 'luna' });
  assert.deepEqual(planOrNot({ reading: reading('several', 0.5), act: true, text: DOSTOEVSKY }), { plan: true, source: 'keywords' }, 'unsure Luna: the keywords');
  assert.deepEqual(planOrNot({ reading: reading('one', 0.5), act: true, text: 'make it nicer' }), { plan: null, source: 'ask' }, 'unsure and no keyword: the card');
  assert.deepEqual(planOrNot({ reading: null, act: false, text: 'make the sky warmer' }), { plan: false, source: 'default' }, 'Luna off: one thing, as before');
  assert.deepEqual(planOrNot({ reading: null, act: false, text: DOSTOEVSKY }), { plan: true, source: 'keywords' });
  assert.deepEqual(planOrNot({ reading: reading('several', 0.9), act: false, text: 'make the sky warmer' }), { plan: false, source: 'default' }, 'Luna not acting: the keywords');
});

test('the plan-or-not card recommends planning; its answers', () => {
  assert.deepEqual(PLAN_CARD.options, ['Plan it step by step', 'Just do it']);
  assert.equal(PLAN_CARD.recommended, 'Just do it', 'the card comes only when no step words were found: almost always one thing');
  assert.equal(planFromCard('Plan it step by step'), true);
  assert.equal(planFromCard(' Just do it '), false);
  assert.equal(planFromCard('paint the moon'), null);
});

test('an addition step: its kind, its place before Accents, a done_when that restates it, and any known tool', () => {
  const step = additionStep('falling snow over the whole scene');
  assert.equal(step.title, 'Add: falling snow over the whole scene');
  assert.equal(step.kind, 'addition');
  assert.equal(folderStepKind({ title: 'Add: a crow on the post' }), 'addition', 'by its title too');
  assert.match(step.done_when, /falling snow over the whole scene/);
  assert.match(step.done_when, /not a token/i);
  assert.equal(step.tool, undefined, 'the painter chooses with its normal tools');
  assert.deepEqual(stepTool({ kind: 'addition', tool: 'paint_snow' }, ['paint_snow', 'paint_batch']), { tool: 'paint_snow' }, 'a snow tool, when it exists');
  assert.deepEqual(stepTool({ kind: 'addition', tool: 'paint_snow' }, ['paint_batch']), { note: 'paint_snow is not a painting tool' });
  const stages = orderStages(stagePolicy({ reading: null, act: false, text: DOSTOEVSKY }).stages).stages;
  assert.deepEqual(stages, ['underpainting', 'finish', 'refine']);
  const steps = folderPlanSteps([...stages, 'accents'], [], { additions: additionsNamed(DOSTOEVSKY) });
  assert.deepEqual(steps.map(s => s.kind), ['underpainting', 'finish', 'refine', 'addition', 'addition', 'accents']);
});

test('a single-image plan: a part the request names is a Refine step for it; no part groups by default', () => {
  const steps = folderPlanSteps(['underpainting', 'finish', 'refine'], [{ label: 'face', parts: ['face'] }], { additions: [] });
  assert.deepEqual(steps.map(s => s.title), ['Underpainting from the goal image', 'Finish', 'Refine to the goal', 'Refine: face']);
  assert.deepEqual(steps[3].parts, ['face']);
});

test('shapePlan keeps every addition: a forgotten one comes back, a token done_when is restated, Accents stays last', () => {
  const draft = folderPlanSteps(['underpainting', 'accents'], [], { additions: ['falling snow over the whole scene', 'fresh snow settled on the shoulders, hats, the posts and the rooftops'] });
  const known = ['paint_from_reference', 'paint_accents', 'paint_batch'];
  const proposed = [{ title: 'Underpainting', done_when: 'Laid.' }, { title: 'Accents', done_when: 'Crisp.' },
    { title: 'Add: falling snow', done_when: 'Some snow.', kind: 'addition', tool: 'paint_batch' }];
  const shaped = shapePlan(proposed, { draft, elements: [], known, single: true });
  assert.deepEqual(shaped.steps.map(s => s.title), ['Underpainting', 'Add: falling snow', 'Add: fresh snow settled on the shoulders, hats, the posts and the rooftops', 'Accents']);
  assert.match(shaped.steps[1].done_when, /falling snow over the whole scene/, 'the planner’s token done_when restates the addition');
  assert.equal(shaped.steps[1].tool, 'paint_batch');
  assert.match(shaped.steps[2].done_when, /fresh snow settled on the shoulders/);
});

test('shapePlan on a single image keeps the planner’s Refine: <part> steps for the parts asked, with its words', () => {
  const draft = folderPlanSteps(['underpainting', 'finish', 'refine'], [{ label: 'face', parts: ['face'] }, { label: 'soldiers', parts: ['soldiers'] }]);
  const proposed = [{ title: 'Underpainting', done_when: 'Laid.' }, { title: 'Finish', done_when: 'Soft.' }, { title: 'Refine to the goal', done_when: 'Close.' },
    { title: 'Refine: the soldiers', done_when: 'Their buttons read.', kind: 'refine_part' }];
  const shaped = shapePlan(proposed, { draft, elements: [], known: ['paint_from_reference', 'paint_finish', 'refine_to_goal'], single: true });
  assert.deepEqual(shaped.steps.map(s => s.title), ['Underpainting', 'Finish', 'Refine to the goal', 'Refine: face', 'Refine: the soldiers'], 'the planner\u2019s words for the part it matched');
  assert.equal(shaped.steps[4].done_when, 'Their buttons read.');
  assert.deepEqual(shaped.steps.map(s => s.tool), ['paint_from_reference', 'paint_finish', 'refine_to_goal', 'refine_to_goal', 'refine_to_goal']);
});
