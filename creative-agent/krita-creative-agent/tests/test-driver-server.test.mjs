// The test driver's local socket: one test chat at a time, behind routes the MCP tools call. A fake test companion;
// the socket lives in a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { request } from 'node:http';
import { mkdtemp, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { serveDriver } from '../src/test-driver-server.ts';

function call(socket, method, path, body) {
  return new Promise((resolve, reject) => {
    const req = request({ socketPath: socket, path, method, headers: { 'Content-Type': 'application/json' } }, res => {
      let text = ''; res.on('data', c => text += c); res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(text) }));
    });
    req.on('error', reject); req.end(body ? JSON.stringify(body) : undefined);
  });
}

function fakeCompanion(log) {
  const state = { chat_id: 'chat-1', busy: false, canvas: '/c.png', copy: '/copy.kra', errors: [],
    moves: [{ number: 1, status: 'ready', review: { verdict: 'undone', findings: [{ type: 'covered_feature', feature: 'Moon', label: 'Moon covered' }], undone_batches: 1, batches: 3 } }, { number: 2, status: 'painting' }] };
  return {
    start: async options => { log.push(['start', options]); return { copy: '/copy.kra', krita: 'Krita: opened a copy' }; },
    prompt: text => log.push(['prompt', text]),
    move: action => log.push(['move', action]),
    protect: async name => { log.push(['protect', name]); return { status: 'ok', kept: 1 }; },
    waitIdle: async ms => { log.push(['wait', ms]); return state; },
    state: () => state,
    toolCalls: () => [{ tool: 'select', args: { steps: [{ seed: [1, 1] }] } }, { tool: 'fill_region', args: {} }],
    end: async () => { log.push(['end']); return { krita: 'Krita: closed the copy' }; },
  };
}

test('one test chat at a time, driven through the socket, with methods and the canvas in its state', async () => {
  const root = await mkdtemp(join(process.platform === 'win32' ? tmpdir() : '/tmp', 'test-driver-'));   // socket paths are length-limited
  const log = [];
  const driver = await serveDriver({ directory: root, make: () => fakeCompanion(log), canvas: () => ({ width: 1000, height: 1000 }) });
  try {
    if (process.platform !== 'win32') assert.equal((await stat(driver.socket)).mode & 0o777, 0o600, 'only the artist’s user');
    const started = await call(driver.socket, 'POST', '/start', { prompt: 'Finish the clouds.', painting: 'new_moscow_finished.kra' });
    assert.equal(started.status, 200);
    assert.match(started.body.krita, /opened a copy/);
    assert.equal((await call(driver.socket, 'POST', '/start', { prompt: 'again' })).status, 409, 'a second chat waits for the first to end');
    assert.equal((await call(driver.socket, 'POST', '/prompt', { text: 'Softer edges.' })).status, 200);
    assert.equal((await call(driver.socket, 'POST', '/move', { action: 'keep' })).status, 200);
    assert.equal((await call(driver.socket, 'POST', '/move', { action: 'delete' })).status, 400);
    const state = await call(driver.socket, 'GET', '/state?wait=30');
    assert.deepEqual(state.body.tool_calls, [{ tool: 'select', methods: ['seed'] }, { tool: 'fill_region', methods: ['fill'] }]);
    assert.equal(state.body.canvas, '/c.png');
    assert.deepEqual(state.body.runtime_luna, [{ move: 1, verdict: 'undone', undone_batches: 1, batches: 3, findings: [{ type: 'covered_feature', feature: 'Moon', label: 'Moon covered' }] }],
      'Luna’s runtime verdict per reviewed move, labelled runtime');
    assert.equal((await call(driver.socket, 'POST', '/protect', {})).status, 400);
    assert.deepEqual((await call(driver.socket, 'POST', '/protect', { name: 'Moon' })).body, { status: 'ok', kept: 1 });
    assert.ok(log.some(([kind, ms]) => kind === 'wait' && ms === 30000));
    assert.equal((await call(driver.socket, 'GET', '/state?wait=600')).status, 400, 'waits are capped below a tool call timeout');
    const ended = await call(driver.socket, 'POST', '/end');
    assert.match(ended.body.krita, /closed the copy/);
    assert.equal((await call(driver.socket, 'POST', '/prompt', { text: 'x' })).status, 409, 'no chat after the end');
    assert.deepEqual(log.map(([kind]) => kind), ['start', 'prompt', 'move', 'wait', 'protect', 'end']);
  } finally { await driver.close(); await rm(root, { recursive: true, force: true }); }
});

test('each test chat is made fresh, so an install between chats is picked up (make may be async)', async () => {
  const root = await mkdtemp(join(process.platform === 'win32' ? tmpdir() : '/tmp', 'test-driver-'));
  const log = []; let made = 0;
  const driver = await serveDriver({ directory: root, make: async () => { made++; await new Promise(r => setImmediate(r)); return fakeCompanion(log); },
    canvas: () => ({ width: 10, height: 10 }) });
  try {
    for (let i = 0; i < 2; i++) {
      assert.equal((await call(driver.socket, 'POST', '/start', { prompt: 'Clouds.' })).status, 200);
      assert.equal((await call(driver.socket, 'POST', '/end')).status, 200);
    }
    assert.equal(made, 2);
  } finally { await driver.close(); await rm(root, { recursive: true, force: true }); }
});

test('a folder or references for a test chat, test assets resolved to their fixture, and panel commands with refusals as 400', async () => {
  const root = await mkdtemp(join(process.platform === 'win32' ? tmpdir() : '/tmp', 'test-driver-'));
  const { mkdir, writeFile, readdir } = await import('node:fs/promises');
  const { TestAssets } = await import('../src/test-fixtures.ts');
  const { panelCommand } = await import('../src/test-commands.ts');
  const source = join(root, 'new_moscow', 'moscow-painting-assets');
  await mkdir(source, { recursive: true });
  await writeFile(join(source, 'final_goal.png'), 'goal'); await writeFile(join(source, 'PLAN.md'), 'plan');
  const log = [];
  const companion = () => ({ ...fakeCompanion(log), command: async (type, params) => {
    const planned = panelCommand(type, params, { testFolder: root, planSteps: [], question: null, closeupQuestion: null, foundAreas: [], folderElements: [] });
    log.push(['command', planned.command.type]); return { status: 'ok', type };
  } });
  const driver = await serveDriver({ directory: root, make: companion, canvas: () => ({ width: 10, height: 10 }),
    assets: new TestAssets(join(root, 'driver', 'test-assets')), assetsSource: source });
  try {
    assert.equal((await call(driver.socket, 'POST', '/start', { prompt: 'x', folder: 'relative' })).status, 400);
    assert.equal((await call(driver.socket, 'POST', '/start', { prompt: 'x', references: ['a.png', 7] })).status, 400);
    const missing = await call(driver.socket, 'POST', '/start', { prompt: 'x', folder: 'test-assets:moscow-painting-assets' });
    assert.equal(missing.status, 400); assert.match(missing.body.error, /prepare/);
    assert.deepEqual((await call(driver.socket, 'POST', '/assets', { action: 'list' })).body, { status: 'ok', assets: [] });
    const prepared = await call(driver.socket, 'POST', '/assets', { action: 'prepare' });
    assert.equal(prepared.body.folder, 'test-assets:moscow-painting-assets');
    assert.deepEqual(await readdir(source), ['PLAN.md', 'final_goal.png'], 'the source is only read');
    assert.equal((await call(driver.socket, 'POST', '/assets', { action: 'wipe' })).status, 400);
    const started = await call(driver.socket, 'POST', '/start', { prompt: 'Plan it.', folder: 'test-assets:moscow-painting-assets', references: [join(source, 'final_goal.png')] });
    assert.equal(started.status, 200);
    const options = log.find(([kind]) => kind === 'start')[1];
    assert.equal(options.folder, join(root, 'driver', 'test-assets', 'moscow-painting-assets'), 'the fixture, which the test chat copies again');
    assert.deepEqual(options.references, [join(source, 'final_goal.png')]);
    const refused = await call(driver.socket, 'POST', '/command', { type: 'shutdown', params: {} });
    assert.equal(refused.status, 400); assert.match(refused.body.error, /not a test command/);
    assert.deepEqual((await call(driver.socket, 'POST', '/command', { type: 'stop' })).body, { status: 'ok', type: 'stop' });
    assert.equal((await call(driver.socket, 'POST', '/end')).status, 200);
    assert.deepEqual((await call(driver.socket, 'POST', '/assets', { action: 'remove', name: 'moscow-painting-assets' })).body, { status: 'ok', removed: 'moscow-painting-assets' });
  } finally { await driver.close(); await rm(root, { recursive: true, force: true }); }
});
