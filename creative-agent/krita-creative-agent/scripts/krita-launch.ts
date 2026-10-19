// Open Krita for an agent, or report on the one that is running (src/krita-launch.ts; the krita-launch skill).
//   node scripts/krita-launch.ts [--timeout 180]
// Starts Krita only when it is not running (macOS: /Applications/krita.app; elsewhere `krita` on PATH), waits for the
// Creative Agent plugin's bridge, then prints the loaded build and the open documents as JSON. It never opens or
// closes a painting and never restarts a running Krita. Exit 0 when the bridge answers, 2 when it does not.
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { launchKrita } from '../src/krita-launch.ts';

const exec = promisify(execFile);
const argv = process.argv.slice(2);
const timeout = Number(argv[argv.indexOf('--timeout') + 1]) || 180;
const url = process.env.KRITA_BRIDGE_URL ?? 'http://127.0.0.1:5678';
const mac = process.platform === 'darwin';

async function creative(operation: string): Promise<any> {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'creative', params: { operation, params: {} }, timeout: 10 }), signal: AbortSignal.timeout(15000) });
  const body = await response.json();
  if (body?.error && !body.status) throw new Error(String(body.error));
  return body;
}

const result = await launchKrita({
  running: async () => {
    const pattern = mac ? 'krita.app/Contents/MacOS/krita' : 'krita';
    try { await exec('pgrep', ['-f', pattern]); return true; } catch { return false; }
  },
  start: async () => {
    if (mac) await exec('open', ['-a', 'krita']);
    else spawn('krita', [], { detached: true, stdio: 'ignore' }).unref();
  },
  health: () => creative('health'),
  context: () => creative('context'),
  sleep: ms => new Promise(resolve => setTimeout(resolve, ms)),
  timeoutMs: timeout * 1000,
});
console.log(JSON.stringify(result, null, 2));
process.exitCode = result.status === 'ready' ? 0 : 2;
