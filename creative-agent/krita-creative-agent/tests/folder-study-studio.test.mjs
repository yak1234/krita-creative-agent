// Folder study in a chat (studio.mjs hooks and folder-study-chat.ts; the study itself is tested in folder-study.test.mjs):
// a small folder is studied when it is attached and its notes are the painter's context; Off is file names only; a big
// folder asks first and remembers the choice; Exclude keeps an image from every model; view_reference studies an image
// with no note; the planning turn waits for a study in progress. A local model server, a fake bridge and a fake study
// reader, as studio.test.mjs; every file goes to a temporary folder and the artist's folder is never written.
import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { StudioRuntime } from '../src/studio.mjs';
import { encodeRgba } from '../src/shapes/png.ts';
import { STUDY_FILE } from '../src/folder-study.ts';
import { boundedPicture } from '../src/folder-study-chat.ts';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64');
const call = (name, args) => ({ tool_calls: [{ index: 0, id: 'call-' + Math.random().toString(36).slice(2), type: 'function', function: { name, arguments: JSON.stringify(args) } }] });
/** A small PNG of one colour per image, so every image has its own content hash. */
const picture = i => encodeRgba({ width: 4, height: 3, data: new Uint8Array(4 * 3 * 4).map((_, k) => k % 4 === 3 ? 255 : (i * 37 + k) % 256) });
const noteFor = name => `The image ${name} shows a quiet winter street at night, with warm amber windows, deep blue shadows on the snow and a soft glow along the lamps. In the goal it sits in the lower third.`;

async function harness(respond, { studyReader, studyModel } = {}) {
  const output = await mkdtemp(join(tmpdir(), 'folder-study-studio-'));
  const requests = [], calls = [], events = [];
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const request = JSON.parse(body); requests.push(request);
    const delta = await respond(request, requests.length);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const choice of [{ delta: { role: 'assistant', ...delta }, finish_reason: null }, { delta: {}, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }])
      res.write('data: ' + JSON.stringify({ id: 'reply', object: 'chat.completion.chunk', created: 1, model: 'vision-test', choices: [{ index: 0, ...choice }] }) + '\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const models = await ModelRuntime.create({ authPath: join(output, 'auth.json'), modelsPath: null, refreshOnCreate: false });
  models.registerProvider('local-test', { api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1`, models: [{ id: 'vision-test', name: 'Test', reasoning: false, input: ['text', 'image'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 4096 }] });
  await models.setRuntimeApiKey('local-test', 'test-only');
  let observation;
  const bridge = { async call(operation, params) {
    calls.push({ operation, params });
    if (operation === 'context') return { document_id: 'doc', active_document_id: 'doc', name: 'Untitled', filename: '', width: 768, height: 1024, modified: true, revision: 'revision-0' };
    if (['begin', 'peek'].includes(operation)) {
      const path = join(params.output_dir, 'view.png'); await writeFile(path, png);
      observation = { status: 'ok', document_id: 'doc', name: 'Untitled', filename: '', modified: true, width: 768, height: 1024, image_path: path, layers: [], revision: 'revision-0', content_id: 'content-0', captured_at: new Date().toISOString() };
    }
    return operation === 'end' ? { status: 'ok' } : observation;
  } };
  const capabilities = { async initialize() {}, status() { return { status: 'verified', route_verified: true, images_supported: true, tools_supported: true }; }, async verify() { return { route_verified: true, cached: true }; }, async invalidate() {} };
  const runtime = new StudioRuntime({defaultPlanner:null, root: output, config: { output }, models, bridge, capabilities, tracing: recordingTracing(), emit: e => events.push(e), studyReader, studyModel });
  return { runtime, requests, calls, events, output,
    start: (mode, prompt = 'Hello') => runtime.start({ provider: 'local-test', model: 'vision-test', chat_mode: mode, prompt, mode: 'copy' }),
    async close() { if (runtime.busy) runtime.stop(); await runtime.writeQueue; await runtime.end().catch(() => {}); runtime.dispose(); server.closeAllConnections(); await new Promise(r => server.close(r)); await rm(output, { recursive: true, force: true }); } };
}

/** A fake study reader: one note per image (named in the prompt), counting what it was sent. */
function reader({ delay = 0, fail = () => false } = {}) {
  const asked = [];
  const read = async request => {
    const name = /IMAGE is (?:the goal image of a painting project \(|an element image of a painting project, )([^\s()"]+)/.exec(request.prompt)?.[1] ?? 'unknown';
    asked.push({ name, images: request.images.length });
    if (delay) await new Promise(resolve => setTimeout(resolve, delay));
    if (fail(name)) throw new Error('provider said no');
    return { text: noteFor(name), cost: 0.001, model: 'local-test/vision-test' };
  };
  return { asked, read };
}

async function projectFolder(count = 3) {
  const root = await mkdtemp(join(tmpdir(), 'folder-study-project-'));
  await writeFile(join(root, 'final_goal.png'), picture(0));
  await mkdir(join(root, 'assets'));
  for (let i = 1; i <= count; i++) await writeFile(join(root, 'assets', `${String(i).padStart(2, '0')}-part-${i}.png`), picture(i));
  return root;
}
const snapshot = async root => JSON.stringify(await Promise.all((await readdir(root, { recursive: true })).sort().map(async name => [name, (await readFile(join(root, name)).catch(() => Buffer.from('dir'))).toString('base64')])));
const context = h => JSON.parse(h.runtime.context('agent').split('\n').find(line => line.startsWith('{')));
const lastStudy = h => h.events.filter(e => e.type === 'folder').at(-1)?.study;
const settle = async h => { while (h.runtime.folderStudy.running()) await h.runtime.folderStudy.running(); };

test('a small folder is studied when it is attached: a note per image in the painter\'s context, progress on the folder card, nothing in the artist\'s folder', { timeout: 30000 }, async () => {
  const { asked, read } = reader();
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(3);
  try {
    await h.start('ask');
    const before = await snapshot(root);
    await h.runtime.openFolder({ path: root });
    await settle(h);
    assert.deepEqual(asked.map(a => a.name).sort(), ['assets/01-part-1.png', 'assets/02-part-2.png', 'assets/03-part-3.png', 'final_goal.png']);
    assert.deepEqual(asked.map(a => a.images).sort(), [1, 2, 2, 2], 'the goal alone; an element with the goal');
    const folder = context(h).folder;
    assert.equal(folder.goal.note, noteFor('final_goal.png'));
    assert.deepEqual(folder.elements.map(e => e.note), folder.elements.map(e => noteFor(e.name)));
    assert.match(folder.notes, /view_reference/, 'the painter is told to read the notes and open an image only when needed');
    const study = lastStudy(h);
    assert.equal(study.enabled, true); assert.equal(study.state, 'done'); assert.equal(study.count, 4);
    assert.deepEqual([study.done, study.total], [4, 4]);
    assert.ok(Object.values(study.images).every(s => s === 'studied'));
    assert.ok(h.events.some(e => e.type === 'folder' && e.study?.state === 'running'), 'the card showed the run');
    const saved = JSON.parse(await readFile(join(h.runtime.study.directory, STUDY_FILE), 'utf8'));
    assert.equal(Object.keys(saved.notes).length, 4, 'kept in the chat\'s own data folder');
    assert.equal(await snapshot(root), before, 'nothing is written into the artist\'s folder');
    // Opening it again studies nothing again.
    await h.runtime.openFolder({ path: root }); await settle(h);
    assert.equal(asked.length, 4);
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('Study folder images Off: no study, file names only', { timeout: 30000 }, async () => {
  const { asked, read } = reader();
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(2);
  try {
    await h.start('ask');
    await h.runtime.setExecutionSettings({ study_folder: false });
    await h.runtime.openFolder({ path: root }); await settle(h);
    assert.equal(asked.length, 0);
    const folder = context(h).folder;
    assert.ok(!('note' in folder.goal) && folder.elements.every(e => !('note' in e)) && !('notes' in folder));
    assert.equal(lastStudy(h).enabled, false);
    // Turned On again: the open folder is studied then.
    await h.runtime.setExecutionSettings({ study_folder: true }); await settle(h);
    assert.equal(asked.length, 3);
    assert.equal(lastStudy(h).state, 'done');
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('a folder of more than 20 images asks first; the choice is remembered for the folder; Let me pick studies the picked; Stop ends a run', { timeout: 30000 }, async () => {
  const { asked, read } = reader({ delay: 20 });
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(21);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root }); await settle(h);
    assert.equal(asked.length, 0, 'nothing is studied before the artist chooses');
    let study = lastStudy(h);
    assert.equal(study.needs_choice, true); assert.equal(study.count, 22);
    assert.equal(study.estimate.all.images, 22); assert.ok(study.estimate.plan.images >= 1 && study.estimate.plan.cost > 0);
    await h.runtime.folderStudyCommand({ action: 'choose', choice: 'pick', picked: ['assets/03-part-3.png', 'assets/07-part-7.png'] });
    await settle(h);
    assert.deepEqual(asked.map(a => a.name).sort(), ['assets/03-part-3.png', 'assets/07-part-7.png']);
    study = lastStudy(h);
    assert.equal(study.choice, 'pick'); assert.equal(study.needs_choice, false);
    assert.equal(study.images['assets/03-part-3.png'], 'studied'); assert.equal(study.images['assets/01-part-1.png'], 'not_studied');
    assert.deepEqual(h.runtime.study.folder.study.picked, ['assets/03-part-3.png', 'assets/07-part-7.png'], 'remembered with the chat\'s folder');
    // Study all, stopped at once: what was studied stays, the rest is not studied.
    await h.runtime.folderStudyCommand({ action: 'choose', choice: 'all' });
    await new Promise(resolve => setTimeout(resolve, 30));
    await h.runtime.folderStudyCommand({ action: 'stop' });
    await settle(h);
    study = lastStudy(h);
    assert.equal(study.state, 'stopped');
    assert.ok(asked.length < 22, `asked ${asked.length}`);
    // Don't study: nothing more.
    await h.runtime.folderStudyCommand({ action: 'choose', choice: 'none' });
    const count = asked.length; await settle(h);
    assert.equal(asked.length, count);
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('Only what the plan uses: the goal now, the plan\'s images once a plan names them, the rest when the agent opens one (view_reference)', { timeout: 30000 }, async () => {
  const { asked, read } = reader();
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(21);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root }); await settle(h);
    await h.runtime.folderStudyCommand({ action: 'choose', choice: 'plan' }); await settle(h);
    assert.deepEqual(asked.map(a => a.name), ['final_goal.png']);
    await h.runtime.editPlan({ title: 'Plan', objective: 'Paint it.', requirements: [], freedom: [], completion: ['Done.'],
      steps: [{ title: 'Underpainting from the goal image', done_when: 'Laid in.', scope: 'whole composition' },
        { title: 'Refine: part 5', done_when: 'Refined.', scope: 'whole composition', kind: 'refine_part', parts: ['assets/05-part-5.png'] },
        { title: 'Part 9', done_when: 'Painted.', scope: 'assets/09-part-9.png' }] });
    await h.runtime.folderStudy.planChanged(); await settle(h);
    assert.deepEqual(asked.map(a => a.name).sort(), ['assets/05-part-5.png', 'assets/09-part-9.png', 'final_goal.png']);
    // The agent opens an element that has no note: it is studied then.
    const view = h.runtime.buildTools().find(t => t.name === 'view_reference');
    const ref = h.runtime.study.references.find(r => r.folder_name === 'assets/12-part-12.png');
    const result = await view.execute('id', { id: ref.id });
    assert.equal(result.content[1].type, 'image');
    await settle(h); await h.runtime.folderStudy.idle();
    assert.ok(asked.some(a => a.name === 'assets/12-part-12.png'), 'studied when opened');
    assert.equal(context(h).folder.elements.find(e => e.name === 'assets/12-part-12.png').note, noteFor('assets/12-part-12.png'));
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('an excluded image is never sent to any model: not attached, not studied, listed as excluded; Include attaches it again; the goal cannot be excluded', { timeout: 30000 }, async () => {
  const { asked, read } = reader();
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(3);
  try {
    await h.start('ask');
    await h.runtime.setExecutionSettings({ study_folder: false });
    await h.runtime.openFolder({ path: root });
    await h.runtime.folderStudyCommand({ action: 'exclude', name: 'assets/02-part-2.png' });
    assert.ok(!h.runtime.study.references.some(r => r.folder_name === 'assets/02-part-2.png'), 'detached: no model is sent it');
    await h.runtime.setExecutionSettings({ study_folder: true });
    await h.runtime.openFolder({ path: root }); await settle(h);
    assert.ok(!asked.some(a => a.name === 'assets/02-part-2.png'), 'never studied');
    assert.ok(!h.runtime.study.references.some(r => r.folder_name === 'assets/02-part-2.png'), 'opening the folder again does not attach it');
    const element = context(h).folder.elements.find(e => e.name === 'assets/02-part-2.png');
    assert.equal(element.excluded, true); assert.equal(element.reference_id, null); assert.ok(!('note' in element));
    assert.equal(lastStudy(h).images['assets/02-part-2.png'], 'excluded');
    assert.deepEqual(h.runtime.study.folder.study.excluded, ['assets/02-part-2.png']);
    await assert.rejects(h.runtime.folderStudyCommand({ action: 'exclude', name: 'final_goal.png' }), /goal image/);
    // An excluded element made the goal is the goal: attached and studied, never listed as excluded.
    await h.runtime.setFolderGoal({ name: 'assets/02-part-2.png' }); await settle(h);
    assert.ok(h.runtime.study.references.some(r => r.folder_name === 'assets/02-part-2.png' && r.role === 'reference'), 'the goal is attached');
    assert.equal(context(h).folder.goal.name, 'assets/02-part-2.png'); assert.ok(!('excluded' in context(h).folder.goal));
    assert.notEqual(lastStudy(h).images['assets/02-part-2.png'], 'excluded');
    await h.runtime.setFolderGoal({ name: 'final_goal.png' }); await settle(h);
    assert.ok(!h.runtime.study.references.some(r => r.folder_name === 'assets/02-part-2.png'), 'back to an element: excluded again');
    await assert.rejects(h.runtime.folderStudyCommand({ action: 'exclude', name: 'elsewhere.png' }), /not an image of the project folder/);
    await h.runtime.folderStudyCommand({ action: 'include', name: 'assets/02-part-2.png' }); await settle(h);
    assert.ok(h.runtime.study.references.some(r => r.folder_name === 'assets/02-part-2.png'), 'attached again');
    assert.ok(asked.some(a => a.name === 'assets/02-part-2.png'), 'a small folder studies it once it is included');
    // Study from the menu: one image again (here already studied: no request).
    const count = asked.length;
    await h.runtime.folderStudyCommand({ action: 'study', name: 'assets/02-part-2.png' }); await settle(h);
    assert.equal(asked.length, count);
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('the folder\'s planning turn waits for the study in progress, so the planner reads the notes', { timeout: 30000 }, async () => {
  const { read } = reader({ delay: 400 });
  let planning = null;
  const h = await harness(request => {
    if (request.tools?.some(t => t.function.name === 'propose_plan') && !planning) { planning = request; return { content: 'Here is the plan.' }; }
    return { content: 'ok' };
  }, { studyReader: read });
  const root = await projectFolder(3);
  try {
    await h.start('ask');
    h.runtime.goalSharpen.gate = async () => 'paint';
    await h.runtime.openFolder({ path: root });
    await h.runtime.setMode('agent');
    await h.runtime.prompt('Paint the underpainting.');
    assert.ok(planning, 'a planning turn ran');
    assert.ok(JSON.stringify(planning.messages).includes(noteFor('assets/03-part-3.png').slice(0, 60)), 'the planner read the notes');
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('boundedPicture: a PNG over the side is reduced to it (long side), a small one or one it cannot read is sent as it is', async () => {
  const big = encodeRgba({ width: 300, height: 100, data: new Uint8Array(300 * 100 * 4).fill(200) });
  const reduced = await boundedPicture(big, 120);
  const { pngSize } = await import('../src/png-rgba.ts');
  const size = pngSize(Buffer.from(reduced.data, 'base64'));
  assert.ok(size.width <= 120 && size.width >= 118 && size.height <= 40, JSON.stringify(size));
  assert.equal(reduced.mimeType, 'image/png');
  assert.equal((await boundedPicture(png, 120)).data, png.toString('base64'));
  const jpeg = Buffer.from([255, 216, 255, 224, 0, 16]);
  assert.deepEqual(await boundedPicture(jpeg, 120), { data: jpeg.toString('base64'), mimeType: 'image/jpeg' });
});

// Review findings (2026-10-24).
test('an excluded element is out of the plan: not offered, not grouped, not planned; its element step is refused, never painted as the whole picture', { timeout: 30000 }, async () => {
  const { read } = reader();
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(3);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root }); await settle(h);
    await h.runtime.folderStudyCommand({ action: 'exclude', name: 'assets/02-part-2.png' });
    assert.deepEqual(h.runtime.folderElements().map(e => e.name), ['assets/01-part-1.png', 'assets/03-part-3.png']);
    assert.ok(!JSON.stringify(h.runtime.folderPlanDraft().steps).includes('02-part-2'), 'no refine group holds it');
    assert.ok(!h.runtime.elementsToOffer().some(name => /part 2/i.test(name)));
    assert.match(context(h).folder.excluded_images, /never plan/i, 'the planner is told');
    await h.runtime.editPlan({ title: 'Plan', objective: 'Paint it.', requirements: [], freedom: [], completion: ['Done.'],
      steps: [{ title: 'Part 2', done_when: 'Painted.', scope: 'assets/02-part-2.png' }] });
    assert.throws(() => h.runtime.folderMoveInstructions({ step: 0 }), /part 2.* is excluded: include it or skip the step/i);
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('Stop sticks: a settings save or reopening the folder starts nothing; a failure is not asked again until the image is opened; a choice or turning the setting On again resumes', { timeout: 30000 }, async () => {
  const { asked, read } = reader({ delay: 30, fail: name => name === 'assets/01-part-1.png' });
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(8);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root });
    await new Promise(resolve => setTimeout(resolve, 10));
    await h.runtime.folderStudyCommand({ action: 'stop' }); await settle(h);
    const count = asked.length;
    assert.ok(count < 9, `asked ${count}`);
    assert.equal(lastStudy(h).stopped, true);
    await h.runtime.setExecutionSettings({ move_size: 'quick' }); await settle(h);
    await h.runtime.openFolder({ path: root }); await settle(h);
    assert.equal(asked.length, count, 'nothing started again');
    await h.runtime.setExecutionSettings({ study_folder: false });
    await h.runtime.setExecutionSettings({ study_folder: true }); await settle(h); await h.runtime.folderStudy.idle();
    assert.equal(lastStudy(h).stopped, false);
    const failing = () => asked.filter(a => a.name === 'assets/01-part-1.png').length, once = failing();
    assert.ok(once >= 1); assert.equal(lastStudy(h).failed, 1);
    await h.runtime.openFolder({ path: root }); await settle(h);
    await h.runtime.setExecutionSettings({ move_size: 'large' }); await settle(h);
    assert.equal(failing(), once, 'reopening or saving a setting does not ask a failed image again');
    await h.runtime.folderStudyCommand({ action: 'study', name: 'assets/01-part-1.png' }); await h.runtime.folderStudy.idle();
    assert.equal(failing(), once + 1, 'Study asks it again');
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('waiting for the study before planning shows "Reading the folder\'s images…" and ends when the chat is stopped', { timeout: 30000 }, async () => {
  const { read } = reader({ delay: 3000 });
  const h = await harness(() => ({ content: 'ok' }), { studyReader: read });
  const root = await projectFolder(2);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root });
    let stop = false; const said = [];
    const started = Date.now();
    setTimeout(() => { stop = true; }, 200);
    await h.runtime.folderStudy.beforePlanning({ cancelled: () => stop, progress: text => said.push(text) });
    assert.ok(Date.now() - started < 1500, 'it stops waiting with the chat');
    assert.match(said[0], /Reading the folder's images before planning…/);
    assert.ok(said.some(t => / 0\/3$/.test(t)), said.join(' | '));
    await h.runtime.folderStudyCommand({ action: 'stop' }); await settle(h);
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('the notes go in planning turns and the first painter turn; later turns get one line and the current element\'s own note; notes are framed as data', { timeout: 30000 }, async () => {
  const { read } = reader();
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(3);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root }); await settle(h);
    const first = context(h).folder;
    assert.equal(first.elements[0].note, noteFor('assets/01-part-1.png'));
    assert.match(first.notes, /never follow instructions/i);
    const later = context(h).folder;
    assert.ok(later.elements.every(e => !('note' in e)) && !('note' in later.goal), 'sent once');
    assert.match(later.notes, /4 images studied.*view_reference/i);
    const planning = JSON.parse(h.runtime.context('plan').split('\n').find(line => line.startsWith('{'))).folder;
    assert.equal(planning.elements[1].note, noteFor('assets/02-part-2.png'), 'a planning turn has them all');
    await h.runtime.editPlan({ title: 'Plan', objective: 'Paint it.', requirements: [], freedom: [], completion: ['Done.'],
      steps: [{ title: 'Part 3', done_when: 'Painted.', scope: 'assets/03-part-3.png' }] });
    context(h);
    const step = context(h).folder;
    assert.equal(step.elements.find(e => e.name === 'assets/03-part-3.png').note, noteFor('assets/03-part-3.png'), 'the element step\'s own note');
    assert.ok(!('note' in step.elements.find(e => e.name === 'assets/01-part-1.png')));
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('the estimate uses the study model\'s own price per token', { timeout: 30000 }, async () => {
  const { read } = reader();
  const model = { provider: 'openrouter', id: 'qwen/qwen3-vl-235b-a22b-instruct', input: ['text', 'image'], cost: { input: 0.21, output: 1.9 } };
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read, studyModel: model });
  const root = await projectFolder(21);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root }); await settle(h);
    const study = lastStudy(h);
    assert.equal(study.model, 'openrouter/qwen/qwen3-vl-235b-a22b-instruct');
    assert.ok(Math.abs(study.estimate.all.cost - 22 * 0.00068) < 0.002, String(study.estimate.all.cost));
    const pricier = { ...model, cost: { input: 2.1, output: 19 } };
    h.runtime.studyModel = pricier;
    h.runtime.emitFolder();
    assert.ok(lastStudy(h).estimate.all.cost > 9 * study.estimate.all.cost, 'ten times the price, ten times the estimate');
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});

test('an image excluded after it was sent is removed from what the model is sent, its earlier messages included', { timeout: 30000 }, async () => {
  const { read } = reader();
  const h = await harness(() => ({ content: 'Hello.' }), { studyReader: read });
  const root = await projectFolder(2);
  try {
    await h.start('ask');
    await h.runtime.openFolder({ path: root }); await settle(h);
    const view = h.runtime.buildTools().find(t => t.name === 'view_reference');
    const ref = h.runtime.study.references.find(r => r.folder_name === 'assets/02-part-2.png');
    const shown = (await view.execute('id', { id: ref.id })).content[1];
    const keep = (await view.execute('id', { id: h.runtime.study.references.find(r => r.folder_name === 'assets/01-part-1.png').id })).content[1];
    const history = [{ role: 'toolResult', content: [{ type: 'text', text: 'x' }, shown] }, { role: 'toolResult', content: [keep] }];
    const transform = h.runtime.session.agent.transformContext;
    assert.equal((await transform(history)).flatMap(m => m.content).filter(p => p.type === 'image').length, 2, 'before: both');
    await h.runtime.folderStudyCommand({ action: 'exclude', name: 'assets/02-part-2.png' });
    const after = await transform(history);
    const images = after.flatMap(m => m.content).filter(p => p.type === 'image');
    assert.equal(images.length, 1); assert.equal(images[0].data, keep.data);
    assert.match(JSON.stringify(after), /excluded/);
  } finally { await h.close(); await rm(root, { recursive: true, force: true }); }
});
