// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Project folder B1: the read-only scan. Each test builds a tiny copy of the artist's folder shape (new_moscow) from
// header-only PNGs in a temporary folder and removes it afterwards; the artist's real folder is never read.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, truncate, symlink, readdir, readFile, stat, chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { scanFolder, FOLDER_LIMITS, elementGuess, defaultFolderSteps, elementStep, folderStepKind, elementsNamed, goalNamed, goalChoices } from '../src/project-folder.ts';

/** A PNG signature and IHDR: enough for imageInfo (files.mjs) to read the size. */
function tinyPng(width = 4, height = 3) {
  const data = Buffer.alloc(33);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(data, 0);
  data.writeUInt32BE(13, 8); data.write('IHDR', 12, 'latin1');
  data.writeUInt32BE(width, 16); data.writeUInt32BE(height, 20);
  return data;
}

const ELEMENTS = ['01-moonlit-sky', '02-historic-buildings', '03-domed-church', '04-kremlin-towers', '05-modern-skyline',
  '06-arched-bridge', '07-river-reflections', '08-snowy-street', '09-lamps-and-trees', '10-snowy-railing',
  '11-woman-back-view', '12-vintage-convertible'];

/** The shape of new_moscow: brief, goal, loose review images, a .kra and a png~ backup, numbered elements in a subfolder. */
async function artistFolder() {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  await writeFile(join(root, 'ART_BRIEF.md'), '# New Moscow\n\nA winter night in Moscow.\n');
  await writeFile(join(root, 'final_goal.png'), tinyPng(1448, 1086));
  for (const name of ['skies.png', 'two_skies.png', 'finished_review.png']) await writeFile(join(root, name), tinyPng());
  await writeFile(join(root, 'cockpit_closeup_prompt.md'), 'A close-up of the cockpit.\n');
  await writeFile(join(root, 'foreground_finish_candidate.png.kra'), 'not read');
  await writeFile(join(root, 'foreground_finish_candidate.png~'), tinyPng());
  await writeFile(join(root, '.DS_Store'), 'finder');
  const assets = join(root, 'moscow-painting-assets');
  await mkdir(assets);
  // Written out of order: the scan orders by number.
  for (const name of [...ELEMENTS].reverse()) await writeFile(join(assets, name + '.png'), tinyPng(1448, 1086));
  await writeFile(join(assets, 'generation-prompts.json'), JSON.stringify({ tool: 'test', assets: ELEMENTS.map(name => ({
    name, prompt: 'Use case: study. Subject: Only the ' + name.slice(3).replaceAll('-', ' ') + '.', path: '/elsewhere/' + name + '.png' })) }));
  return root;
}

/** Every file's name, size and mtime, to show a scan wrote nothing. */
async function snapshot(root) {
  const out = [];
  for (const entry of await readdir(root, { recursive: true, withFileTypes: true })) {
    const path = join(entry.parentPath ?? entry.path, entry.name);
    const info = await stat(path).catch(() => null);
    out.push([path, info?.size, info?.mtimeMs, entry.isFile() ? (await readFile(path)).toString('base64').slice(0, 64) : '']);
  }
  return JSON.stringify(out.sort());
}

test('a messy parent folder: elements in a subfolder, loose images listed as other, .kra and ~ backups skipped', async () => {
  const root = await artistFolder();
  try {
    const index = await scanFolder(root);
    assert.equal(index.goal?.name, 'final_goal.png');
    assert.deepEqual([index.goal?.width, index.goal?.height, index.goal?.role], [1448, 1086, 'goal']);
    assert.deepEqual(index.elements.map(e => e.name), ELEMENTS.map(name => 'moscow-painting-assets/' + name + '.png'));
    assert.deepEqual(index.elements.map(e => e.number), ELEMENTS.map((_, i) => i + 1));
    assert.equal(index.elements[0].guess, 'Moonlit sky');
    assert.equal(index.elements[11].guess, 'Vintage convertible');
    assert.ok(index.elements.every(e => e.role === 'element' && e.mimeType === 'image/png'));
    assert.match(index.elements[3].prompt ?? '', /kremlin towers/, 'the matching prompt entry describes the element');
    assert.ok(!JSON.stringify(index).includes('/elsewhere/'), 'paths inside the prompts file are never followed or kept');
    assert.deepEqual(index.others.map(o => o.name), ['finished_review.png', 'skies.png', 'two_skies.png'],
      'loose unnumbered images are listed, not made elements');
    const brief = index.texts.find(t => t.name === 'ART_BRIEF.md');
    assert.equal(brief?.kind, 'brief');
    assert.equal(index.texts.find(t => t.name === 'cockpit_closeup_prompt.md')?.kind, 'other');
    assert.equal(Object.keys(index.prompts).length, 12);
    const reasons = Object.fromEntries(index.skipped.map(s => [s.name, s.reason]));
    assert.match(reasons['foreground_finish_candidate.png.kra'], /Krita document/);
    assert.match(reasons['foreground_finish_candidate.png~'], /backup/);
    assert.ok(!('.DS_Store' in reasons), 'hidden system files are passed over silently');
    assert.ok(index.root.endsWith(root.split('/').at(-1)));
  } finally { await rm(root, { recursive: true, force: true }); }
});

/** The folder the artist opens: moscow-painting-assets with final_goal.png placed inside it, all files directly in it. */
async function cleanFolder() {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  await writeFile(join(root, 'final_goal.png'), tinyPng(1448, 1086));
  for (const name of [...ELEMENTS].reverse()) await writeFile(join(root, name + '.png'), tinyPng(1448, 1086));
  await writeFile(join(root, 'generation-prompts.json'), JSON.stringify({ tool: 'test', assets: ELEMENTS.map(name => ({
    name, prompt: 'Use case: study. Subject: Only the ' + name.slice(3).replaceAll('-', ' ') + '.', path: '/elsewhere/' + name + '.png' })) }));
  return root;
}

test('the artist\'s layout is read: goal, twelve numbered elements in order with guesses, prompts', async () => {
  const root = await cleanFolder();
  try {
    const before = await snapshot(root);
    const index = await scanFolder(root);
    assert.equal(index.goal?.name, 'final_goal.png');
    assert.deepEqual(index.elements.map(e => e.name), ELEMENTS.map(name => name + '.png'));
    assert.deepEqual(index.elements.map(e => e.guess), ['Moonlit sky', 'Historic buildings', 'Domed church', 'Kremlin towers', 'Modern skyline',
      'Arched bridge', 'River reflections', 'Snowy street', 'Lamps and trees', 'Snowy railing', 'Woman back view', 'Vintage convertible']);
    assert.ok(index.elements.every(e => /^Only the /.test(e.prompt ?? '')), 'each element carries its prompt subject');
    assert.deepEqual([index.others.length, index.texts.length, index.skipped.length], [0, 0, 0]);
    assert.equal(Object.keys(index.prompts).length, 12);
    assert.ok(!JSON.stringify(index).includes('/elsewhere/'));
    assert.equal(await snapshot(root), before);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('a guess comes from the file name', () => {
  assert.equal(elementGuess('04-kremlin-towers.png'), 'Kremlin towers');
  assert.equal(elementGuess('09_lamps_and_trees.jpg'), 'Lamps and trees');
  assert.equal(elementGuess('sub/12 vintage convertible.png'), 'Vintage convertible');
});

test('caps and skips: too many images, a file too large, a script, an archive and a WebP', async () => {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  try {
    for (let i = 1; i <= FOLDER_LIMITS.images + 1; i++) await writeFile(join(root, String(i).padStart(2, '0') + '-element.png'), tinyPng());
    const big = join(root, 'huge.png');
    await writeFile(big, tinyPng()); await truncate(big, 13_000_000);          // sparse: no 13 MB written
    await writeFile(join(root, 'run.py'), 'print("never run")\n');
    await writeFile(join(root, 'app.zip'), 'PK');
    await writeFile(join(root, 'sky.webp'), 'RIFF');
    const index = await scanFolder(root);
    assert.equal(index.elements.length + index.others.length + (index.goal ? 1 : 0), FOLDER_LIMITS.images);
    assert.equal(index.elements.at(-1)?.number, 40, 'the lowest numbers are read first');
    const reasons = Object.fromEntries(index.skipped.map(s => [s.name, s.reason]));
    assert.match(reasons['41-element.png'], /too many images/);
    assert.match(reasons['huge.png'], /too large/);
    assert.match(reasons['run.py'], /not run/);
    assert.match(reasons['app.zip'], /archive/);
    assert.match(reasons['sky.webp'], /WebP/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('a folder with more files than the cap stops reading and says so', async () => {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  try {
    for (let i = 0; i < 8; i++) await writeFile(join(root, `note-${i}.txt`), 'n');
    const index = await scanFolder(root, { ...FOLDER_LIMITS, files: 5 });
    assert.equal(index.texts.length, 5);
    assert.ok(index.skipped.some(s => /too many files/.test(s.reason)));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('a symlink pointing outside is skipped, a file or a folder; deeper folders are not read', async () => {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  const outside = await mkdtemp(join(tmpdir(), 'project-outside-'));
  try {
    await writeFile(join(outside, 'secret.png'), tinyPng());
    await writeFile(join(outside, 'secret.md'), 'secret');
    await symlink(join(outside, 'secret.png'), join(root, '01-sky.png'));
    await symlink(join(outside, 'secret.md'), join(root, 'NOTES.md'));
    await symlink(outside, join(root, 'linked-folder'));
    await mkdir(join(root, 'assets', 'deeper'), { recursive: true });
    await writeFile(join(root, 'assets', 'deeper', '02-hidden.png'), tinyPng());
    const index = await scanFolder(root);
    assert.deepEqual([index.elements.length, index.texts.length, index.others.length], [0, 0, 0]);
    const reasons = Object.fromEntries(index.skipped.map(s => [s.name, s.reason]));
    assert.match(reasons['01-sky.png'], /link/);
    assert.match(reasons['NOTES.md'], /link/);
    assert.match(reasons['linked-folder'], /link/);
    assert.match(reasons['assets/deeper'], /deeper/);
    assert.ok(!JSON.stringify(index).includes('secret'));
  } finally { await rm(root, { recursive: true, force: true }); await rm(outside, { recursive: true, force: true }); }
});

test('nothing is written while scanning, and PLAN.md and NOTES.md are recognised', async () => {
  const root = await artistFolder();
  try {
    await writeFile(join(root, 'PLAN.md'), '# Plan\n');
    await writeFile(join(root, 'NOTES.md'), '- a note\n');
    await writeFile(join(root, 'README.txt'), 'read me\n');
    const before = await snapshot(root);
    const index = await scanFolder(root);
    assert.equal(await snapshot(root), before);
    const kinds = Object.fromEntries(index.texts.map(t => [t.name, t.kind]));
    assert.deepEqual([kinds['PLAN.md'], kinds['NOTES.md'], kinds['README.txt']], ['plan', 'notes', 'readme']);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('a folder that is not there, or a file, is refused clearly', async () => {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  try {
    await assert.rejects(scanFolder(join(root, 'missing')), /folder/i);
    await writeFile(join(root, 'file.png'), tinyPng());
    await assert.rejects(scanFolder(join(root, 'file.png')), /folder/i);
  } finally { await rm(root, { recursive: true, force: true }); }
});

// Review fixes.
test('file names like constructor or __proto__ do not break the scan; control characters are skipped (I3, I4)', async () => {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  try {
    for (const name of ['01-constructor.png', 'constructor.png', 'toString.png', '__proto__.png', 'hasOwnProperty.png']) await writeFile(join(root, name), tinyPng());
    await writeFile(join(root, '02-bad\nname.png'), tinyPng());
    await writeFile(join(root, 'prompts.json'), JSON.stringify({ assets: [{ name: '__proto__', prompt: 'Subject: odd' }, { name: 'constructor', prompt: 42 }] }));
    const index = await scanFolder(root);
    assert.deepEqual(index.elements.map(e => e.name), ['01-constructor.png']);
    assert.equal(index.elements[0].prompt, undefined);
    assert.deepEqual(index.others.map(o => o.name).sort(), ['__proto__.png', 'constructor.png', 'hasOwnProperty.png', 'toString.png']);
    assert.equal(index.others.find(o => o.name === '__proto__.png')?.prompt, 'odd');
    assert.match(index.skipped.find(s => s.name.startsWith('02-bad'))?.reason ?? '', /control characters/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('a subfolder that cannot be read is listed as skipped, the scan goes on', async () => {
  const root = await mkdtemp(join(tmpdir(), 'project-folder-'));
  const locked = join(root, 'locked');
  try {
    await writeFile(join(root, '01-sky.png'), tinyPng());
    await mkdir(locked); await writeFile(join(locked, '02-hidden.png'), tinyPng());
    await chmod(locked, 0o000);
    const index = await scanFolder(root);
    assert.deepEqual(index.elements.map(e => e.name), ['01-sky.png']);
    assert.match(index.skipped.find(s => s.name === 'locked')?.reason ?? '', /could not be read/);
  } finally { await chmod(locked, 0o755).catch(() => {}); await rm(root, { recursive: true, force: true }); }
});

// Plan shape (the artist, 2026-10-23): underpainting, accents, then the artist says what to refine; element steps only on
// request. The finish between the underpainting and the accents (finish-stage, approved 2026-10-24).
test('the default folder plan is the underpainting, the finish, then accents on the whole picture; no element steps', () => {
  const steps = defaultFolderSteps();
  assert.deepEqual(steps.map(s => [s.title, s.scope]), [['Underpainting from the goal image', 'whole composition'], ['Finish', 'whole composition'], ['Accents', 'whole composition']]);
  assert.match(steps[1].done_when, /blended/i); assert.match(steps[1].done_when, /strokes/i);
  assert.match(steps[2].done_when, /lights/i); assert.match(steps[2].done_when, /darks/i);
  assert.deepEqual(steps.map(folderStepKind), ['underpainting', 'finish', 'accents']);
  // Review finding: only the default step's own title is the finish; older PLAN.md titles keep their kinds.
  assert.equal(folderStepKind({ title: ' finish ', scope: 'whole composition' }), 'finish');
  assert.equal(folderStepKind({ title: 'Finishing touches on the sky', scope: 'whole composition' }), 'whole');
  assert.equal(folderStepKind({ title: 'Finish the underpainting of the whole picture', scope: 'whole composition' }), 'underpainting');
  assert.equal(folderStepKind({ title: 'Finished sky glow', scope: 'whole composition' }), 'whole', 'only a step named for the finish');
  assert.equal(folderStepKind({ title: 'Finish with accents', scope: 'whole composition' }), 'accents');
  const towers = elementStep('assets/04-kremlin-towers.png', 'Kremlin towers');
  assert.deepEqual([towers.title, towers.scope, folderStepKind(towers)], ['Kremlin towers', 'assets/04-kremlin-towers.png', 'element']);
  assert.equal(folderStepKind({ title: 'Soften the sky', scope: 'whole composition' }), 'whole', 'an artist\u2019s own whole-picture step is neither');
  assert.equal(folderStepKind({ title: 'Block-in of the whole composition' }), 'underpainting');
  assert.equal(folderStepKind({ title: 'Lights and accents', scope: 'whole composition' }), 'accents');
});

test('elementsNamed: the elements an artist\u2019s message names, by name, file or head word, in the folder\u2019s order', () => {
  const elements = [{ name: 'assets/01-moonlit-sky.png', guess: 'Moonlit sky' }, { name: 'assets/02-historic-buildings.png', guess: 'Historic buildings' },
    { name: 'assets/04-kremlin-towers.png', guess: 'Kremlin towers' }];
  assert.deepEqual(elementsNamed('Now refine the Kremlin towers, please.', elements), ['assets/04-kremlin-towers.png']);
  assert.deepEqual(elementsNamed('the towers and the sky need more', elements), ['assets/01-moonlit-sky.png', 'assets/04-kremlin-towers.png']);
  assert.deepEqual(elementsNamed('Paint 02-historic-buildings.png next', elements), ['assets/02-historic-buildings.png']);
  assert.deepEqual(elementsNamed('the tower on the left', elements), ['assets/04-kremlin-towers.png'], 'singular of the head word');
  assert.deepEqual(elementsNamed('Looks great, keep going.', elements), []);
  assert.deepEqual(elementsNamed('skyline', elements), [], 'whole words only');
  assert.deepEqual(elementsNamed('', elements), []);
  // Review B1: a negated or passing mention names nothing.
  const more = [...elements, { name: 'assets/05-street-light.png', guess: 'Street light' }, { name: 'assets/06-buildings-left.png', guess: 'Buildings on the left' }];
  for (const text of ['don\u2019t paint the sky', 'leave the towers alone', 'the light is too harsh', 'the left side is too dark', 'Do not touch the Kremlin towers.'])
    assert.deepEqual(elementsNamed(text, more), [], text);
  assert.deepEqual(elementsNamed('work on the Kremlin towers', more), ['assets/04-kremlin-towers.png']);
  assert.deepEqual(elementsNamed('the sky looks too cold', more), ['assets/01-moonlit-sky.png']);
  assert.deepEqual(elementsNamed('leave the sky alone, refine the street light', more), ['assets/05-street-light.png'], 'each mention decides in its own clause');
});

// Goal picker (goal-image change): the artist chooses which folder image is the goal; without a choice, today's rule.
test('the goal is the artist\u2019s choice when one is given: a numbered image leaves the elements, final_goal.png becomes another image', async () => {
  const root = await cleanFolder();
  try {
    const plain = await scanFolder(root);
    assert.equal(plain.goal?.name, 'final_goal.png'); assert.equal(plain.goal_source, 'name');
    const chosen = await scanFolder(root, FOLDER_LIMITS, { goal: '05-modern-skyline.png' });
    assert.deepEqual([chosen.goal?.name, chosen.goal?.role, chosen.goal?.guess, chosen.goal_source], ['05-modern-skyline.png', 'goal', 'Goal image', 'chosen']);
    assert.ok(!chosen.elements.some(e => e.name === '05-modern-skyline.png'), 'the goal is not also an element');
    assert.equal(chosen.elements.length, 11);
    assert.deepEqual(chosen.others.map(o => o.name), ['final_goal.png'], 'the old goal is listed among the other images');
    const missing = await scanFolder(root, FOLDER_LIMITS, { goal: 'gone.png' });
    assert.deepEqual([missing.goal?.name, missing.goal_source], ['final_goal.png', 'name'], 'a choice no longer in the folder falls back to the rule');
    const none = await scanFolder(root, FOLDER_LIMITS, { goal: '../outside.png' });
    assert.equal(none.goal?.name, 'final_goal.png', 'a name outside the folder is never a choice');
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('goalChoices: every image of the folder, the goal first, then the elements in order, then the other images', async () => {
  const root = await artistFolder();
  try {
    const index = await scanFolder(root);
    const choices = goalChoices(index);
    assert.equal(choices[0], 'final_goal.png');
    assert.deepEqual(choices.slice(1, 3), ['moscow-painting-assets/01-moonlit-sky.png', 'moscow-painting-assets/02-historic-buildings.png']);
    assert.deepEqual(choices.slice(-3), ['finished_review.png', 'skies.png', 'two_skies.png']);
    assert.equal(choices.length, 1 + 12 + 3);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('goalNamed: a typed message that makes a folder image the goal, by file name or stem; anything else names none', () => {
  const images = ['final_goal.png', 'assets/05-modern-skyline.png', 'assets/04-kremlin-towers.png', 'skies.png'];
  assert.equal(goalNamed('use 05-modern-skyline.png as the goal', images), 'assets/05-modern-skyline.png');
  assert.equal(goalNamed('Use 05-modern-skyline as the goal image.', images), 'assets/05-modern-skyline.png');
  assert.equal(goalNamed('make skies.png the goal', images), 'skies.png');
  assert.equal(goalNamed('Set the goal image to assets/04-kremlin-towers.png please', images), 'assets/04-kremlin-towers.png');
  assert.equal(goalNamed('switch the goal to 04-kremlin-towers.png', images), 'assets/04-kremlin-towers.png');
  for (const text of ['Paint 04-kremlin-towers.png as the goal shows it', 'Make the tower as the goal image has it, see 04-kremlin-towers.png',
    'Keep 05-modern-skyline as the goal picture does', 'the goal is final_goal.png again', 'paint the modern skyline', 'refine 05-modern-skyline.png', 'don\u2019t use skies.png as the goal', 'use skies.png as a colour reference',
    'the goal is a snowy night', 'use 99-nothing.png as the goal', ''])
    assert.equal(goalNamed(text, images), null, text);
  assert.equal(goalNamed('use final_goal.png or skies.png as the goal', images), null, 'two images named: not a choice');
});
