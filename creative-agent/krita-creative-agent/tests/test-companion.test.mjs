// The test companion: a separate companion process, its own data folder, driven like the panel drives it. A fake
// companion process and a fake bridge; files go to a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, mkdir, readFile, rm, writeFile, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { TestCompanion } from '../src/test-companion.ts';

/** A child process that answers the panel's commands with the events the companion emits. */
function fakeCompanion(commands) {
  const child = new EventEmitter();
  child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
  child.kill = () => child.emit('exit', 0);
  const emit = event => child.stdout.write(JSON.stringify(event) + '\n');
  let moves = 0;
  const paint = () => { moves++; emit({ type: 'busy', busy: true });
    emit({ type: 'canvas', path: '/canvas-' + moves + '.png' });
    emit({ type: 'move', move: { number: moves, status: 'ready', title: 'Move ' + moves, actions: 2, strokes: 0, request_done: moves === 2 } });
    emit({ type: 'busy', busy: false }); };
  let buffer = '';
  child.stdin.on('data', chunk => {
    buffer += chunk; const lines = buffer.split('\n'); buffer = lines.pop();
    for (const line of lines) {
      const command = JSON.parse(line); commands.push(command);
      if (command.type === 'start') { emit({ type: 'study', id: 'chat-1' }); paint(); }
      if (command.type === 'move' && command.action === 'undo')       // the panel learns of an undo from the goal
        emit({ type: 'goal', goal: { moves: [{ number: command.move, status: 'undone', title: 'Move ' + command.move }] } });
      if (command.type === 'move' || command.type === 'prompt') paint();
      if (command.type === 'shutdown') setImmediate(() => child.emit('exit', 0));
      folderEvents(command, emit);
    }
  });
  setImmediate(() => emit({ type: 'ready' }));
  return child;
}

/** The project folder, Find it and Paint only here, as the companion answers them (studio.mjs). */
let chatFolder = '/nowhere';
function folderEvents(command, emit) {
  if (command.type === 'open_folder') emit({ type: 'folder', index: { root: command.path, name: 'moscow-painting-assets', goal: { name: 'final_goal.png' },
    elements: [{ name: '01-moonlit-sky.png', guess: 'moonlit sky' }], others: [], texts: [], skipped: [] }, references: {} });
  if (command.type === 'find_it' && !/moon|river/.test(command.part)) emit({ type: 'found_area', request_id: command.request_id, part: command.part,
    mask_path: join(chatFolder, 'data', 'chat', '.shapes', 'found-0123456789abcdef01234567.png'), bounds: [0, 0, 8, 4], canvas: [8, 8], share: 0.5 });
  if (command.type === 'paint_only_here') emit({ type: 'goal', goal: { moves: [], paint_only_here: command.action === 'set' ? { name: command.name, bounds: command.bounds,
    mask_path: join(chatFolder, 'data', 'chat', '.shapes', 'paint-only-0123456789abcdef01234567.png'), share: 0.5, set_at: new Date().toISOString() + Math.random() } : null } });
}

async function setup() {
  const root = await mkdtemp(join(tmpdir(), 'test-companion-'));
  const project = join(root, 'project'), data = join(root, 'artist-data');
  await mkdir(project, { recursive: true }); await mkdir(data, { recursive: true });
  await writeFile(join(project, 'painting.kra'), 'kra bytes');
  await writeFile(join(data, 'execution-settings.json'), '{"native_craft":true}');
  const base = { node: 'node', companion: '/release/companion/src/main.mjs', data_dir: data, project_root: project,
    bridge_url: 'http://127.0.0.1:1', build_id: 'build-1' };
  const bridgeCalls = [], commands = [];
  const bridge = async (action, params = {}) => {
    bridgeCalls.push([action, params]);
    if (action === 'creative' && params.operation === 'health') return { build: { build_id: 'build-1' }, session_active: false };
    if (action === 'creative' && params.operation === 'close_benchmark_copy') return { status: 'ok', closed: true };
    return { status: 'ok' };
  };
  const companion = new TestCompanion(base, join(root, 'benchmark-runs', '202610181200-tool-choice', 'test-1'),
    { bridge, spawn: () => fakeCompanion(commands), quietMs: 20 });
  return { root, project, data, companion, bridgeCalls, commands, cleanup: () => rm(root, { recursive: true, force: true }) };
}

test('a test chat on a copy: own data folder, the copy opened, the chat driven, then closed unsaved and deleted', async () => {
  const s = await setup();
  try {
    const opened = await s.companion.start({ prompt: 'Finish the clouds.', painting: 'painting.kra', provider: 'p', model: 'm' });
    assert.match(opened.krita, /opened a copy/, 'the result says what it opened in Krita');
    const copy = opened.copy;
    assert.equal(await readFile(copy, 'utf8'), 'kra bytes');
    assert.deepEqual(s.bridgeCalls.find(([action]) => action === 'open_file'), ['open_file', { path: copy }]);
    assert.equal(await readFile(join(s.companion.folder, 'data', 'execution-settings.json'), 'utf8'), '{"native_craft":true}', 'the artist’s settings, copied');
    const config = JSON.parse(await readFile(join(s.companion.folder, 'companion-config.json'), 'utf8'));
    assert.equal(config.data_dir, join(s.companion.folder, 'data'), 'never the artist’s data folder: no chat in their list');
    const start = s.commands.find(c => c.type === 'start');
    assert.equal(start.prompt, 'Finish the clouds.');
    assert.equal(start.mode, 'current'); assert.equal(start.chat_mode, 'agent');

    let state = await s.companion.waitIdle(5000);
    assert.equal(state.chat_id, 'chat-1');
    assert.deepEqual(state.moves.map(m => [m.number, m.status]), [[1, 'ready']]);
    assert.equal(state.canvas, '/canvas-1.png');
    s.companion.move('keep');
    state = await s.companion.waitIdle(5000);
    assert.equal(state.moves.at(-1).number, 2);
    assert.equal(state.moves.at(-1).request_done, true);

    s.companion.move('undo');
    state = await s.companion.waitIdle(5000);
    assert.deepEqual(state.moves.map(m => [m.number, m.status]), [[1, 'ready'], [2, 'undone'], [3, 'ready']], 'an undo seen in the goal, the retry as a new move');

    const ended = await s.companion.end();
    assert.match(ended.krita, /closed the copy/);
    assert.ok(s.commands.some(c => c.type === 'end') && s.commands.some(c => c.type === 'shutdown'));
    assert.deepEqual(s.bridgeCalls.find(([, p]) => p.operation === 'close_benchmark_copy')[1].params, { path: copy });
    await assert.rejects(access(copy), 'the copy is deleted');
  } finally { await s.cleanup(); }
});

test('a start that fails after the copy is open closes the copy and deletes it', async () => {
  const s = await setup();
  try {
    const silent = () => { const child = new EventEmitter(); child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.kill = () => {}; return child; };
    const stuck = new TestCompanion(s.companion.base, s.companion.folder, { bridge: async (action, params = {}) => {
      s.bridgeCalls.push([action, params]);
      if (params.operation === 'health') return { build: { build_id: 'build-1' }, session_active: false };
      if (params.operation === 'close_benchmark_copy') return { status: 'ok', closed: true };
      return { status: 'ok' };
    }, spawn: silent, quietMs: 20, startMs: 50 });
    await assert.rejects(stuck.start({ prompt: 'x', painting: 'painting.kra' }), /Timed out waiting for the companion/);
    const copy = join(s.companion.folder, 'painting.kra');
    assert.ok(s.bridgeCalls.some(([, p]) => p.operation === 'close_benchmark_copy' && p.params.path === copy), 'the copy is closed in Krita');
    await assert.rejects(access(copy), 'and deleted');
  } finally { await s.cleanup(); }
});

test('ending mid-move stops the move first, and closes the copy once the session has let go', async () => {
  const s = await setup();
  try {
    let refusals = 1;
    const commands = [];
    const busy = () => {                                  // a companion that stays busy until it is told to stop
      const child = fakeCompanion(commands);
      const write = child.stdin.write.bind(child.stdin);
      child.stdin.write = data => {
        const command = JSON.parse(String(data));
        if (command.type === 'prompt') { child.stdout.write(JSON.stringify({ type: 'busy', busy: true }) + '\n'); commands.push(command); return true; }
        if (command.type === 'stop') { child.stdout.write(JSON.stringify({ type: 'busy', busy: false }) + '\n'); }
        return write(data);
      };
      return child;
    };
    const companion = new TestCompanion(s.companion.base, s.companion.folder, { quietMs: 20, spawn: busy, bridge: async (action, params = {}) => {
      if (params.operation === 'health') return { build: { build_id: 'build-1' }, session_active: false };
      if (params.operation === 'close_benchmark_copy')
        return refusals-- > 0 ? { error: 'ValueError: A painting session is open: end it before closing the benchmark copy.' } : { status: 'ok', closed: true };
      return { status: 'ok' };
    }, closeRetryMs: 10 });
    await companion.start({ prompt: 'x', painting: 'painting.kra' });
    await companion.waitIdle(5000);
    companion.prompt('Keep going.');                     // busy now
    const ended = await companion.end();
    const types = commands.map(c => c.type);
    assert.ok(types.indexOf('stop') >= 0 && types.indexOf('stop') < types.indexOf('end'), 'Stop before End');
    assert.match(ended.krita, /closed the copy/, 'the close was retried until the session let go');
  } finally { await s.cleanup(); }
});

test('a test chat on a new canvas opens no copy', async () => {
  const s = await setup();
  try {
    const opened = await s.companion.start({ prompt: 'Paint Starry Night.', width: 1200, height: 950 });
    assert.match(opened.krita, /new painting/);
    const start = s.commands.find(c => c.type === 'start');
    assert.deepEqual([start.mode, start.width, start.height], ['new', 1200, 950]);
    assert.equal(s.bridgeCalls.some(([action]) => action === 'open_file'), false);
    await s.companion.waitIdle(5000);
    s.companion.prompt('Make the sky swirl more.');
    assert.equal(s.commands.at(-1).text, 'Make the sky swirl more.');
    await s.companion.waitIdle(5000);
    await s.companion.end();
  } finally { await s.cleanup(); }
});

test('a test chat refuses while Krita holds the artist’s painting session, or runs another build', async () => {
  const s = await setup();
  try {
    const busy = new TestCompanion({ ...s.companion.base }, s.companion.folder,
      { bridge: async () => ({ build: { build_id: 'build-1' }, session_active: true }), spawn: () => fakeCompanion([]) });
    await assert.rejects(busy.start({ prompt: 'x' }), /painting session/);
    const stale = new TestCompanion({ ...s.companion.base }, s.companion.folder,
      { bridge: async () => ({ build: { build_id: 'other' }, session_active: false }), spawn: () => fakeCompanion([]) });
    await assert.rejects(stale.start({ prompt: 'x' }), /build/);
  } finally { await s.cleanup(); }
});

test('a Luna override is written into the test chat’s settings, never the artist’s; protect keeps a proposed area', async () => {
  const s = await setup();
  try {
    await s.companion.start({ prompt: 'Finish the clouds.', luna: 'evaluate' });
    const settings = JSON.parse(await readFile(join(s.companion.folder, 'data', 'execution-settings.json'), 'utf8'));
    assert.deepEqual(settings, { native_craft: true, routing: 'evaluate' });
    assert.equal(await readFile(join(s.data, 'execution-settings.json'), 'utf8'), '{"native_craft":true}', 'the artist’s file is untouched');
    s.bridgeCalls.length = 0;
    const kept = await s.companion.protect('Moon');
    assert.deepEqual(s.bridgeCalls, [['creative', { operation: 'test_keep_protection', params: { name: 'Moon' } }]]);
    assert.deepEqual(kept, { status: 'ok' });
    await s.companion.end();
  } finally { await s.cleanup(); }
});

test('end closes every document saved inside the run folder: an image copy the session saved as a .kra', async () => {
  const s = await setup();
  try {
    await writeFile(join(s.project, 'flat.png'), 'png bytes');
    const closes = [];
    const saved = join(s.companion.folder, 'Test chat.kra');
    const companion = new TestCompanion(s.companion.base, s.companion.folder, { quietMs: 20, spawn: () => fakeCompanion([]), bridge: async (action, params = {}) => {
      if (params.operation === 'health') return { build: { build_id: 'build-1' }, session_active: false };
      // As the real bridge: context is a creative operation, and an unknown action is an error.
      if (!['creative', 'open_file', 'health', 'reload', 'save_native'].includes(action)) return { error: `Unknown action: ${action}` };
      if (params.operation === 'context') return { documents: [{ filename: saved }, { filename: '/art/new_moscow_finished.kra' }] };
      if (params.operation === 'close_benchmark_copy') { closes.push(params.params.path); return { status: 'ok', closed: params.params.path === saved }; }
      return { status: 'ok' };
    } });
    await companion.start({ prompt: 'Finish the clouds.', painting: 'flat.png' });
    await writeFile(saved, 'kra'); await writeFile(saved + '~', 'backup');
    const ended = await companion.end();
    assert.deepEqual(closes, [saved], 'the document Krita has open is the saved .kra, never the artist’s painting');
    await assert.rejects(access(saved)); await assert.rejects(access(saved + '~')); await assert.rejects(access(join(s.companion.folder, 'flat.png')));
    assert.match(ended.krita, /Test chat\.kra/);
  } finally { await s.cleanup(); }
});

test('element shapes in a test chat: the artist’s downloaded model is shared, and every shape timing reaches the report', async () => {
  const s = await setup();
  try {
    await mkdir(join(s.data, 'models', 'sam2.1-hiera-base-plus'), { recursive: true });
    await s.companion.start({ prompt: 'Trace the tower.', width: 800, height: 600 });
    const { lstat, readlink } = await import('node:fs/promises');
    const shared = join(s.companion.folder, 'data', 'models');
    assert.ok((await lstat(shared)).isSymbolicLink(), 'the 330 MB model is linked, never copied or downloaded again per test chat');
    assert.equal(await readlink(shared), join(s.data, 'models'));
    const child = s.companion.child;
    const emit = event => child.stdout.write(JSON.stringify(event) + '\n');
    emit({ type: 'shapes_model_needed', model: 'sam2.1-hiera-base-plus', size_mb: 328, message: 'Download it now?' });
    emit({ type: 'shape_timing', kind: 'study', ms: 2200, peak_mb: 1630, provider: 'cpu', image_id: 'abc' });
    emit({ type: 'shapes_model_ready' });
    emit({ type: 'shape_timing', kind: 'shape', ms: 19, peak_mb: 1660, provider: 'cpu', image_id: 'abc', score: 0.95 });
    await new Promise(resolve => setTimeout(resolve, 50));
    const state = s.companion.state();
    assert.deepEqual(state.shape_timings.map(t => [t.kind, t.ms, t.peak_mb, t.provider]), [['study', 2200, 1630, 'cpu'], ['shape', 19, 1660, 'cpu']]);
    assert.equal(state.shapes_model_needed, null, 'the download question is shown while it waits, and cleared once answered');
    emit({ type: 'shapes_model_needed', model: 'sam2.1-hiera-base-plus', size_mb: 328, message: 'Download it now?' });
    await new Promise(resolve => setTimeout(resolve, 50));
    assert.match(s.companion.state().shapes_model_needed, /Download it now/);
    await s.companion.end();
  } finally { await s.cleanup(); }
});

test('a test chat on a copy of a project folder and of reference images: the panel’s open folder, never the artist’s files, all deleted at the end', async () => {
  const s = await setup();
  try {
    chatFolder = s.companion.folder;
    const artist = join(s.root, 'artist', 'moscow-painting-assets');
    await mkdir(artist, { recursive: true });
    await writeFile(join(artist, 'final_goal.png'), 'goal'); await writeFile(join(artist, '01-moonlit-sky.png'), 'sky'); await writeFile(join(artist, 'PLAN.md'), 'plan');
    await writeFile(join(s.root, 'artist', 'ref.png'), 'ref');
    const { readdir } = await import('node:fs/promises');
    const before = (await readdir(join(s.root, 'artist'), { recursive: true })).sort();
    const opened = await s.companion.start({ prompt: 'Plan the New Moscow painting.', folder: artist, references: [join(s.root, 'artist', 'ref.png')] });
    const copy = join(s.companion.folder, 'project', 'moscow-painting-assets');
    assert.equal(opened.project_folder, copy);
    assert.match(opened.krita, /copy of the project folder/);
    assert.equal(await readFile(join(copy, 'final_goal.png'), 'utf8'), 'goal');
    const types = s.commands.map(c => c.type);
    assert.ok(types.indexOf('open_folder') >= 0 && types.indexOf('open_folder') < types.indexOf('start'), 'the folder opens before the chat starts, as in the panel');
    assert.equal(s.commands.find(c => c.type === 'open_folder').path, copy, 'the test chat only sees the copy');
    const start = s.commands.find(c => c.type === 'start');
    assert.deepEqual(start.references.map(r => [r.path, r.name, r.role]), [[join(s.companion.folder, 'references', '1-ref.png'), 'ref.png', 'reference']]);
    const state = await s.companion.waitIdle(5000);
    assert.equal(state.project_folder.root, copy);
    assert.deepEqual(state.project_folder.elements, [{ name: '01-moonlit-sky.png', guess: 'moonlit sky' }]);
    await s.companion.end();
    await assert.rejects(access(copy), 'the folder copy is deleted');
    await assert.rejects(access(join(s.companion.folder, 'references')), 'the reference copies are deleted');
    assert.deepEqual((await readdir(join(s.root, 'artist'), { recursive: true })).sort(), before, 'nothing written into the artist’s folder');
  } finally { await s.cleanup(); }
});

test('panel commands drive the rehearsal: the plan and Now card in the state, Find it, Paint only here protected on the test copy only', async () => {
  const s = await setup();
  try {
    chatFolder = s.companion.folder;
    const protects = [];
    let documents = [];
    const companion = new TestCompanion(s.companion.base, s.companion.folder, { quietMs: 20, spawn: () => fakeCompanion(s.commands), bridge: async (action, params = {}) => {
      if (params.operation === 'health') return { build: { build_id: 'build-1' }, session_active: false };
      if (params.operation === 'context') return { documents };
      if (params.operation === 'paint_only_here') { protects.push(params.params); return { status: 'ok' }; }
      if (params.operation === 'close_benchmark_copy') return { status: 'ok', closed: true };
      return { status: 'ok' };
    } });
    await companion.start({ prompt: 'Plan it.', width: 8, height: 8 });
    await companion.waitIdle(5000);
    await assert.rejects(companion.command('shutdown', {}), /not a test command/);
    await assert.rejects(companion.command('start_plan', {}), /no plan yet/);
    const emit = event => companion.child.stdout.write(JSON.stringify(event) + '\n');
    emit({ type: 'goal', mode: 'agent', goal: { moves: [], brief: { title: 'New Moscow', steps: [{ title: 'Underpainting' }, { title: 'Accents' }] }, question: null },
      plan_steps: [{ index: 0, key: 'underpainting', title: 'Underpainting', state: 'met' }, { index: 1, key: 'accents', title: 'Accents', state: 'painting', batches: 2 }] });
    await new Promise(resolve => setTimeout(resolve, 30));
    let state = companion.state();
    assert.deepEqual(state.plan, { title: 'New Moscow', status: null, steps: ['Underpainting', 'Accents'] });
    assert.deepEqual(state.now, { caption: 'Now painting', index: 1, key: 'accents', title: 'Accents', state: 'painting', batches: 2 });
    assert.equal((await companion.command('plan_step', { action: 'good_enough', step_key: 'accents' })).status, 'ok');
    assert.equal(s.commands.at(-1).type, 'plan_step');
    const find = await companion.command('find_it', { part: 'the sky' });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(companion.state().found_areas.at(-1).request_id, find.request_id);
    documents = [{ document_id: 'artist', filename: '/art/new_moscow_finished.kra' }];
    const unprotected = await companion.command('paint_only_here', { action: 'set' });
    assert.match(unprotected.krita, /not protected/);
    assert.deepEqual(protects, [], 'never a document outside the test chat’s folder');
    documents.push({ document_id: 'test-doc', filename: join(s.companion.folder, 'Test chat.kra') });
    const set = await companion.command('paint_only_here', { action: 'set', name: 'Sky' });
    assert.match(set.krita, /protected/);
    const sent = s.commands.filter(c => c.type === 'paint_only_here').at(-1);
    assert.equal(sent.mask_path, join(s.companion.folder, 'data', 'chat', '.shapes', 'found-0123456789abcdef01234567.png'));
    assert.deepEqual(protects.at(-1), { action: 'set', bounds: [0, 0, 8, 4], mask_path: join(s.companion.folder, 'data', 'chat', '.shapes', 'paint-only-0123456789abcdef01234567.png'),
      name: 'Sky', document_id: 'test-doc' });
    state = companion.state();
    assert.equal(state.paint_only_here.name, 'Sky');
    await companion.command('paint_only_here', { action: 'clear' });
    assert.deepEqual(protects.at(-1), { action: 'clear', document_id: 'test-doc' });
    assert.equal(companion.state().paint_only_here, null);
    emit({ type: 'goal', mode: 'agent', goal: { moves: [], question: { id: 'q1', question: 'Is this the sky?', options: ['Use this', 'Paint everywhere'],
      select_area: { part: 'the sky', proposal: { mask_path: join(s.companion.folder, 'data', 'chat', '.shapes', 'found-0123456789abcdef01234567.png'), bounds: [0, 0, 8, 4], canvas: [8, 8] } } } } });
    await new Promise(resolve => setTimeout(resolve, 30));
    await companion.command('answer', { text: 'Use this', area: 'proposal' });
    const last = s.commands.slice(-2);
    assert.deepEqual(last.map(c => c.type), ['paint_only_here', 'prompt'], 'the area is taken and protected before the answer goes');
    assert.equal(last[1].text, 'Use this');
    await companion.end();
  } finally { await s.cleanup(); }
});

// Rehearsal fixes (2026-10-24, live in Toska).
test('end closes the test chat’s own new painting unsaved (it lives in the test folder), never another document', async () => {
  const s = await setup();
  try {
    const closes = [];
    const own = join(s.companion.folder, 'Test chat.kra');
    const companion = new TestCompanion(s.companion.base, s.companion.folder, { quietMs: 20, spawn: () => fakeCompanion([]), bridge: async (action, params = {}) => {
      if (params.operation === 'health') return { build: { build_id: 'build-1' }, session_active: false };
      if (params.operation === 'context') return { documents: [{ filename: own }, { filename: '/art/new_moscow_finished.kra' }] };
      if (params.operation === 'close_benchmark_copy') { closes.push(params.params.path); return { status: 'ok', closed: true }; }
      return { status: 'ok' };
    } });
    await companion.start({ prompt: 'Paint New Moscow.', width: 6000, height: 4500 });
    await writeFile(own, 'kra');
    const ended = await companion.end();
    assert.deepEqual(closes, [own], 'the test chat’s painting, not the artist’s');
    assert.match(ended.krita, /closed the test chat’s painting .*Test chat\.kra unsaved/);
    assert.equal(await readFile(own, 'utf8'), 'kra', 'its saved file stays in the test folder for the record');
  } finally { await s.cleanup(); }
});

test('a find in progress: the state waits for its outline, and the activity moves on when it arrives', async () => {
  const s = await setup();
  try {
    await s.companion.start({ prompt: 'Plan it.', width: 8, height: 8 });
    await s.companion.waitIdle(5000);
    const emit = event => s.companion.child.stdout.write(JSON.stringify(event) + '\n');
    s.commands.length = 0;
    // The real companion answers find_it a few seconds later, while it is not busy.
    const find = await s.companion.command('find_it', { part: 'the moon' });
    emit({ type: 'status', phase: 'idle', message: 'Finding the moon…' });
    const late = setTimeout(() => emit({ type: 'found_area', request_id: find.request_id, part: 'the moon', mask_path: '/m.png', bounds: [0, 0, 1, 1], canvas: [8, 8],
      share: 0.1, message: 'Found the moon in 5.7 s (locating 1.7 s, shapes model 3.7 s): 4% of the canvas.' }), 200);
    const state = await s.companion.waitIdle(5000);
    clearTimeout(late);
    assert.equal(state.found_areas.filter(f => f.request_id === find.request_id).length, 1, 'waited for the outline');
    assert.match(state.activity, /^Found the moon in 5\.7 s/);
    assert.equal(state.finding, null);
    await s.companion.command('find_it', { part: 'the river' });
    const failed = s.commands.at(-1);
    emit({ type: 'found_area', request_id: failed.request_id, error: 'I could not see the river on the painting.' });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(s.companion.state().activity, 'I could not see the river on the painting.');
    await s.companion.end();
  } finally { await s.cleanup(); }
});

test('the canvas reference card is in the state and is answered as the panel answers it', async () => {
  const s = await setup();
  try {
    await s.companion.start({ prompt: 'Paint it.', width: 6000, height: 4500 });
    await s.companion.waitIdle(5000);
    const emit = event => s.companion.child.stdout.write(JSON.stringify(event) + '\n');
    emit({ type: 'canvas_reference', id: 'ref-1', title: 'Canvas reference', message: 'A reference of a glow…', image_path: '/compare.png',
      options: ['Use as the target', 'Try again', 'Discard'], actions: ['use', 'retry', 'discard'], share: 0.04, bounds: [1, 2, 3, 4], auto_approve: false });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.deepEqual(s.companion.state().canvas_reference, { id: 'ref-1', options: ['Use as the target', 'Try again', 'Discard'], actions: ['use', 'retry', 'discard'],
      text: 'A reference of a glow…', image_path: '/compare.png' });
    await s.companion.command('canvas_reference_answer', { action: 'use' });
    assert.deepEqual(s.commands.at(-1), { type: 'canvas_reference', id: 'ref-1', action: 'use' });
    assert.equal(s.companion.state().canvas_reference, null, 'answered: the card is gone');
    await s.companion.end();
  } finally { await s.cleanup(); }
});

test('the Sharpen goal card is in the state and is answered as the panel answers it', async () => {
  const s = await setup();
  try {
    await s.companion.start({ prompt: 'Plan it.', width: 6000, height: 4500 });
    await s.companion.waitIdle(5000);
    const emit = event => s.companion.child.stdout.write(JSON.stringify(event) + '\n');
    await assert.rejects(s.companion.command('sharpen_answer', { action: 'sharpen' }), /no Sharpen goal card/);
    emit({ type: 'goal_sharpen_offer', id: 'offer-1', factor: 4.1, options: ['Sharpen', 'Use as is'], message: 'Your goal image is 4.1x smaller than the canvas…' });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.deepEqual(s.companion.state().sharpen, { kind: 'offer', id: 'offer-1', options: ['Sharpen', 'Use as is'], text: 'Your goal image is 4.1x smaller than the canvas…' });
    await assert.rejects(s.companion.command('sharpen_answer', { action: 'use' }), /action is sharpen or original/);
    await s.companion.command('sharpen_answer', { action: 'sharpen' });
    assert.deepEqual(s.commands.at(-1), { type: 'goal_sharpen', id: 'offer-1', action: 'sharpen' });
    emit({ type: 'goal_sharpen_progress', id: 'offer-1', done: 2, total: 4, message: 'Sharpening the goal image: 50%…' });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(s.companion.state().sharpen.progress, 'Sharpening the goal image: 50%…');
    emit({ type: 'goal_sharpen_review', id: 'offer-1', image_path: '/c.png', options: ['Use sharpened', 'Keep original'], question: 'Use the sharpened goal?' });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.deepEqual(s.companion.state().sharpen, { kind: 'review', id: 'offer-1', options: ['Use sharpened', 'Keep original'], text: 'Use the sharpened goal?', image_path: '/c.png' });
    await s.companion.command('sharpen_answer', { action: 'use' });
    assert.deepEqual(s.commands.at(-1), { type: 'goal_sharpen', id: 'offer-1', action: 'use' });
    assert.equal(s.companion.state().sharpen, null, 'answered: the card is gone');
    await s.companion.end();
  } finally { await s.cleanup(); }
});
