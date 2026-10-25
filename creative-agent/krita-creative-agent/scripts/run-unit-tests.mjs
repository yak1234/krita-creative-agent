// Runs the unit tests with a private temporary directory and removes it afterwards,
// whatever the outcome. Tests that leak temporary folders (or stop before their own
// cleanup) can then never fill the disk: everything they write lives under TMPDIR.
//   node scripts/run-unit-tests.mjs [extra node --test arguments]
import { spawn } from 'node:child_process';
import { mkdtemp, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const scratch = await mkdtemp(join(tmpdir(), 'creative-agent-tests-'));
const tests = (await readdir(join(root, 'tests'))).filter(f => f.endsWith('.test.mjs')).map(f => join('tests', f));
// No test may wait forever (a shapes-chat test once raced its own 10 ms tick under load and hung the suite for 35 minutes):
// a test without its own timeout fails after TEST_TIMEOUT_MS. Tests that need longer set { timeout } themselves.
const TEST_TIMEOUT_MS = 120000;
// Provider keys stay out of the tests: with the artist's own OPENROUTER_API_KEY in the shell a fake chat saw real routes as
// connected (the default planner, Qwen3 VL, took over plan turns). A test that needs a key sets its own.
const hermetic = env => Object.fromEntries(Object.entries(env).filter(([name]) => !/_API_KEY$|^(AWS|AZURE)_/.test(name)));
const child = spawn(process.execPath, ['--test', `--test-timeout=${TEST_TIMEOUT_MS}`, ...process.argv.slice(2), ...tests], {
  cwd: root, stdio: 'inherit', env: { ...hermetic(process.env), TMPDIR: scratch, TMP: scratch, TEMP: scratch } });
const stop = signal => child.kill(signal);
process.on('SIGINT', stop); process.on('SIGTERM', stop);
const code = await new Promise(resolve => child.on('close', (status, signal) => resolve(status ?? (signal ? 1 : 0))));
await rm(scratch, { recursive: true, force: true, maxRetries: 3 });
process.exit(code);
