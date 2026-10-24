// Development only: the test driver behind the MCP's creative_test_* tools (test_driver_client.py starts it). It holds
// one test chat at a time in a separate test companion (src/test-companion.ts) with its own data folder, so test
// chats never appear in the artist's chat list. Paintings are copied into benchmark-runs/<stamp>-tool-choice/,
// opened, then closed unsaved and deleted; the original is never opened. A project folder or reference images are copied
// into the test chat's folder the same way. Test assets (creative_test_assets) live in benchmark-runs/test-assets: fixtures
// prepared once from a source folder that is only read (TEST_ASSETS_SOURCE, by default <project>/new_moscow/
// moscow-painting-assets), each test chat working on a fresh copy of one ('test-assets:<name>').
//   node scripts/test-driver.ts            (writes <project>/benchmark-runs/test-driver.json with its socket)
//   KRITA_CREATIVE_CONFIG=<fork pykrita>/kritamcp/creative-agent-config.json TEST_DRIVER_ENDPOINT=… (the fork)
import { readFile, mkdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { TestCompanion, httpBridge, type Base, type StartOptions } from '../src/test-companion.ts';
import { serveDriver } from '../src/test-driver-server.ts';
import { TestAssets } from '../src/test-fixtures.ts';

// Stock Krita's panel config, or another Krita's (the Qt6 fork's) when KRITA_CREATIVE_CONFIG names it; the client
// (test_driver_client.py) names this driver's endpoint in TEST_DRIVER_ENDPOINT, so each Krita has its own driver.
const panelConfig = process.env.KRITA_CREATIVE_CONFIG || join(homedir(), 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json');
// Read again for every test chat: an install and reload in between changes the build the chat must match.
const readBase = async () => JSON.parse(await readFile(panelConfig, 'utf8')) as Base;
const base = await readBase();
const bridge = httpBridge(base.bridge_url);
const runs = join(base.project_root, 'benchmark-runs');
await mkdir(runs, { recursive: true });
let count = 0;

const driver = await serveDriver({
  directory: '/tmp',                                            // unix socket paths are length-limited
  endpoint: process.env.TEST_DRIVER_ENDPOINT || join(runs, 'test-driver.json'),
  assets: new TestAssets(join(runs, 'test-assets')),
  assetsSource: process.env.TEST_ASSETS_SOURCE || join(base.project_root, 'new_moscow', 'moscow-painting-assets'),
  make: async () => {
    const base = await readBase();
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '');
    const companion = new TestCompanion(base, join(runs, `${stamp}-tool-choice`, `test-${++count}`), { bridge });
    // The painter model for tests unless a call names one (the live-test model).
    const start = companion.start.bind(companion);
    companion.start = (options: StartOptions) => start({ provider: 'deepseek', model: 'deepseek-flash', ...options });
    return companion;
  },
  canvas: async (copy, options) => {
    if (!copy) return { width: options.width ?? 768, height: options.height ?? 1024 };
    const context = await bridge('creative', { operation: 'context', params: {} });
    return { width: Number(context.width) || 1, height: Number(context.height) || 1 };
  },
});
const stop = async () => { await driver.close(); process.exit(0); };
process.on('SIGTERM', stop); process.on('SIGINT', stop);
console.log(JSON.stringify({ ready: true, socket: driver.socket }));
