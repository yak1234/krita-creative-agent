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
      if (command.type === 'move' || command.type === 'prompt') paint();
      if (command.type === 'shutdown') setImmediate(() => child.emit('exit', 0));
    }
  });
  setImmediate(() => emit({ type: 'ready' }));
  return child;
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
