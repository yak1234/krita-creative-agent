// Opening Krita for the agent: start it only when it is not running, wait for the plugin's bridge, report what is open.
// Fakes for the process, the bridge and the clock. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { launchKrita } from '../src/krita-launch.ts';

function fakes({ running = false, failures = 0, healthy = true } = {}) {
  const calls = [];
  let left = failures;
  return {
    calls,
    deps: {
      running: async () => { calls.push('running'); return running; },
      start: async () => { calls.push('start'); },
      health: async () => {
        calls.push('health');
        if (!healthy || left-- > 0) throw new Error('connection refused');
        return { status: 'ok', build: { build_id: 'build-1234567890' }, session_active: false, krita_actions: 11, krita_version: '5.3.3' };
      },
      context: async () => ({ documents: [{ name: 'new_moscow', filename: '/art/new_moscow_finished.kra', modified: false }] }),
      sleep: async () => { calls.push('sleep'); },
      timeoutMs: 30, intervalMs: 10, now: (() => { let t = 0; return () => (t += 10); })(),
    },
  };
}

test('Krita not running: it is started, and the result waits for the plugin’s bridge', async () => {
  const f = fakes({ failures: 2 });
  const result = await launchKrita(f.deps);
  assert.deepEqual(f.calls.slice(0, 2), ['running', 'start']);
  assert.equal(f.calls.filter(c => c === 'health').length, 3, 'two refusals while Krita loads, then ready');
  assert.deepEqual(result, { status: 'ready', started: true, build: 'build-1234567890', krita_version: '5.3.3', session_active: false,
    krita_actions: 11, documents: [{ name: 'new_moscow', filename: '/art/new_moscow_finished.kra', modified: false }] });
});

test('Krita already running: nothing is started, it only reports', async () => {
  const f = fakes({ running: true });
  const result = await launchKrita(f.deps);
  assert.ok(!f.calls.includes('start'));
  assert.equal(result.started, false);
  assert.equal(result.status, 'ready');
});

test('a bridge that never answers is reported, not waited on forever', async () => {
  const f = fakes({ healthy: false });
  const result = await launchKrita({ ...f.deps, timeoutMs: 50 });
  assert.equal(result.status, 'no_bridge');
  assert.match(result.message, /plugin/);
});
