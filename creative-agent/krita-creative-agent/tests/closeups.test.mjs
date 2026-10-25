// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Close-up references for detail (after-the-underpainting goal 1): which references are close-ups of the goal, their
// alignment once per content (the plugin's align_closeup, faked here), the artist's yes before first use, and detail
// transfers from the goal routed to the close-up. Temporary folders only, removed after each test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, readFile, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { chatCloseups, goalReference, closeupCandidates, mapSource, CLOSEUP_ANSWERS, MIN_SHARPER } from '../src/closeups.ts';
import { referenceTools } from '../src/reference-tool.mjs';

const sha = data => createHash('sha256').update(data).digest('hex');
// A close-up of goal box [300, 600, 250, 240] at 4x: close-up pixel = (goal - box origin) * 4.
const PLACED = { status: 'ok', aligned: true, matrix: [0.25, 0, 300, 0, 0.25, 600, 0, 0, 1],
  quad: [[300, 600], [550, 600], [550, 840], [300, 840]], box: [300, 600, 250, 240], scale: 4, rotation: 0,
  matches: 300, inliers: 280, inlier_ratio: .93, spread: .8, similarity: .97, score: .95, ms: 180,
  goal_size: [1448, 1086], closeup_size: [1000, 960], method: 'sift-homography', preview_jpeg_base64: Buffer.from('jpeg').toString('base64') };

function edgeImage(w, h, at = w / 2) {                     // dark left of `at`, light right of it: one edge (the middle)
  const data = Buffer.alloc(w * h * 4, 255);
  for (let y = 0; y < h; y++) for (let x = 0; x < at; x++) data.fill(30, (y * w + x) * 4, (y * w + x) * 4 + 3);
  return { width: w, height: h, rgba_base64: data.toString('base64') };
}

async function chat(work, { folder = true, answers = {} } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'closeups-'));
  try {
    const file = async (name, text) => { const path = join(directory, name); await writeFile(path, text); return path; };
    const references = folder ? [
      { id: 'goal', path: await file('goal.png', 'goal pixels'), role: 'reference', name: 'final_goal.png', width: 1448, height: 1086, source: 'folder', folder_name: 'final_goal.png' },
      { id: 'woman', path: await file('woman.png', 'woman pixels'), role: 'asset', name: '11-woman-back-view.png', width: 1000, height: 960, source: 'folder', folder_name: '11-woman-back-view.png', notes: 'Element: Woman back view' },
      { id: 'sky', path: await file('sky.png', 'sky pixels'), role: 'asset', name: '01-moonlit-sky.png', width: 1448, height: 1086, source: 'folder', folder_name: '01-moonlit-sky.png', notes: 'Element: Moonlit sky' },
    ] : [];
    const calls = [], events = [], asked = [];
    const host = {
      study: { id: 'chat', directory, references },
      canvas: { width: 6000, height: 4500 },
      persisted: 0,
      async persist() { this.persisted++; },
      emit(event) { events.push(event); },
      reads: 0,
      async readReference(ref) { this.reads++; return readFile(ref.path); },
      async statReference(ref) { const { size, mtimeMs } = await stat(ref.path); return { size, mtimeMs }; },
      async callNative(operation, params) {
        calls.push({ operation, params });
        assert.equal(operation, 'align_closeup');
        const name = references.find(r => sha(Buffer.from(params.closeup.image_base64, 'base64')) === r.sha)?.id;
        return answers[name] ?? { status: 'ok', aligned: false, reason: 'The matching features do not agree on one place in the goal (5 of 45 agree).', matches: 45, inliers: 5, ms: 260, goal_size: [1448, 1086], closeup_size: [1448, 1086] };
      },
      ask(question) { asked.push(question); },
    };
    for (const r of references) r.sha = sha(await readFile(r.path));
    const closeups = chatCloseups(host);
    await work({ host, closeups, calls, events, asked, references, directory, file });
  } finally { await rm(directory, { recursive: true, force: true }); }
}

test('the goal is the folder’s goal image, else the reference with the canvas’s proportions; close-ups are the others that show a part', () => {
  const canvas = { width: 6000, height: 4500 };
  const goal = { id: 'g', role: 'reference', width: 1448, height: 1086, source: 'folder' };
  const element = { id: 'e', role: 'asset', width: 1448, height: 1086, source: 'folder', folder_name: '11-woman.png' };
  const asset = { id: 'a', role: 'asset', width: 800, height: 800 };                       // a generated asset: not a close-up
  const part = { id: 'p', role: 'reference', width: 1448, height: 1086, part_kind: 'part', part_of: 'g', bounds: [0, 0, 10, 10] };
  const photo = { id: 'f', role: 'reference', width: 3000, height: 4000 };                   // other proportions: a part of the picture
  assert.equal(goalReference([element, goal, photo], canvas)?.id, 'g');
  assert.deepEqual(closeupCandidates([goal, element, asset, part, photo], goal).map(r => r.id), ['e', 'f']);
  const picture = { id: 'r', role: 'reference', width: 1600, height: 1200 };                 // no folder: the canvas's proportions
  assert.equal(goalReference([photo, picture], canvas)?.id, 'r');
  assert.equal(goalReference([photo], canvas), null, 'no picture of the whole: nothing to align to');
  assert.deepEqual(closeupCandidates([picture, photo, { ...picture, id: 'r2' }], picture).map(r => r.id), ['f'], 'another whole picture is not a close-up');
});

test('each close-up is aligned once per content of both images; refusals are kept with their reason', () => chat(async ({ closeups, calls, host, references, directory }) => {
  await closeups.refresh();
  assert.equal(calls.length, 2, 'the woman and the sky, the goal not with itself');
  assert.equal(calls[0].params.goal.sha256, references[0].sha);
  assert.equal(calls[0].params.preview, true);
  const records = host.study.closeups;
  assert.equal(records.sky.aligned, false);
  assert.match(records.sky.reason, /do not agree/);
  await closeups.refresh();
  assert.equal(calls.length, 2, 'cached: nothing aligned again');
  await writeFile(references[2].path, 'another sky'); references[2].sha = sha('another sky');
  await closeups.refresh();
  assert.equal(calls.length, 3, 'a changed image is aligned again');
  assert.ok(host.persisted > 0);
  assert.equal(directory, host.study.directory);
}, { answers: {} }));

test('an aligned close-up is shown to the artist before its first use, with its place drawn on the goal', () => chat(async ({ closeups, host, asked, directory }) => {
  await closeups.refresh();
  const record = host.study.closeups.woman;
  assert.equal(record.aligned, true);
  assert.equal(record.confirmed, undefined);
  assert.equal(await readFile(join(directory, record.preview), 'utf8'), 'jpeg');
  const recipe = { name: 'Hair', reference_id: 'goal', source: [350, 640, 100, 80], target: [1450, 2650, 415, 332] };
  assert.equal(await closeups.route(recipe), null, 'not confirmed yet: this transfer samples the goal, nothing waits');
  assert.equal(asked.length, 1);
  assert.equal(asked[0].closeup_id, 'woman');
  assert.equal(await closeups.route(recipe), null);
  assert.equal(asked.length, 1, 'asked once a run');
  closeups.startRun();
  await closeups.route(recipe);
  assert.equal(asked.length, 2, 'a new run may show it again while it is unanswered');
  assert.match(asked[0].question, /11-woman-back-view\.png/);
  assert.match(asked[0].question, /4x/);
  assert.deepEqual(asked[0].options, CLOSEUP_ANSWERS);
  assert.equal(asked[0].recommended, CLOSEUP_ANSWERS[0], 'Auto-approve takes Use the close-up there: the host found it aligned and sharper');
  assert.equal(asked[0].image_path, join(directory, record.preview));
  assert.equal(closeups.answer('woman', CLOSEUP_ANSWERS[0]), true);
  assert.equal(host.study.closeups.woman.confirmed, 'yes');
  const used = await closeups.route(recipe);
  assert.equal(used.recipe.reference_id, 'woman');
  assert.deepEqual(used.recipe.source, [200, 160, 400, 320], 'the goal rect mapped into close-up pixels');
  assert.deepEqual(used.recipe.target, recipe.target);
  assert.match(used.note, /11-woman-back-view\.png/);
  assert.match(used.note, /enlarges 1x, not 4\.2x/);
  assert.equal(asked.length, 2, 'a confirmed close-up is not asked about again');
}, { answers: { woman: PLACED } }));

test('a declined close-up, a source outside it, another reference or a turned close-up keep sampling the goal', () => chat(async ({ closeups, host }) => {
  await closeups.refresh();
  closeups.answer('woman', 'yes');
  assert.equal(await closeups.route({ reference_id: 'goal', source: [100, 100, 100, 80], target: [0, 0, 400, 320] }), null, 'outside the close-up');
  assert.equal(await closeups.route({ reference_id: 'goal', source: [500, 600, 100, 80], target: [0, 0, 400, 320] }), null, 'only partly inside');
  assert.equal(await closeups.route({ reference_id: 'sky', source: [350, 640, 100, 80], target: [0, 0, 400, 320] }), null, 'not from the goal');
  host.study.closeups.woman.rotation = 12;
  assert.equal(await closeups.route({ reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320] }), null, 'turned');
  host.study.closeups.woman.rotation = 0;
  closeups.answer('woman', CLOSEUP_ANSWERS[1]);
  assert.equal(host.study.closeups.woman.confirmed, 'no');
  assert.equal(await closeups.route({ reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320] }), null, 'declined');
}, { answers: { woman: PLACED } }));

test('a close-up no sharper than the goal there is recorded but never asked about or used', () => chat(async ({ closeups, asked }) => {
  await closeups.refresh();
  assert.equal(await closeups.route({ reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320] }), null);
  assert.equal(asked.length, 0);
  const context = closeups.context();
  assert.equal(context.aligned[0].sharper, 1.1);
  assert.match(context.aligned[0].status, /not sharper/);
}, { answers: { woman: { ...PLACED, scale: 1.1, matrix: [1 / 1.1, 0, 300, 0, 1 / 1.1, 600, 0, 0, 1] } } }));

test('the painter’s context lists the areas with a close-up and the elements without one', () => chat(async ({ closeups }) => {
  assert.equal(closeups.context(), undefined, 'nothing aligned yet');
  await closeups.refresh();
  closeups.answer('woman', CLOSEUP_ANSWERS[0]);
  const context = closeups.context();
  assert.deepEqual(context.aligned, [{ reference_id: 'woman', name: '11-woman-back-view.png', area: 'Woman back view', goal_box: [300, 600, 250, 240], sharper: 4, status: 'confirmed by the artist' }]);
  assert.deepEqual(context.could_not_align, ['01-moonlit-sky.png']);
  assert.match(context.note, /Woman back view: 11-woman-back-view\.png, about 4x sharper/);
}, { answers: { woman: PLACED } }));

test('mapSource keeps the target’s proportions and stays inside the close-up', () => {
  const record = { ...PLACED, closeup_size: [1000, 960] };
  assert.deepEqual(mapSource(record, [350, 640, 100, 80], [0, 0, 415, 332]), [200, 160, 400, 320]);
  assert.equal(mapSource(record, [290, 640, 100, 80], [0, 0, 415, 332]), null, 'starts left of the close-up');
  const odd = mapSource(record, [301, 601, 77, 51], [0, 0, 693, 459]);
  assert.ok(Math.abs(odd[3] * 693 / odd[2] - 459) <= 1, 'same aspect within a target pixel');
  assert.ok(odd[0] >= 0 && odd[1] >= 0 && odd[0] + odd[2] <= 1000 && odd[1] + odd[3] <= 960);
  assert.ok(MIN_SHARPER > 1);
});

test('a detail transfer from the goal samples the confirmed close-up, says so, and replays under the same ID', () => chat(async ({ host, closeups, directory }) => {
  await closeups.refresh(); closeups.answer('woman', CLOSEUP_ANSWERS[0]);
  const decoded = [];
  const image = edgeImage;
  const runtime = { config: { reference_batch: 4096 }, mode: 'agent', executionPhase: 'agent', study: host.study, decisionObservation: { width: 6000, height: 4500, revision: 'r0' },
    emit() {}, closeups,
    async callNative(op, p) {
      if (op === 'decode_reference') { const ref = host.study.references.find(r => r.sha === p.sha256); decoded.push(ref.id); return { ...image(ref.width, ref.height), sha256: p.sha256 }; }
      if (op === 'observe') return { width: 6000, height: 4500, revision: 'r0' };
      throw new Error(op);
    } };
  const execute = async () => ({ details: { status: 'ok', revision: 'r1', layer_id: 'l1' } });
  const tools = referenceTools(runtime, execute, null);
  const edges = tools.find(t => t.name === 'paint_reference_edges');
  const args = { name: 'Hair edges', reference_id: 'goal', preset: 'b) Basic-6 Details', source: [350, 640, 100, 80], target: [1450, 2650, 415, 332] };
  const result = await edges.execute('hair-edges', args);
  assert.deepEqual(decoded, ['woman']);
  assert.match(result.details.closeup, /11-woman-back-view\.png/);
  const job = JSON.parse(await readFile(join(directory, 'reference-paintings', result.details.job_id + '.json'), 'utf8'));
  assert.equal(job.recipe.reference_id, 'woman');
  assert.deepEqual(job.recipe.source, [200, 160, 400, 320]);
  assert.equal(job.requested.reference_id, 'goal', 'what the painter asked is kept');
  await edges.execute('hair-edges', args);                                                 // a replay is not "reused with different instructions"
}, { answers: { woman: PLACED } }));

test('before the artist has confirmed, the transfer samples the goal at once and the question waits beside the run', () => chat(async ({ host, closeups, asked }) => {
  const decoded = [];
  const runtime = { config: { reference_batch: 4096 }, mode: 'agent', executionPhase: 'agent', study: host.study, decisionObservation: { width: 6000, height: 4500, revision: 'r0' }, emit() {}, closeups,
    async callNative(op, p) {
      if (op === 'decode_reference') { const ref = host.study.references.find(r => r.sha === p.sha256); decoded.push(ref.id); return { ...edgeImage(ref.width, ref.height, 400), sha256: p.sha256 }; }
      if (op === 'observe') return { width: 6000, height: 4500, revision: 'r0' };
      throw new Error(op);
    } };
  const tools = referenceTools(runtime, async () => ({ details: { status: 'ok', revision: 'r1', layer_id: 'l1' } }), null);
  const result = await tools.find(t => t.name === 'paint_reference_edges').execute('hair', { name: 'Hair', reference_id: 'goal', preset: 'b) Basic-6 Details', source: [350, 640, 100, 80], target: [1450, 2650, 415, 332] });
  assert.equal(result.details.status, 'complete');
  assert.deepEqual(decoded, ['goal']);
  assert.equal(asked.length, 1);
}, { answers: { woman: PLACED } }));

test('a plugin without align_closeup is asked once', () => chat(async ({ host, closeups, calls }) => {
  host.callNative = async (operation, params) => { calls.push({ operation, params }); throw new Error('Unsupported creative operation'); };
  await closeups.refresh(); await closeups.refresh();
  assert.equal(calls.length, 1, 'an older plugin: no more calls this session');
  assert.deepEqual(host.study.closeups ?? {}, {});
  assert.equal(closeups.context(), undefined);
}));

test('a transient failure is not recorded and is not retried in the same chat; a refusal is recorded by content', () => chat(async ({ host, closeups, calls }) => {
  host.callNative = async (operation, params) => {
    calls.push({ operation });
    if (params.closeup.sha256 === host.study.references[1].sha) throw new Error('Krita is busy');
    throw Object.assign(new Error('ValueError: The closeup image must be a PNG or JPEG.'), { code: 'validation_rejected' });
  };
  await closeups.refresh(); await closeups.refresh();
  assert.equal(calls.length, 2, 'each tried once in this chat');
  assert.equal(host.study.closeups.woman, undefined, 'the busy one is not recorded');
  assert.equal(host.study.closeups.sky.aligned, false);
  assert.equal(host.study.closeups.sky.reason, 'The closeup image must be a PNG or JPEG.');
}));

test('unchanged files are not read or hashed again on each refresh', () => chat(async ({ host, closeups, references }) => {
  await closeups.refresh();
  const reads = host.reads;
  await closeups.refresh();
  assert.equal(host.reads, reads, 'size and modification time unchanged: nothing read');
  await writeFile(references[1].path, 'woman pixels, retouched'); references[1].sha = sha('woman pixels, retouched');
  const later = new Date(Date.now() + 5000); await utimes(references[1].path, later, later);
  await closeups.refresh();
  assert.ok(host.reads > reads);
}));

test('focal regions and source-pixel sizes follow the source into the close-up', () => chat(async ({ closeups }) => {
  await closeups.refresh(); closeups.answer('woman', CLOSEUP_ANSWERS[0]);
  const used = await closeups.route({ reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320], focal_regions: [[360, 650, 20, 20], [440, 700, 20, 30]], steps: [6, 2.5, 1.2] });
  assert.deepEqual(used.recipe.focal_regions, [[240, 200, 80, 80], [560, 400, 40, 80]], 'mapped, and the second clamped inside the mapped source');
  assert.deepEqual(used.recipe.steps, [24, 10, 4.8], 'the painter\u2019s steps were in goal pixels');
  const edges = await closeups.route({ reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320], spacing: 1.5, mode: 'edges' });
  assert.equal(edges.recipe.spacing, 6);
  const outside = await closeups.route({ reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320], focal_regions: [[460, 730, 20, 20]] });
  assert.equal(outside, null, 'a focal region that cannot fit: the goal is sampled');
}, { answers: { woman: PLACED } }));

test('a close-up the transfer cannot read (over 64 MB, over 26 million pixels, a source past 8192) is not used', () => chat(async ({ closeups, host }) => {
  await closeups.refresh(); closeups.answer('woman', CLOSEUP_ANSWERS[0]);
  const recipe = { reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320] };
  host.study.closeups.woman.bytes = 65 * 1024 * 1024;
  assert.equal(await closeups.route(recipe), null, 'over 64 MB');
  host.study.closeups.woman.bytes = 1000; host.study.closeups.woman.closeup_size = [6000, 4400];
  assert.equal(await closeups.route(recipe), null, 'over 26 million pixels');
  host.study.closeups.woman.closeup_size = [1000, 960];
  assert.ok(await closeups.route(recipe));
}, { answers: { woman: PLACED } }));

test('a removed close-up is no longer used, listed or answered, and its record goes', () => chat(async ({ closeups, host }) => {
  await closeups.refresh(); closeups.answer('woman', CLOSEUP_ANSWERS[0]);
  host.study.references = host.study.references.filter(r => r.id !== 'woman');
  assert.equal(await closeups.route({ reference_id: 'goal', source: [350, 640, 100, 80], target: [0, 0, 400, 320] }), null);
  assert.deepEqual(closeups.context().aligned, []);
  assert.equal(closeups.answer('woman', CLOSEUP_ANSWERS[0]), false);
  closeups.forget('woman');
  assert.equal(host.study.closeups.woman, undefined);
}, { answers: { woman: PLACED } }));

test('mapSource refuses a stretched alignment: the close-up would paint the area squashed', () => {
  const stretched = { ...PLACED, matrix: [0.25, 0, 300, 0, 0.3, 600, 0, 0, 1], closeup_size: [1000, 960] };
  assert.equal(mapSource(stretched, [350, 640, 100, 80], [0, 0, 400, 320]), null);
});
