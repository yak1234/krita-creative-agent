// @ts-check
// Python for image work (crop, resize, cut-outs, colour matching) that runs the same on every
// platform: Pyodide in a child Node process locked down with Node's permission model. The child gets
// no environment (no keys), may read only Pyodide, the package cache and one work folder, and may
// write only the work folder and the cache. Python inside it has an empty `js` module.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, readdirSync, realpathSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { storagePaths } from './storage-paths.mjs';

const RUNNER = realpathSync(fileURLToPath(new URL('./pyodide-runner.mjs', import.meta.url)));
export const PYTHON_PACKAGES = ['numpy', 'pillow'];
export const PYTHON_TIMEOUT_MS = 120_000;

export function pyodidePaths() {
  const entry = createRequire(import.meta.url).resolve('pyodide');
  const directory = dirname(entry);
  // The release ships the packages it needs beside the companion; a checkout caches them on first use.
  const bundled = fileURLToPath(new URL('../pyodide-packages/', import.meta.url));
  const hasWheels = dir => existsSync(dir) && readdirSync(dir).some(name => name.startsWith('numpy-'));
  const cache = hasWheels(bundled) ? bundled : join(storagePaths().cache, 'pyodide-packages');
  return { directory, module: join(directory, 'pyodide.mjs'), cache };
}

// mounts: [{root, at}] read-only folders (Node grants read, not write), e.g. a skill's scripts at /skill.
export async function runPython({ code, args = {}, work, mounts = [], packages = PYTHON_PACKAGES, timeoutMs = PYTHON_TIMEOUT_MS, signal, paths = pyodidePaths() }) {
  if (!work || !existsSync(work)) throw new Error('The Python work folder does not exist.');
  mkdirSync(paths.cache, { recursive: true });
  // Node checks permissions against real paths (macOS temp folders sit behind /var -> /private/var).
  work = realpathSync(work); mounts = mounts.map(m => ({ ...m, root: realpathSync(m.root) }));
  paths = { ...paths, directory: realpathSync(paths.directory), cache: realpathSync(paths.cache) };
  paths.module = join(paths.directory, 'pyodide.mjs');
  const flags = ['--permission', '--allow-fs-read=' + RUNNER, '--allow-fs-read=' + paths.directory,
    '--allow-fs-read=' + paths.cache, '--allow-fs-write=' + paths.cache, '--allow-fs-read=' + work, '--allow-fs-write=' + work, ...mounts.map(m => '--allow-fs-read=' + m.root)];
  return await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [...flags, RUNNER], { env: {}, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    const finish = error => { clearTimeout(timer); signal?.removeEventListener('abort', abort); if (error) reject(error); };
    const timer = setTimeout(() => { child.kill('SIGKILL'); finish(new Error('Python took longer than ' + Math.round(timeoutMs / 1000) + ' s and was stopped.')); }, timeoutMs);
    const abort = () => { child.kill('SIGKILL'); finish(new Error('Python was stopped.')); };
    signal?.addEventListener('abort', abort, { once: true });
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', finish);
    child.on('close', () => {
      finish();
      const line = stdout.trim().split('\n').at(-1);
      try {
        const reply = JSON.parse(line);
        if (reply.ok) resolve(reply);
        else reject(Object.assign(new Error('Python failed: ' + reply.error), { output: reply.output }));
      } catch { reject(new Error('Python did not answer: ' + (stderr || stdout).trim().slice(-600))); }
    });
    child.stdin.end(JSON.stringify({ pyodide: paths.module, cache: paths.cache, work, mounts, packages, code, args }));
  });
}
