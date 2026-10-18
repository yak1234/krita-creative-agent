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
  const state = { chat_id: 'chat-1', busy: false, moves: [{ number: 1, status: 'ready' }], canvas: '/c.png', copy: '/copy.kra', errors: [] };
  return {
    start: async options => { log.push(['start', options]); return { copy: '/copy.kra', krita: 'Krita: opened a copy' }; },
    prompt: text => log.push(['prompt', text]),
    move: action => log.push(['move', action]),
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
    assert.ok(log.some(([kind, ms]) => kind === 'wait' && ms === 30000));
    assert.equal((await call(driver.socket, 'GET', '/state?wait=600')).status, 400, 'waits are capped below a tool call timeout');
    const ended = await call(driver.socket, 'POST', '/end');
    assert.match(ended.body.krita, /closed the copy/);
    assert.equal((await call(driver.socket, 'POST', '/prompt', { text: 'x' })).status, 409, 'no chat after the end');
    assert.deepEqual(log.map(([kind]) => kind), ['start', 'prompt', 'move', 'wait', 'end']);
  } finally { await driver.close(); await rm(root, { recursive: true, force: true }); }
});
