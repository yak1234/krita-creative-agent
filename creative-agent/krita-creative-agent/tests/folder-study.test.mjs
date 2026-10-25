// Folder study (folder-study.ts, openspec folder-study): a vision model writes a short note per folder image, kept in the
// chat's data folder by the image's content hash; 4 images at a time, a timeout and a failure per image, Stop, the lazy
// study of one image, and the choice for a big folder. The model is a fake reader; every file goes to a temporary folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { FolderStudy, studyTargets, studyEstimate, cleanNote, studyPrompt, piReader, studyModelRoute, SMALL_FOLDER, STUDY_CONCURRENCY,
  STUDY_FILE, STUDY_SIDE, STUDY_MODEL } from '../src/folder-study.ts';

const words = n => Array.from({ length: n }, (_, i) => 'word' + i).join(' ') + '.';
const NOTE = 'A moonlit sky over the city, deep blue at the top fading to a pale band at the horizon, with a full moon in the upper right and thin clouds lit silver around it. In the goal it fills the top third of the picture.';
const sha = data => createHash('sha256').update(data).digest('hex');

async function folder(names = ['final_goal.png', '01-moonlit-sky.png', '02-historic-buildings.png', '03-domed-church.png']) {
  const root = await mkdtemp(join(tmpdir(), 'folder-study-'));
  const chat = join(root, 'chat'), images = [];
  await writeFile(join(root, 'marker'), '');
  await (await import('node:fs/promises')).mkdir(chat);
  for (const [i, name] of names.entries()) {
    const path = join(root, name); await writeFile(path, Buffer.from('image ' + name));
    images.push({ name, path, role: i === 0 ? 'goal' : 'element', guess: i === 0 ? 'Goal image' : name.replace(/^\d+-|\.png$/g, '').replace(/-/g, ' ') });
  }
  return { root, chat, images, goal: images[0], close: () => rm(root, { recursive: true, force: true }) };
}

/** A fake host: the reader answers with a note (or what `answer` gives), counting calls and the most at once. */
function host(chat, { answer = () => NOTE, delay = 5 } = {}) {
  const seen = { calls: [], running: 0, most: 0, events: [], changed: 0, reads: 0, pictures: [] };
  const reader = async request => {
    seen.calls.push(request); seen.running++; seen.most = Math.max(seen.most, seen.running);
    try {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, delay);
        request.signal.addEventListener('abort', () => { clearTimeout(timer); reject(request.signal.reason ?? new Error('aborted')); }, { once: true });
      });
      const text = await answer(request);
      return { text, cost: 0.0008, model: 'openrouter/test-vision' };
    } finally { seen.running--; }
  };
  return { seen, host: { directory: () => chat, readImage: async path => { seen.reads++; return readFile(path); },
    picture: async (path, data, side) => { seen.pictures.push({ path, side }); return { data: data.toString('base64'), mimeType: 'image/png', side }; },
    reader: async () => reader, changed: () => { seen.changed++; }, record: event => seen.events.push(event) } };
}

test('studyTargets: a small folder studies every image not excluded; a big one waits for the choice, then the plan\'s images, all, the picked or none', () => {
  const names = n => ['goal.png', ...Array.from({ length: n - 1 }, (_, i) => `${String(i + 1).padStart(2, '0')}-e.png`)];
  const small = names(SMALL_FOLDER);
  assert.deepEqual(studyTargets(small, { excluded: ['01-e.png'] }), small.filter(n => n !== '01-e.png'));
  const big = names(SMALL_FOLDER + 1);
  assert.equal(studyTargets(big, {}), null, 'more than 20 images: the card asks first');
  assert.deepEqual(studyTargets(big, { choice: 'plan', goal: 'goal.png', planFiles: ['03-e.png', 'missing.png'] }), ['goal.png', '03-e.png']);
  assert.deepEqual(studyTargets(big, { choice: 'all', excluded: ['goal.png'] }), big.slice(1));
  assert.deepEqual(studyTargets(big, { choice: 'pick', picked: ['05-e.png', '02-e.png'], excluded: ['02-e.png'] }), ['05-e.png']);
  assert.deepEqual(studyTargets(big, { choice: 'none' }), []);
});

test('studyEstimate: cost and time for n images, 4 at a time; measured averages win over the defaults', () => {
  const e = studyEstimate(9);
  assert.equal(e.images, 9);
  assert.ok(e.cost > 0 && e.seconds > 0);
  assert.deepEqual(studyEstimate(9, { cost: 0.001, seconds: 10 }), { images: 9, cost: 0.009, seconds: 30 }, 'ceil(9 / 4) rounds of 10 s');
  assert.deepEqual(studyEstimate(0), { images: 0, cost: 0, seconds: 0 });
});

test('cleanNote keeps plain prose of a useful length: markup and a preamble go, a long note is cut at a sentence, an empty one is refused', () => {
  assert.equal(cleanNote('**Note:** ' + NOTE), NOTE);
  assert.equal(cleanNote('- one\n- ' + NOTE), 'one ' + NOTE);
  assert.equal(cleanNote('Too short.'), null);
  const long = cleanNote(Array.from({ length: 30 }, () => 'This sentence has exactly seven words here.').join(' '));
  assert.ok(long.split(/\s+/).length <= 160 && long.endsWith('.'), long);
  assert.equal(cleanNote(''), null);
});

test('studyPrompt asks for what the image shows, its place in the goal (for an element), its colours, shapes and details, in 60-120 words', () => {
  const goal = studyPrompt({ name: 'final_goal.png', role: 'goal', guess: 'Goal image' }, { goal: false });
  assert.match(goal, /goal image/i); assert.match(goal, /60-120 words/); assert.doesNotMatch(goal, /where it sits/i);
  const element = studyPrompt({ name: '04-kremlin-towers.png', role: 'element', guess: 'Kremlin towers', prompt: 'Red brick towers at night' }, { goal: true });
  assert.match(element, /Kremlin towers/); assert.match(element, /where it sits in the goal/i); assert.match(element, /colours/);
  assert.match(element, /Red brick towers at night/, 'the folder\'s generation prompt is a hint');
  assert.doesNotMatch(studyPrompt({ name: 'x.png', role: 'element', guess: 'X' }, { goal: false }), /where it sits in the goal/i, 'no goal: no position');
});

test('a study writes one note per image, at most 4 requests at once, kept in the chat folder by content hash; the progress counts', async () => {
  const f = await folder(['final_goal.png', ...Array.from({ length: 9 }, (_, i) => `0${i + 1}-part.png`)]);
  const { seen, host: h } = host(f.chat);
  try {
    const study = new FolderStudy(h);
    const run = study.run(f.images, { goal: f.goal });
    assert.equal(study.status(f.images.map(i => i.name)).state, 'running');
    const result = await run;
    assert.deepEqual([result.studied, result.failed, result.stopped], [10, 0, false]);
    assert.equal(seen.calls.length, 10); assert.ok(seen.most <= STUDY_CONCURRENCY && seen.most > 1, `most at once: ${seen.most}`);
    const status = study.status(f.images.map(i => i.name));
    assert.equal(status.state, 'done'); assert.equal(status.done, 10); assert.equal(status.total, 10);
    assert.ok(Object.values(status.images).every(s => s === 'studied'));
    assert.equal(study.noteOf('01-part.png'), NOTE);
    const saved = JSON.parse(await readFile(join(f.chat, STUDY_FILE), 'utf8'));
    const key = sha(await readFile(f.images[1].path)) + '@' + sha(await readFile(f.goal.path));   // the element, placed in this goal
    assert.equal(saved.notes[key].note, NOTE); assert.equal(saved.names['01-part.png'], key);
    assert.ok(saved.notes[sha(await readFile(f.goal.path)) + ':goal'], 'the goal\'s own note');
    assert.ok(seen.changed >= 10, 'each image tells the panel');
    // The goal is sent alone; an element with the goal (smaller) to place it.
    const goalCall = seen.calls.find(c => c.prompt.includes('the goal image of a painting'));
    assert.equal(goalCall.images.length, 1); assert.equal(goalCall.images[0].picture.side, STUDY_SIDE);
    const elementCall = seen.calls.find(c => c.prompt.includes('01-part.png'));
    assert.equal(elementCall.images.length, 2); assert.ok(elementCall.images[1].picture.side < STUDY_SIDE);
    // Diagnostics: one record per image with its time and cost, and the run's.
    const images = seen.events.filter(e => e.type === 'folder_study_image');
    assert.equal(images.length, 10); assert.ok(images.every(e => e.ok && e.ms >= 0 && e.cost === 0.0008 && e.model === 'openrouter/test-vision'));
    const runEvent = seen.events.find(e => e.type === 'folder_study');
    assert.deepEqual([runEvent.studied, runEvent.failed], [10, 0]); assert.ok(Math.abs(runEvent.cost - 0.008) < 1e-9);
    // A second run, or a new FolderStudy on the same chat folder, asks nothing again.
    await study.run(f.images, { goal: f.goal });
    const again = new FolderStudy(h); await again.run(f.images, { goal: f.goal });
    assert.equal(seen.calls.length, 10);
    assert.equal(again.noteOf('09-part.png'), NOTE);
  } finally { await f.close(); }
});

test('a changed image is studied again; the same picture under another name reuses its note', async () => {
  const f = await folder();
  const { seen, host: h } = host(f.chat);
  try {
    const study = new FolderStudy(h);
    await study.run(f.images, { goal: f.goal });
    assert.equal(seen.calls.length, 4);
    await writeFile(f.images[2].path, 'repainted');
    await study.refresh(f.images);
    assert.equal(study.status(f.images.map(i => i.name)).images[f.images[2].name], 'not_studied', 'the old note was for another picture');
    assert.equal(study.noteOf(f.images[2].name), null);
    await study.run(f.images, { goal: f.goal });
    assert.equal(seen.calls.length, 5);
    const copy = { ...f.images[1], name: '07-copy.png' };
    await study.run([copy], { goal: f.goal });
    assert.equal(seen.calls.length, 5, 'same content: no request');
    assert.equal(study.noteOf('07-copy.png'), NOTE);
  } finally { await f.close(); }
});

test('a failed or timed-out image is just not studied; the rest go on, and the failed one is retried on demand', async () => {
  const f = await folder();
  let fail = true;
  const { seen, host: h } = host(f.chat, { answer: request => {
    if (request.prompt.includes('02-historic-buildings.png') && fail) throw new Error('provider said no');
    if (request.prompt.includes('03-domed-church.png') && fail) return new Promise(() => {});   // never answers
    return NOTE;
  } });
  try {
    const study = new FolderStudy(h, { timeoutMs: 60 });
    const result = await study.run(f.images, { goal: f.goal });
    assert.deepEqual([result.studied, result.failed], [2, 2]);
    const status = study.status(f.images.map(i => i.name));
    assert.equal(status.images['02-historic-buildings.png'], 'not_studied'); assert.equal(status.images['03-domed-church.png'], 'not_studied');
    assert.equal(status.failed, 2);
    const failures = seen.events.filter(e => e.type === 'folder_study_image' && !e.ok);
    assert.deepEqual(failures.map(e => e.reason).sort(), ['request_failed', 'timeout']);
    assert.ok(!JSON.stringify(seen.events).includes('provider said no'), 'only a classified reason is recorded');
    fail = false;
    // A failure is kept: a later run (this chat resumed, or the setting saved) does not send it again.
    const calls = seen.calls.length;
    const resumed = new FolderStudy(h, { timeoutMs: 60 });
    await resumed.run(f.images, { goal: f.goal });
    assert.equal(seen.calls.length, calls, 'failed images wait to be asked for');
    assert.equal(resumed.status(f.images.map(i => i.name)).failed, 2);
    assert.equal(await resumed.studyOne(f.images[2], { goal: f.goal }), NOTE, 'retried when it is opened');
    assert.equal(resumed.status(f.images.map(i => i.name)).images['02-historic-buildings.png'], 'studied');
    await resumed.run([f.images[3]], { goal: f.goal, retry: true });
    assert.equal(resumed.status(f.images.map(i => i.name)).images['03-domed-church.png'], 'studied', 'Study from the menu retries');
  } finally { await f.close(); }
});

test('hashes are kept by path, size and time: a resumed chat reads no image again; a changed file is read', async () => {
  const f = await folder();
  const { seen, host: h } = host(f.chat);
  try {
    await new FolderStudy(h).run(f.images, { goal: f.goal });
    const again = new FolderStudy(h);
    seen.reads = 0;
    await again.refresh(f.images, { goal: f.goal });
    await again.run(f.images, { goal: f.goal });
    assert.equal(seen.reads, 0, 'nothing read on resume');
    await new Promise(resolve => setTimeout(resolve, 20));
    await writeFile(f.images[3].path, 'repainted church');
    await again.refresh(f.images, { goal: f.goal });
    assert.equal(seen.reads, 1, 'only the changed file');
  } finally { await f.close(); }
});

test('an element\'s note belongs to the goal it was placed in: a new goal makes the element notes stale; the goal image is sent once a run', async () => {
  const f = await folder();
  const { seen, host: h } = host(f.chat);
  try {
    const study = new FolderStudy(h);
    await study.run(f.images, { goal: f.goal });
    assert.equal(seen.pictures.filter(p => p.side < STUDY_SIDE).length, 1, 'the goal context picture is made once and reused');
    const newGoal = { ...f.images[1], role: 'goal' }, rest = [newGoal, { ...f.images[0], role: 'element' }, f.images[2], f.images[3]];
    await study.refresh(rest, { goal: newGoal });
    const status = study.status(rest.map(i => i.name)).images;
    assert.equal(status['02-historic-buildings.png'], 'not_studied', 'placed in the old goal');
    assert.equal(status['01-moonlit-sky.png'], 'not_studied', 'the new goal needs a goal note');
    await study.run(rest, { goal: newGoal });
    assert.equal(seen.calls.length, 8);
    await study.refresh(f.images, { goal: f.goal });
    assert.ok(Object.values(study.status(f.images.map(i => i.name)).images).every(s => s === 'studied'), 'back to the first goal: its notes are still there');
  } finally { await f.close(); }
});

test('lazy studies share the 4-at-a-time cap with the run; Stop also cancels a run waiting its turn', async () => {
  const f = await folder(['final_goal.png', ...Array.from({ length: 9 }, (_, i) => `0${i + 1}-part.png`)]);
  const { seen, host: h } = host(f.chat, { delay: 30 });
  try {
    const study = new FolderStudy(h);
    const run = study.run(f.images.slice(0, 6), { goal: f.goal });
    const lazy = f.images.slice(6).map(image => study.studyOne(image, { goal: f.goal }));
    await Promise.all([run, ...lazy]);
    assert.ok(seen.most <= STUDY_CONCURRENCY, `most at once: ${seen.most}`);
    const g = await folder(['final_goal.png', '01-a.png', '02-b.png']);
    const { seen: seen2, host: h2 } = host(g.chat, { delay: 40 });
    try {
      const other = new FolderStudy(h2);
      const first = other.run(g.images.slice(0, 2), { goal: g.goal });
      const queued = other.run(g.images, { goal: g.goal });
      other.stop();
      const [, second] = await Promise.all([first, queued]);
      assert.equal(second.stopped, true, 'the queued run never starts');
      assert.ok(seen2.calls.length <= 2);
    } finally { await g.close(); }
  } finally { await f.close(); }
});


test('Stop ends the run: what is studied stays, the rest is not studied; a note too short to use is a failure', async () => {
  const f = await folder(['final_goal.png', ...Array.from({ length: 8 }, (_, i) => `0${i + 1}-part.png`)]);
  const { seen, host: h } = host(f.chat, { delay: 40, answer: request => request.prompt.includes('08-part') ? 'Sky.' : NOTE });
  try {
    const study = new FolderStudy(h);
    const run = study.run(f.images, { goal: f.goal });
    while (!seen.events.some(e => e.type === 'folder_study_image' && e.ok)) await new Promise(resolve => setTimeout(resolve, 5));   // the first note, however slow the machine
    study.stop();
    const result = await run;
    assert.equal(result.stopped, true);
    assert.ok(result.studied >= 1 && result.studied < 9, `studied ${result.studied}`);
    assert.equal(study.status(f.images.map(i => i.name)).state, 'stopped');
    assert.ok(seen.calls.length < 9, 'nothing new starts after Stop');
    const rest = new FolderStudy(h);
    await rest.run(f.images, { goal: f.goal });
    assert.equal(rest.status(f.images.map(i => i.name)).images['08-part.png'], 'not_studied', 'a one-word note is not a note');
  } finally { await f.close(); }
});

test('studyOne joins a run already studying that image, and needs a reader: without one nothing is studied', async () => {
  const f = await folder();
  const { seen, host: h } = host(f.chat, { delay: 30 });
  try {
    const study = new FolderStudy(h);
    const run = study.run(f.images, { goal: f.goal });
    assert.equal(await study.studyOne(f.images[1], { goal: f.goal }), NOTE);
    await run;
    assert.equal(seen.calls.length, 4, 'the image was not asked twice');
    const none = new FolderStudy({ ...h, directory: () => null, reader: async () => null });   // a chat folder with no notes
    const result = await none.run(f.images, { goal: f.goal });
    assert.equal(result.studied, 0); assert.equal(result.unavailable, true);
    assert.equal(none.status(f.images.map(i => i.name)).state, 'unavailable');
    assert.equal(await none.studyOne(f.images[1], { goal: f.goal }), null);
  } finally { await f.close(); }
});

test('piReader asks the model through Pi\'s completeSimple and returns the text and cost; studyModelRoute prefers the painter, then the planner, then qwen3-vl', async () => {
  const asked = [];
  const models = { completeSimple: async (model, context, options) => { asked.push({ model, context, options });
    return { content: [{ type: 'text', text: NOTE }], usage: { cost: { total: 0.0009 } }, stopReason: 'stop' }; } };
  const read = piReader(models, { provider: 'openrouter', id: 'qwen/qwen3-vl-235b-a22b-instruct', input: ['text', 'image'] });
  const controller = new AbortController();
  const reply = await read({ prompt: 'Describe.', images: [{ label: 'IMAGE:', picture: { data: 'AAAA', mimeType: 'image/png' } }], signal: controller.signal });
  assert.deepEqual(reply, { text: NOTE, cost: 0.0009, model: 'openrouter/qwen/qwen3-vl-235b-a22b-instruct' });
  const content = asked[0].context.messages[0].content;
  assert.deepEqual(content.map(c => c.type), ['text', 'image', 'text']);
  assert.equal(asked[0].options.signal, controller.signal);
  const failing = piReader({ completeSimple: async () => ({ content: [], stopReason: 'error', errorMessage: 'secret detail' }) }, { provider: 'p', id: 'm', input: ['image'] });
  await assert.rejects(failing({ prompt: 'x', images: [], signal: controller.signal }), /provider_error/);
  const vision = { provider: 'a', id: 'eyes', input: ['text', 'image'] }, text = { provider: 'b', id: 'words', input: ['text'] };
  assert.equal(studyModelRoute({ painter: vision, planner: text, fallback: null }), vision);
  assert.equal(studyModelRoute({ painter: text, planner: vision, fallback: null }), vision);
  const qwen = { provider: 'openrouter', id: 'qwen/qwen3-vl-235b-a22b-instruct', input: ['text', 'image'] };
  assert.equal(studyModelRoute({ painter: text, planner: text, fallback: qwen }), qwen);
  assert.equal(studyModelRoute({ painter: text, planner: null, fallback: null }), null);
  assert.equal(STUDY_MODEL, 'openrouter/qwen/qwen3-vl-235b-a22b-instruct');
});
