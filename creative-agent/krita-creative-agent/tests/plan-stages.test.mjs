// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The plan follows the request (openspec plan-from-request goals 1-3, approved by the artist 2026-10-24): which stages a
// folder plan holds comes from the artist's message (Luna's reading in the same call, keywords as the fallback, the plan
// card when unsure), the host keeps the order rules, the full plan has a refine step per group of elements, and each step
// records the tool it uses, checked by the host.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readMessage } from '../src/message-reading.ts';
import { reviseStages, stagesNamed, stagePolicy, orderStages, folderPlanSteps, shapePlan, stepTool, STAGE_CARD, stagesFromCard, nextStages } from '../src/plan-stages.ts';
import { refineGroups, partsOf, unionFound } from '../src/refine-parts.ts';
import { folderStepKind, defaultFolderSteps } from '../src/project-folder.ts';
import { encodePlane, decodePlane } from '../src/shapes/png.ts';

function luna(answers) {
  const requests = [];
  return { requests, decide: async request => { requests.push(request); return { answers, model: 'luna', elapsed_ms: 500, usage: { input_tokens: 400, output_tokens: 9, cost: 0.0001 } }; } };
}
const choice = (choice, p = 0.92) => ({ type: 'choice', choice, confidence: p, probabilities: { [choice]: p } });
const noul = p => ({ type: 'noul', noul: p });
const base = { one_part: noul(0.1), negation: noul(0.1), reference: choice('neither'), hand_painting: noul(0.1) };

test('a folder plan being made: the same single reading also answers the stages', async () => {
  const client = luna({ ...base, plan_scope: choice('stages', 0.9), stage_underpainting: noul(0.95), stage_finish: noul(0.1), stage_refine: noul(0.05), stage_accents: noul(0.2) });
  const reading = await readMessage({ client, text: 'Peins juste la sous-couche.', elements: [], stages: true });
  assert.equal(client.requests.length, 1, 'one call');
  assert.deepEqual(Object.keys(client.requests[0].questions), ['one_part', 'negation', 'reference', 'hand_painting', 'plan_scope', 'stage_underpainting', 'stage_finish', 'stage_refine', 'stage_accents']);
  assert.deepEqual(Object.keys(client.requests[0].questions.plan_scope.criteria), ['whole', 'stages', 'neither']);
  assert.deepEqual(reading.stages, { scope: { choice: 'stages', confidence: 0.9 }, asked: { underpainting: 0.95, finish: 0.1, refine: 0.05, accents: 0.2 } });
  const plain = luna(base);
  const without = await readMessage({ client: plain, text: 'Paint the sky.', elements: [] });
  assert.ok(!('plan_scope' in plain.requests[0].questions), 'no stage questions outside a folder plan');
  assert.equal(without.stages, null);
});

test('keywords: the stages a message names, the whole painting, negated clauses ignored', () => {
  assert.deepEqual(stagesNamed('paint the underpainting'), { stages: ['underpainting'], whole: false, removed: [] });
  assert.deepEqual(stagesNamed('Paint the underpainting and the finish, please.'), { stages: ['underpainting', 'finish'], whole: false, removed: [] });
  assert.deepEqual(stagesNamed('paint it like the goal'), { stages: [], whole: true, removed: [] });
  assert.deepEqual(stagesNamed('Paint the whole thing.'), { stages: [], whole: true, removed: [] });
  assert.deepEqual(stagesNamed('Block-in first, then accents'), { stages: ['underpainting', 'accents'], whole: false, removed: [] });
  assert.deepEqual(stagesNamed('underpainting and finish, but no accents'), { stages: ['underpainting', 'finish'], whole: false, removed: ['accents'] });
  assert.deepEqual(stagesNamed("Don't refine anything yet; just the underpainting."), { stages: ['underpainting'], whole: false, removed: ['refine'] });
  assert.deepEqual(stagesNamed('Paint this folder.'), { stages: [], whole: false, removed: [] });
  assert.deepEqual(stagesNamed('refine it to the goal'), { stages: ['refine'], whole: false, removed: [] }, '"to the goal" is not "like the goal"');
  assert.deepEqual(stagesNamed('paint everything from start to finish'), { stages: [], whole: true, removed: [] }, '"to finish" in a phrase is not the finish');
});

const reading = (scope, asked = {}) => ({ element: null, one_part: 0.1, negation: 0.1, reference: null, hand_painting: 0.1, elapsed_ms: 1, cost: 0, input_tokens: 0,
  stages: { scope: scope && { choice: scope[0], confidence: scope[1] }, asked: { underpainting: null, finish: null, refine: null, accents: null, ...asked } } });

test('the policy: Luna acting and sure decides, the keywords otherwise, the card when Luna is unsure and the keywords name nothing', () => {
  assert.deepEqual(stagePolicy({ reading: reading(['whole', 0.9]), act: true, text: 'Mach alles wie das Ziel.' }), { stages: ['underpainting', 'finish', 'refine', 'accents'], whole: true, source: 'luna' });
  assert.deepEqual(stagePolicy({ reading: reading(['stages', 0.85], { underpainting: 0.93, finish: 0.2 }), act: true, text: 'Nur die Untermalung.' }), { stages: ['underpainting'], whole: false, source: 'luna' });
  assert.deepEqual(stagePolicy({ reading: reading(['stages', 0.5]), act: true, text: 'paint the underpainting' }), { stages: ['underpainting'], whole: false, source: 'keywords' }, 'unsure Luna: the keywords');
  assert.deepEqual(stagePolicy({ reading: reading(['stages', 0.5]), act: true, text: 'Faites ce que vous pensez.' }), { stages: null, whole: false, source: 'ask' }, 'unsure and no keyword: the card asks');
  assert.deepEqual(stagePolicy({ reading: reading(['neither', 0.9]), act: true, text: 'Paint this folder.' }), { stages: ['underpainting', 'finish', 'refine', 'accents'], whole: true, source: 'default' }, 'no stage named: the full plan, as before');
  assert.deepEqual(stagePolicy({ reading: null, act: false, text: 'paint it like the goal' }), { stages: ['underpainting', 'finish', 'refine', 'accents'], whole: true, source: 'keywords' });
  assert.deepEqual(stagePolicy({ reading: null, act: false, text: 'Paint it.' }), { stages: ['underpainting', 'finish', 'refine', 'accents'], whole: true, source: 'default' }, 'Luna off: never the card');
  assert.deepEqual(stagePolicy({ reading: reading(['stages', 0.9], { finish: 0.9 }), act: false, text: 'the underpainting only' }).stages, ['underpainting'], 'Luna not acting (Evaluate): the keywords decide');
  assert.deepEqual(stagePolicy({ reading: { ...reading(['whole', 0.9]), fallback: 'timeout' }, act: true, text: 'Paint it.' }).source, 'default', 'a failed reading is no reading');
});

test('the plan card: its options give the stages', () => {
  assert.deepEqual(STAGE_CARD.options, ['The underpainting only', 'Underpainting and finish', 'The whole plan']);
  assert.deepEqual(stagesFromCard('The underpainting only'), ['underpainting']);
  assert.deepEqual(stagesFromCard('Underpainting and finish'), ['underpainting', 'finish']);
  assert.deepEqual(stagesFromCard('The whole plan'), ['underpainting', 'finish', 'refine', 'accents']);
  assert.equal(stagesFromCard('something typed'), null);
});

test('the order rules: an underpainting first, Refine only after a whole-picture Finish, Accents last', () => {
  assert.deepEqual(orderStages(['accents', 'underpainting']), { stages: ['underpainting', 'accents'], added: [] });
  const refine = orderStages(['refine']);
  assert.deepEqual(refine.stages, ['underpainting', 'finish', 'refine']);
  assert.deepEqual(refine.added.map(a => a.stage), ['underpainting', 'finish']);
  assert.match(refine.added.find(a => a.stage === 'finish').because, /Refine/);
  assert.deepEqual(orderStages(['finish'], { done: ['underpainting'] }), { stages: ['finish'], added: [] }, 'an underpainting already painted');
  assert.deepEqual(orderStages(['refine'], { done: ['underpainting', 'finish'] }).stages, ['refine']);
  assert.deepEqual(orderStages([]).stages, []);
});

const twelve = ['01-moonlit-sky', '02-historic-buildings', '03-domed-church', '04-kremlin-towers', '05-modern-skyline', '06-arched-bridge',
  '07-river-reflections', '08-snowy-street', '09-lamps-and-trees', '10-snowy-railing', '11-woman-back-view', '12-vintage-convertible']
  .map(stem => ({ name: `assets/${stem}.png`, guess: stem.slice(3).replace(/-/g, ' ').replace(/^./, c => c.toUpperCase()) }));

test('refine groups: the folder’s elements in their order, 4-7 groups (fewer elements, one each)', () => {
  const groups = refineGroups(twelve);
  assert.equal(groups.length, 6);
  assert.deepEqual(groups.map(g => g.parts.length), [2, 2, 2, 2, 2, 2]);
  assert.equal(groups[0].label, 'Moonlit sky and historic buildings');
  assert.deepEqual(groups[0].parts, ['assets/01-moonlit-sky.png', 'assets/02-historic-buildings.png']);
  assert.equal(refineGroups(twelve.slice(0, 3)).length, 3, 'three elements: one group each');
  assert.equal(refineGroups(twelve.slice(0, 5)).length, 4);
  assert.deepEqual(refineGroups(twelve.slice(0, 5)).map(g => g.parts.length), [2, 1, 1, 1]);
  const fifteen = [...twelve, ...twelve.slice(0, 3).map(e => ({ name: e.name.replace('assets/', 'more/'), guess: e.guess + ' 2' }))];
  assert.equal(refineGroups(fifteen).length, 7);
  assert.deepEqual(refineGroups([]), []);
  assert.equal(refineGroups([{ name: 'a.png', guess: 'A' }, { name: 'b.png', guess: 'B' }, { name: 'c.png', guess: 'C' }, { name: 'd.png', guess: 'D' }, { name: 'e.png', guess: 'E' }, { name: 'f.png', guess: 'F' }, { name: 'g.png', guess: 'G' }])
    .map(g => g.label).join(' | '), 'A and b | C and d | E and f | G', 'seven: four groups');
});

// The artist, 2026-10-25 (approved): six part steps each refining its area fully took 45-60 minutes on New Moscow. The
// refine stage is one whole-picture "Refine to the goal", then a short touch-up step per group of parts.
test('the steps: one per stage asked; the refine stage is one whole-picture refine, then a touch-up step per group', () => {
  const groups = refineGroups(twelve);
  const full = folderPlanSteps(['underpainting', 'finish', 'refine', 'accents'], groups);
  assert.deepEqual(full.map(s => s.title), ['Underpainting from the goal image', 'Finish', 'Refine to the goal', ...groups.map(g => 'Refine: ' + g.label), 'Accents']);
  assert.deepEqual(full.map(s => s.kind), ['underpainting', 'finish', 'refine', ...groups.map(() => 'refine_part'), 'accents']);
  assert.deepEqual(full.map(s => s.tool), ['paint_from_reference', 'paint_finish', 'refine_to_goal', ...groups.map(() => 'refine_to_goal'), 'paint_accents']);
  assert.deepEqual(full[3].parts, groups[0].parts);
  assert.match(full[3].done_when, /touch-up|still/i, 'a part step says it is a touch-up after the whole-picture refine');
  assert.deepEqual(full.map(folderStepKind), full.map(s => s.kind));
  const one = folderPlanSteps(['underpainting'], groups);
  assert.deepEqual(one.map(s => s.title), ['Underpainting from the goal image']);
  const noElements = folderPlanSteps(['underpainting', 'finish', 'refine', 'accents'], []);
  assert.deepEqual(noElements.map(s => [s.title, s.kind]), [['Underpainting from the goal image', 'underpainting'], ['Finish', 'finish'], ['Refine to the goal', 'refine'], ['Accents', 'accents']], 'no elements: one whole-picture refine');
  assert.equal(defaultFolderSteps().length, 4, 'the old default stays for callers that want it');
});

test('folderStepKind: the step’s kind first; "Refine: <part>" titles; old PLAN.md titles keep their kinds', () => {
  assert.equal(folderStepKind({ title: 'Clean the towers', kind: 'refine_part' }), 'refine_part');
  assert.equal(folderStepKind({ title: 'Accents', kind: 'nonsense' }), 'accents', 'an unknown kind: the title decides');
  assert.equal(folderStepKind({ title: 'Refine: sky and moon', scope: 'sky and moon' }), 'refine_part');
  assert.equal(folderStepKind({ title: 'refine : the bridge' }), 'refine_part');
  assert.equal(folderStepKind({ title: 'Refine to the goal', scope: 'whole composition' }), 'refine');
  assert.equal(folderStepKind({ title: 'Refine the sky', scope: 'whole composition' }), 'whole');
  assert.equal(folderStepKind({ title: 'Underpainting from the goal image', scope: 'whole composition' }), 'underpainting');
  assert.equal(folderStepKind({ title: 'Kremlin towers', scope: 'assets/04-kremlin-towers.png', kind: 'element' }), 'element');
});

test('a step’s tool: kept when it exists and fits the kind, else the kind’s own tool', () => {
  const known = ['paint_from_reference', 'paint_finish', 'refine_to_goal', 'paint_accents', 'paint_batch', 'fill_region'];
  assert.deepEqual(stepTool({ kind: 'finish', tool: 'paint_finish' }, known), { tool: 'paint_finish' });
  assert.deepEqual(stepTool({ kind: 'finish', tool: 'paint_accents' }, known), { tool: 'paint_finish', note: 'paint_accents does not do a finish step: paint_finish' });
  assert.deepEqual(stepTool({ kind: 'refine_part', tool: 'nonexistent_tool' }, known), { tool: 'refine_to_goal', note: 'nonexistent_tool is not a painting tool: refine_to_goal' });
  assert.deepEqual(stepTool({ kind: 'underpainting' }, known), { tool: 'paint_from_reference' });
  assert.deepEqual(stepTool({ kind: 'whole', tool: 'fill_region' }, known), { tool: 'fill_region' }, 'a whole-picture step of the artist’s: any painting tool');
  assert.deepEqual(stepTool({ kind: 'whole', tool: 'make_coffee' }, known), { note: 'make_coffee is not a painting tool' });
});

test('the planner’s proposal is shaped by the host: the stages asked, in order, its words kept, its groups when valid', () => {
  const groups = refineGroups(twelve), known = ['paint_from_reference', 'paint_finish', 'refine_to_goal', 'paint_accents'];
  const draft = folderPlanSteps(['underpainting'], groups);
  // The planner proposed the whole plan for "paint the underpainting": the host keeps the underpainting only, with its words.
  const proposed = [{ title: 'Underpainting of New Moscow', done_when: 'The night city is laid in from the goal.', checks: ['The sky is blue.'], kind: 'underpainting', tool: 'paint_from_reference' },
    { title: 'Finish', done_when: 'Blended.', tool: 'paint_finish' }, { title: 'Accents', done_when: 'Crisp.' }];
  const one = shapePlan(proposed, { draft, elements: twelve, known });
  assert.deepEqual(one.steps.map(s => [s.title, s.kind, s.tool]), [['Underpainting of New Moscow', 'underpainting', 'paint_from_reference']]);
  assert.equal(one.steps[0].done_when, 'The night city is laid in from the goal.');
  assert.deepEqual(one.steps[0].checks, ['The sky is blue.']);
  assert.deepEqual(one.dropped, ['Finish', 'Accents']);
  // The full plan: the planner regroups the parts (valid: every element once, 4-7 groups) and picks a wrong tool for one.
  const fullDraft = folderPlanSteps(['underpainting', 'finish', 'refine', 'accents'], groups);
  const regrouped = [[0], [1, 2], [3], [4], [5, 6], [7, 8, 9, 10, 11]].map(ix => ix.map(i => twelve[i].name));
  const fullProposal = [{ title: 'Underpainting', done_when: 'Laid in.', kind: 'underpainting', tool: 'paint_from_reference' },
    { title: 'Finish', done_when: 'Blended.', kind: 'finish', tool: 'paint_finish' },
    ...regrouped.map((parts, i) => ({ title: `Refine: group ${i + 1}`, done_when: `Group ${i + 1} close to the goal.`, kind: 'refine_part', tool: i === 0 ? 'paint_accents' : 'refine_to_goal', parts })),
    { title: 'Accents', done_when: 'Crisp.', kind: 'accents', tool: 'paint_accents' }];
  const full = shapePlan(fullProposal, { draft: fullDraft, elements: twelve, known });
  assert.deepEqual(full.steps.map(s => s.kind), ['underpainting', 'finish', 'refine', 'refine_part', 'refine_part', 'refine_part', 'refine_part', 'refine_part', 'refine_part', 'accents'],
    'the whole-picture refine stays although the planner left it out');
  assert.deepEqual(full.steps.filter(s => s.kind === 'refine_part').map(s => s.parts), regrouped, 'the planner’s groups');
  assert.equal(full.steps[3].tool, 'refine_to_goal');
  // The planner's words for the whole-picture refine are kept when it proposes one.
  const worded = shapePlan([...fullProposal.slice(0, 2), { title: 'Refine to the goal', done_when: 'Every building crisp.', kind: 'refine', tool: 'refine_to_goal' }, ...fullProposal.slice(2)],
    { draft: fullDraft, elements: twelve, known });
  assert.deepEqual(worded.steps.filter(s => s.kind === 'refine').map(s => [s.title, s.done_when]), [['Refine to the goal', 'Every building crisp.']]);
  assert.match(full.notes.join(' '), /paint_accents does not do a refine_part step/);
  // Groups that leave an element out, or repeat one, are not used: the host's groups.
  const missing = fullProposal.map(s => s.kind === 'refine_part' && s.title === 'Refine: group 6' ? { ...s, parts: s.parts.slice(1) } : s);
  assert.deepEqual(shapePlan(missing, { draft: fullDraft, elements: twelve, known }).steps.filter(s => s.kind === 'refine_part').map(s => s.parts), groups.map(g => g.parts));
  // A proposal out of order, with no kinds: titles find the kinds; the order rules put it right; a missing stage comes from the draft.
  const muddled = [{ title: 'Accents', done_when: 'Crisp lights.' }, { title: 'Underpainting from the goal image', done_when: 'Laid.' }];
  const fixed = shapePlan(muddled, { draft: folderPlanSteps(['underpainting', 'finish', 'accents'], groups), elements: twelve, known });
  assert.deepEqual(fixed.steps.map(s => s.title), ['Underpainting from the goal image', 'Finish', 'Accents']);
  assert.equal(fixed.steps[2].done_when, 'Crisp lights.');
  // An element step the artist asked for (scope: its file) is kept after the stages.
  const withElement = shapePlan([...proposed.slice(0, 1), { title: 'Kremlin towers', done_when: 'Towers.', scope: 'assets/04-kremlin-towers.png' }], { draft, elements: twelve, known });
  assert.deepEqual(withElement.steps.map(s => s.kind), ['underpainting', 'element']);
});

test('groups the host replaces do not take the planner’s titles, words or materials (live, 2026-10-25: a duplicate step, wrong titles)', () => {
  const groups = refineGroups(twelve), known = ['paint_from_reference', 'paint_finish', 'refine_to_goal', 'paint_accents'];
  const draft = folderPlanSteps(['underpainting', 'finish', 'refine'], groups);
  // The planner left three elements out: its groups are not used, and its step 1 described other parts than the host's group 1.
  const theirs = [[1, 3], [4, 6], [7, 9], [8, 10], [11]].map(ix => ix.map(i => twelve[i].name));
  const proposal = [{ title: 'Underpainting', done_when: 'Laid in.', kind: 'underpainting' }, { title: 'Finish', done_when: 'Blended.', kind: 'finish' },
    ...theirs.map((parts, i) => ({ title: `Refine: their group ${i + 1}`, done_when: `Their group ${i + 1}.`, kind: 'refine_part', parts,
      materials: [{ aspect: 'walls', id: 'Bricks085' }] }))];
  const shaped = shapePlan(proposal, { draft, elements: twelve, known }).steps.filter(s => s.kind === 'refine_part');
  assert.deepEqual(shaped.map(s => s.parts), groups.map(g => g.parts), 'the host’s groups');
  assert.ok(shaped.every(s => !/their group/.test(s.title) && !/Their group/.test(s.done_when ?? '') && !s.materials), 'none of the planner’s words on groups it did not make');
  assert.equal(new Set(shaped.map(s => s.title)).size, shaped.length, 'no duplicate titles');
  // A host group the planner described with exactly the same parts keeps the planner’s words.
  const same = [...proposal.slice(0, 2), { title: 'Refine: their exact group', done_when: 'Exact.', kind: 'refine_part', parts: groups[0].parts, materials: [{ aspect: 'walls', id: 'Bricks085' }] }];
  const kept = shapePlan(same, { draft, elements: twelve, known }).steps.filter(s => s.kind === 'refine_part');
  assert.equal(kept[0].done_when, 'Exact.');
});

test('a later request adds the next stages; the end of a plan offers the ones not in it', () => {
  const groups = refineGroups(twelve);
  const plan = folderPlanSteps(['underpainting'], groups);
  assert.deepEqual(nextStages(plan), ['finish', 'refine', 'accents']);
  assert.deepEqual(nextStages(folderPlanSteps(['underpainting', 'finish', 'refine', 'accents'], groups)), []);
  assert.deepEqual(nextStages([{ title: 'Underpainting from the goal image' }, { title: 'Finish' }, { title: 'Refine to the goal' }, { title: 'Accents' }]), [], 'an older plan');
});

test('a refine step’s parts: its own list, else the element names in its title', () => {
  assert.deepEqual(partsOf({ title: 'Refine: x', parts: ['assets/03-domed-church.png', 'assets/99-gone.png'] }, twelve), ['assets/03-domed-church.png'], 'only elements of the folder');
  assert.deepEqual(partsOf({ title: 'Refine: Moonlit sky and Kremlin towers' }, twelve), ['assets/01-moonlit-sky.png', 'assets/04-kremlin-towers.png'], 'an old PLAN.md line');
  assert.deepEqual(partsOf({ title: 'Refine: the whole lot' }, twelve), []);
});

test('the union of found areas is one mask in the chat’s .shapes, measured on the canvas', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'refine-parts-'));
  try {
    await mkdir(join(dir, '.shapes'));
    const a = join(dir, '.shapes', 'found-' + 'a'.repeat(24) + '.png'), b = join(dir, '.shapes', 'found-' + 'b'.repeat(24) + '.png');
    await writeFile(a, encodePlane({ width: 2, height: 2, data: new Uint8Array([255, 255, 255, 255]) }));
    await writeFile(b, encodePlane({ width: 3, height: 1, data: new Uint8Array([255, 0, 255]) }));
    const union = await unionFound(dir, [{ mask_path: a, bounds: [0, 0, 2, 2], canvas: [10, 10] }, { mask_path: b, bounds: [5, 5, 3, 1], canvas: [10, 10] }]);
    assert.deepEqual(union.bounds, [0, 0, 8, 6]);
    assert.deepEqual(union.canvas, [10, 10]);
    assert.equal(union.share, 0.06);
    assert.match(union.mask_path, /\.shapes\/found-[0-9a-f]{24}\.png$/);
    const plane = decodePlane(await readFile(union.mask_path), { width: 8, height: 6 });
    assert.equal(plane.data.filter(v => v === 255).length, 6);
    assert.equal(plane.data[5 * 8 + 5], 255); assert.equal(plane.data[5 * 8 + 6], 0);
    const single = await unionFound(dir, [{ mask_path: a, bounds: [0, 0, 2, 2], canvas: [10, 10] }]);
    assert.equal(single.mask_path, a, 'one part: its own mask');
    await assert.rejects(unionFound(dir, [{ mask_path: join(tmpdir(), 'x.png'), bounds: [0, 0, 1, 1], canvas: [10, 10] }]), /\.shapes/);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

// Review fixes (2026-10-24).
test('a negated stage is taken away, from the whole set too', () => {
  assert.deepEqual(stagesNamed('paint everything except the accents'), { stages: [], whole: true, removed: ['accents'] });
  assert.deepEqual(stagesNamed('the whole thing but skip accents'), { stages: [], whole: true, removed: ['accents'] });
  assert.deepEqual(stagePolicy({ reading: null, act: false, text: 'paint everything except the accents' }).stages, ['underpainting', 'finish', 'refine']);
  assert.deepEqual(stagePolicy({ reading: null, act: false, text: 'the whole thing but skip accents' }).stages, ['underpainting', 'finish', 'refine']);
  assert.deepEqual(stagePolicy({ reading: reading(['whole', 0.95]), act: true, text: 'paint it all, no accents' }).stages, ['underpainting', 'finish', 'refine'], 'Luna\u2019s whole minus the negated stage');
  assert.equal(stagePolicy({ reading: null, act: false, text: 'paint everything except the accents' }).whole, false);
});

test('explicit stage requests: a stage named with a verb that asks for it, not a complaint about it', () => {
  assert.deepEqual(stagesNamed('Now the finish.', { explicit: true }).stages, ['finish']);
  assert.deepEqual(stagesNamed('also add accents', { explicit: true }).stages, ['accents']);
  assert.deepEqual(stagesNamed('Please paint the accents next.', { explicit: true }).stages, ['accents']);
  assert.deepEqual(stagesNamed('the highlights on the river are too bright', { explicit: true }).stages, []);
  assert.deepEqual(stagesNamed('more detail', { explicit: true }).stages, []);
  assert.deepEqual(stagesNamed('rename the finish step to Blend', { explicit: true }).stages, []);
});

test('revising a draft: its stages stay; only explicit additions and negations change them; never the full plan by default', () => {
  const cur = ['underpainting', 'finish', 'refine', 'accents'];
  assert.deepEqual(reviseStages({ current: cur, reading: null, act: false, text: 'rename the finish step' }).stages, cur);
  assert.deepEqual(reviseStages({ current: ['underpainting', 'finish'], reading: null, act: false, text: 'also add accents' }).stages, ['underpainting', 'finish', 'accents']);
  assert.deepEqual(reviseStages({ current: ['underpainting'], reading: null, act: false, text: 'use warmer colours' }).stages, ['underpainting']);
  assert.deepEqual(reviseStages({ current: cur, reading: null, act: false, text: 'drop the accents, no accents' }).stages, ['underpainting', 'finish', 'refine']);
  assert.deepEqual(reviseStages({ current: ['underpainting'], reading: null, act: false, text: 'actually, paint the whole thing' }).stages, cur, 'an explicit whole');
  assert.deepEqual(reviseStages({ current: ['underpainting'], reading: null, act: false, text: 'add refine too' }).stages, ['underpainting', 'finish', 'refine'], 'the order rules');
});

test('shapePlan drops whole-picture steps the request did not ask for; guides and the artist\u2019s own steps stay', () => {
  const draft = folderPlanSteps(['underpainting'], []), known = ['paint_from_reference', 'paint_finish', 'paint_accents', 'draw_guide', 'fill_region'];
  const proposed = [{ title: 'Underpainting', done_when: 'Laid.' }, { title: 'Blend and restroke the forms', done_when: 'Soft.' }, { title: 'Final highlights pass', done_when: 'Bright.' },
    { title: 'Guides for the towers', done_when: 'Lines placed.' }, { title: 'Soften the sky', done_when: 'Soft sky.' }];
  const shaped = shapePlan(proposed, { draft, elements: [], known, keepWhole: ['Soften the sky'] });
  assert.deepEqual(shaped.steps.map(s => s.title), ['Underpainting', 'Guides for the towers', 'Soften the sky']);
  assert.ok(shaped.dropped.includes('Blend and restroke the forms') && shaped.dropped.includes('Final highlights pass'));
});

test('a step\u2019s tool is only ever a known tool name: free text is dropped', () => {
  const known = ['paint_batch', 'fill_region'];
  assert.deepEqual(stepTool({ kind: 'whole', tool: 'paint_batch with fill_region for the disc' }, known), { note: 'paint_batch with fill_region for the disc is not a painting tool' });
});

test('stages the message names win over Luna reading its scope as the whole painting (live, 2026-10-25: "an underpainting, then the finish" got four steps)', () => {
  const reading = { stages: { scope: { choice: 'whole', confidence: 0.77 }, asked: { underpainting: 1, finish: 0.62, refine: 0, accents: 0 } } };
  const answer = stagePolicy({ reading, act: true, text: 'Paint this scene from the goal image: an underpainting, then the finish.' });
  assert.deepEqual(answer.stages, ['underpainting', 'finish']);
  assert.equal(answer.whole, false);
  const all = stagePolicy({ reading, act: true, text: 'Paint the whole scene from the goal image.' });
  assert.equal(all.whole, true, 'no stage named: the whole plan');
});
