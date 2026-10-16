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
const child = spawn(process.execPath, ['--test', ...process.argv.slice(2), ...tests], {
  cwd: root, stdio: 'inherit', env: { ...process.env, TMPDIR: scratch, TMP: scratch, TEMP: scratch } });
const stop = signal => child.kill(signal);
process.on('SIGINT', stop); process.on('SIGTERM', stop);
const code = await new Promise(resolve => child.on('close', (status, signal) => resolve(status ?? (signal ? 1 : 0))));
await rm(scratch, { recursive: true, force: true, maxRetries: 3 });
process.exit(code);
