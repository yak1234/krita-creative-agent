// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Project folder B3: the Markdown the agent keeps in the folder (PLAN.md, NOTES.md, dated backups). Temporary folders only,
// removed after each test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile, readdir, symlink, link } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writePlan, appendNote, readPlan, planDifference, editMarkdown, planText, remapTicks, briefFromPlan, stepKeys, parsePlan, layerName } from '../src/folder-notes.ts';

const brief = { title: 'New Moscow', objective: 'A snowy night in Moscow, painted one element per move.', requirements: ['Keep the warm windows.'],
  freedom: [], completion: ['Every element is painted.'], steps: [
    { title: 'Block-in: the whole composition', done_when: 'Placed.', scope: 'whole composition' },
    { title: 'Moonlit sky', done_when: 'Sky painted.', scope: '01-moonlit-sky.png' },
    { title: 'Historic buildings', done_when: 'Buildings painted.', scope: '02-historic-buildings.png' },
    { title: 'Kremlin towers', done_when: 'Towers painted.', scope: '04-kremlin-towers.png' }] };
const today = new Date().toISOString().slice(0, 10);

async function folder(work) {
  const root = await mkdtemp(join(tmpdir(), 'folder-notes-'));
  try { await work(root); } finally { await rm(root, { recursive: true, force: true }); }
}

test('PLAN.md is written with ticks and references', () => folder(async root => {
  const { text } = await writePlan(root, brief, [0, 1], { goal: 'final_goal.png' });
  const written = await readFile(join(root, 'PLAN.md'), 'utf8');
  assert.equal(written, text);
  assert.match(written, /^# Plan · New Moscow/);
  assert.match(written, /Goal image: final_goal\.png/);
  assert.match(written, /Keep the warm windows\./);
  assert.match(written, /^- \[x\] 1\. Block-in: the whole composition · layer "Block-in: the whole composition"$/m);
  assert.match(written, /^- \[x\] 2\. Moonlit sky \(01-moonlit-sky\.png\) · layer "Moonlit sky"$/m);
  assert.match(written, /^- \[ \] 4\. Kremlin towers \(04-kremlin-towers\.png\) · layer "Kremlin towers"$/m);
  const plan = await readPlan(root);
  assert.deepEqual(plan.ticked, [0, 1]);
  assert.deepEqual(plan.steps.map(s => [s.title, s.file ?? null]), [['Block-in: the whole composition', null], ['Moonlit sky', '01-moonlit-sky.png'],
    ['Historic buildings', '02-historic-buildings.png'], ['Kremlin towers', '04-kremlin-towers.png']]);
  assert.equal(plan.title, 'New Moscow');
  assert.equal(await readPlan(join(root, 'missing')).catch(() => 'refused'), 'refused');
  const second = await writePlan(root, brief, [0, 1, 2], { expected: text });
  assert.equal(second.backup, undefined, 'the agent\'s own last version is replaced without a backup');
}));

test('a PLAN.md changed outside is backed up before it is rewritten', () => folder(async root => {
  const { text } = await writePlan(root, brief, []);
  await writeFile(join(root, 'PLAN.md'), text + '\nmy own line\n');
  const result = await writePlan(root, brief, [0], { expected: text });
  assert.equal(result.backup, `PLAN.backup-${today}.md`);
  assert.match(await readFile(join(root, result.backup), 'utf8'), /my own line/);
  await writeFile(join(root, 'PLAN.md'), 'again by hand\n');
  const again = await writePlan(root, brief, [0], { expected: result.text });
  assert.equal(again.backup, `PLAN.backup-${today}-2.md`, 'an earlier backup of the day is never overwritten');
}));

test('NOTES.md only grows', () => folder(async root => {
  await writeFile(join(root, 'NOTES.md'), '# Notes\n\n- the artist\'s own line');
  await appendNote(root, 'Move 2 kept: Moonlit sky (step 2).');
  await appendNote(root, 'Move 3 kept: Historic buildings (step 3).\nsecond line folded');
  const text = await readFile(join(root, 'NOTES.md'), 'utf8');
  assert.ok(text.startsWith('# Notes\n\n- the artist\'s own line\n'), 'what was there stays, a missing newline is added');
  assert.match(text, new RegExp(`^- ${today} · Move 2 kept: Moonlit sky \\(step 2\\)\\.$`, 'm'));
  assert.match(text, /Move 3 kept: Historic buildings \(step 3\)\. second line folded$/m);
}));

test('editing the artist\'s brief makes a dated backup first; the agent\'s own file is edited in place', () => folder(async root => {
  await writeFile(join(root, 'ART_BRIEF.md'), '# Brief\nMine.\n');
  const result = await editMarkdown(root, 'ART_BRIEF.md', '# Brief\nMine, revised.\n');
  assert.deepEqual(result, { changed: true, backup: `ART_BRIEF.backup-${today}.md` });
  assert.equal(await readFile(join(root, result.backup), 'utf8'), '# Brief\nMine.\n');
  assert.equal(await readFile(join(root, 'ART_BRIEF.md'), 'utf8'), '# Brief\nMine, revised.\n');
  assert.deepEqual(await editMarkdown(root, 'ART_BRIEF.md', '# Brief\nMine, revised.\n'), { changed: false });
  assert.deepEqual(await editMarkdown(root, 'IDEAS.md', 'new\n'), { changed: true }, 'a new file needs no backup');
  assert.deepEqual(await editMarkdown(root, 'IDEAS.md', 'newer\n', { created: ['IDEAS.md'] }), { changed: true });
}));

test('writing anything but .md or outside the folder is refused', () => folder(async root => {
  const outside = await mkdtemp(join(tmpdir(), 'folder-outside-'));
  try {
    await mkdir(join(root, 'sub'));
    for (const name of ['notes.txt', 'image.png', '../escape.md', 'sub/inner.md', '/tmp/abs.md', '.hidden.md', 'run.py'])
      await assert.rejects(editMarkdown(root, name, 'x'), /Markdown file|inside the project folder/, name);
    await writeFile(join(outside, 'target.md'), 'outside\n');
    await symlink(join(outside, 'target.md'), join(root, 'NOTES.md'));
    await assert.rejects(appendNote(root, 'x'), /link/);
    await assert.rejects(editMarkdown(root, 'NOTES.md', 'x'), /link/);
    await symlink(join(outside, 'target.md'), join(root, 'PLAN.md'));
    await assert.rejects(writePlan(root, brief, []), /link/);
    assert.equal(await readFile(join(outside, 'target.md'), 'utf8'), 'outside\n', 'nothing reached the file the link points to');
    assert.deepEqual((await readdir(outside)).sort(), ['target.md']);
  } finally { await rm(outside, { recursive: true, force: true }); }
}));

test('planDifference lists a reorder, a removal, an addition and a hand tick', () => folder(async root => {
  const { text } = await writePlan(root, brief, []);
  const lines = text.split('\n');
  const towers = lines.findIndex(l => l.includes('Kremlin towers')), sky = lines.findIndex(l => l.includes('Moonlit sky'));
  const edited = [...lines];
  [edited[towers], edited[sky]] = [edited[sky].replace('- [ ]', '- [x]'), edited[towers]];
  edited.splice(edited.findIndex(l => l.includes('Historic buildings')), 1, '- [ ] 9. Snowy street (08-snowy-street.png)');
  const differences = planDifference(brief, edited, []);
  assert.ok(differences.some(d => /Removed: Historic buildings/.test(d)), differences.join('\n'));
  assert.ok(differences.some(d => /Added: Snowy street/.test(d)), differences.join('\n'));
  assert.ok(differences.some(d => /Moved: Kremlin towers/.test(d)), differences.join('\n'));
  assert.ok(differences.some(d => /Ticked: Moonlit sky/.test(d)), differences.join('\n'));
  assert.deepEqual(planDifference(brief, lines, []), [], 'the plan as written has no difference');
  const followed = briefFromPlan({ title: 'New Moscow', steps: [{ title: 'Kremlin towers', file: '04-kremlin-towers.png', done: false }, { title: 'Snowy street', file: '08-snowy-street.png', done: false }] }, brief);
  assert.deepEqual(followed.steps.map(s => [s.title, s.done_when, s.scope]), [['Kremlin towers', 'Towers painted.', '04-kremlin-towers.png'],
    ['Snowy street', 'Snowy street is painted where the goal image places it.', '08-snowy-street.png']], 'kept steps keep their checks');
}));

test('ticks follow their steps when the plan is revised', () => {
  const revised = { ...brief, steps: [brief.steps[0], brief.steps[3], brief.steps[1]] };
  assert.deepEqual(remapTicks(brief, revised, [0, 1]), [0, 2]);
  assert.equal(planText(brief, []).includes('[x]'), false);
});

// Review fixes.
const twin = { ...brief, steps: [brief.steps[0], { title: 'Tower', done_when: 'Left tower.', scope: '03-tower-left.png' },
  { title: 'Tower', done_when: 'Right tower.', scope: '04-tower-right.png' }, { title: 'Snow', done_when: 'a' }, { title: 'Snow', done_when: 'b' }] };

test('steps with the same title are told apart by their file, else by their order (I2)', () => {
  assert.deepEqual(remapTicks(twin, twin, [1]), [1]);
  assert.deepEqual(remapTicks(twin, twin, [4]), [4]);
  const swapped = { ...twin, steps: [twin.steps[0], twin.steps[2], twin.steps[1], twin.steps[3], twin.steps[4]] };
  assert.deepEqual(remapTicks(twin, swapped, [1]), [2], 'the left tower\'s tick follows the left tower');
  const lines = planText(twin, []).split('\n');
  assert.deepEqual(planDifference(twin, lines, []), []);
  const parsed = briefFromPlan({ title: 'x', steps: [{ title: 'Tower', file: '04-tower-right.png', done: false }] }, twin);
  assert.equal(parsed.steps[0].done_when, 'Right tower.');
  assert.deepEqual(stepKeys(twin.steps), ['title:block-in: the whole composition#0', 'file:03-tower-left.png', 'file:04-tower-right.png', 'title:snow#0', 'title:snow#1']);
});

test('PLAN.md is parsed only under its Moves heading, and what it writes cannot inject steps (I4)', () => {
  const sneaky = { ...brief, objective: '- [ ] 1. Injected from the objective', requirements: ['[x] 2. Injected', '## Moves', '* [ ] star'],
    steps: [{ title: 'Lamps (and trees)', done_when: 'x', scope: '09-lamps.png' }, { title: 'The "big" moon\u0007', done_when: 'y' },
      { title: 'Sky', done_when: 'z', scope: '01-sky\n- [ ] 9. evil.png' }] };
  const text = planText(sneaky, [0]);
  const plan = parsePlan(text);
  assert.deepEqual(plan.steps.map(s => [s.title, s.file ?? null, s.done]), [['Lamps (and trees)', '09-lamps.png', true],
    ["The 'big' moon", null, false], ['Sky', '01-sky - [ ] 9. evil.png', false]]);
  assert.ok(!/[\u0000-\u0008\u000b-\u001f]/.test(text), 'no control characters are written');
  assert.ok(text.split('\n').filter(l => /^\s*[-*]\s+\[/.test(l)).length === 3, 'only the three step lines look like checklist items');
  assert.equal(layerName('Lamps (and trees)'), 'Lamps (and trees)');
  assert.equal(layerName('Moonlit sky (01-moonlit-sky.png)'), 'Moonlit sky');
  assert.deepEqual(parsePlan('# Plan · x\n\n- [x] 1. Above the heading\n\n## Moves\n\n- [ ] 1. Real step\n\n## Later\n\n- [ ] 2. After\n').steps.map(s => s.title), ['Real step']);
});

test('a large PLAN.md the agent did not write is backed up without being read whole; hard links are refused (minors)', () => folder(async root => {
  const big = '# Plan\n' + 'x'.repeat(300_000) + '\n';
  await writeFile(join(root, 'PLAN.md'), big);
  const result = await writePlan(root, brief, []);
  assert.equal(result.backup, `PLAN.backup-${today}.md`);
  assert.equal((await readFile(join(root, result.backup), 'utf8')).length, big.length);
  await writeFile(join(root, 'NOTES.md'), 'y'.repeat(300_000));
  await appendNote(root, 'still grows');
  assert.match(await readFile(join(root, 'NOTES.md'), 'utf8'), /y\n- \d{4}-\d{2}-\d{2} · still grows\n$/);
  const outside = await mkdtemp(join(tmpdir(), 'folder-outside-'));
  try {
    await writeFile(join(outside, 'shared.md'), 'outside\n');
    await link(join(outside, 'shared.md'), join(root, 'IDEAS.md'));
    await assert.rejects(editMarkdown(root, 'IDEAS.md', 'x', { created: ['IDEAS.md'] }), /link/);
    assert.equal(await readFile(join(outside, 'shared.md'), 'utf8'), 'outside\n');
  } finally { await rm(outside, { recursive: true, force: true }); }
}));

// Plan step controls (plan-step-controls goal 3): PLAN.md records skipped, met (by the artist or "good enough") and redone
// steps after the layer, keyed by step identity, and reads them back (a resumed or new chat restores them).
test('PLAN.md records skipped, met and redone steps and reads them back', () => folder(async root => {
  const keys = stepKeys(brief.steps);
  const marks = { [keys[1]]: { met: 'artist', redone: 1 }, [keys[2]]: { skipped: true }, [keys[3]]: { met: 'good_enough', redone: 2 } };
  const { text } = await writePlan(root, brief, [1, 3], { marks });
  assert.match(text, /^- \[x\] 2\. Moonlit sky \(01-moonlit-sky\.png\) · layer "Moonlit sky" · met by the artist · redone 1 time$/m);
  assert.match(text, /^- \[ \] 3\. Historic buildings \(02-historic-buildings\.png\) · layer "Historic buildings" · skipped$/m);
  assert.match(text, /^- \[x\] 4\. Kremlin towers \(04-kremlin-towers\.png\) · layer "Kremlin towers" · good enough · redone 2 times$/m);
  assert.match(text, /^- \[ \] 1\. Block-in: the whole composition · layer "Block-in: the whole composition"$/m, 'an unmarked step is written as before');
  const plan = await readPlan(root);
  assert.deepEqual(plan.steps.map(s => [s.title, s.layer, s.done]), [['Block-in: the whole composition', 'Block-in: the whole composition', false],
    ['Moonlit sky', 'Moonlit sky', true], ['Historic buildings', 'Historic buildings', false], ['Kremlin towers', 'Kremlin towers', true]]);
  assert.deepEqual(plan.marks, marks, 'the marks come back keyed by step identity');
  assert.deepEqual(planDifference(brief, text.split('\n'), [1, 3], marks), [], 'the plan as written has no difference');
}));

test('a step skipped or restored by hand in PLAN.md is a difference the artist is asked about', () => {
  const keys = stepKeys(brief.steps);
  const lines = planText(brief, [], { marks: { [keys[3]]: { skipped: true } } }).split('\n');
  const edited = lines.map(l => l.includes('Historic buildings') ? l + ' · skipped' : l.includes('Kremlin towers') ? l.replace(' · skipped', '') : l);
  const differences = planDifference(brief, edited, [], { [keys[3]]: { skipped: true } });
  assert.deepEqual(differences, ['Skipped: Historic buildings', 'Restored: Kremlin towers']);
  assert.deepEqual(parsePlan(edited.join('\n')).marks, { [keys[2]]: { skipped: true } });
  assert.deepEqual(parsePlan('## Moves\n\n- [ ] 1. Sky · SKIPPED\n').marks, { 'title:sky#0': { skipped: true } }, 'by hand, in any case, without a layer');
});

test('marks written by hand anywhere in a step line are read, and met or unmet by hand is a difference', () => {
  const keys = stepKeys(brief.steps);
  const plan = parsePlan('## Moves\n\n- [ ] 2. Moonlit sky · skipped (01-moonlit-sky.png) · layer "Moonlit sky"\n'
    + '- [x] 3. Historic buildings · good enough · layer "Historic buildings" (02-historic-buildings.png)\n');
  assert.deepEqual(plan.steps.map(s => [s.title, s.file ?? null, s.mark ?? null]), [['Moonlit sky', '01-moonlit-sky.png', { skipped: true }],
    ['Historic buildings', '02-historic-buildings.png', { met: 'good_enough' }]]);
  const lines = planText(brief, [1], { marks: { [keys[1]]: { met: 'artist' } } }).split('\n');
  const edited = lines.map(l => l.includes('Moonlit sky') ? l.replace(' · met by the artist', '') : l.includes('Kremlin towers') ? l + ' · met by the artist' : l);
  assert.deepEqual(planDifference(brief, edited, [1], { [keys[1]]: { met: 'artist' } }), ['Unmarked met: Moonlit sky', 'Marked met: Kremlin towers']);
});
