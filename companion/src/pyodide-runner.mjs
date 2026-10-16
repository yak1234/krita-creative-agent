// Runs one Python job in Pyodide inside a Node process started with --permission (see python-sandbox.mjs).
// Python sees an empty `js` module (no process, no fetch) and a WebAssembly filesystem; only the job's
// work folder is mounted, at /work. Node's permission model limits even this process to Pyodide's files,
// the package cache and the work folder, so a script cannot reach keys, the painting or the network
// through JavaScript either. Not bundled: the release ships it beside main.mjs.
// Job on stdin: {pyodide, cache, work, mounts, packages, code, args}; mounts are read-only folders (a skill's scripts at /skill). One JSON line on stdout: {ok, result, output} or {ok:false, error, output}.
import { constants, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';

// Pyodide's NODEFS reads the fs flag constants through process.binding, which --permission refuses.
process.binding = name => { if (name === 'constants') return { fs: constants }; throw new Error('process.binding is not available'); };

let input = '';
for await (const chunk of process.stdin) input += chunk;
const job = JSON.parse(input);
const output = [];
const reply = value => process.stdout.write(JSON.stringify({ ...value, output: output.join('\n').slice(-8000) }) + '\n');
// Verify the lock instead of assuming it: a runtime can accept --permission and ignore it (Bun 1.4 read
// ~/.pi/agent/auth.json with it on). If the home folder is readable, nothing runs.
let unlocked = false;
try { readdirSync(homedir()); unlocked = true; } catch { /* refused: the permission lock is on */ }
if (unlocked) { reply({ ok: false, error: 'The Python sandbox is not locked (this runtime ignored its permissions); nothing was run.' }); process.exit(0); }
try {
  const { loadPyodide } = await import(pathToFileURL(job.pyodide).href);
  const py = await loadPyodide({ jsglobals: {}, packageCacheDir: job.cache, stdout: line => output.push(line), stderr: line => output.push(line) });
  if (job.packages?.length) await py.loadPackage(job.packages, { messageCallback: () => {}, errorCallback: line => output.push(line) });
  py.FS.mkdir('/work');
  py.FS.mount(py.FS.filesystems.NODEFS, { root: job.work }, '/work');
  for (const { root, at } of job.mounts ?? []) { py.FS.mkdirTree(at); py.FS.mount(py.FS.filesystems.NODEFS, { root }, at); }
  if (job.mounts?.length) py.runPython('import sys\n' + job.mounts.map(m => 'sys.path.insert(0, ' + JSON.stringify(m.at) + ')').join('\n'));
  py.globals.set('ARGS', py.toPy(job.args ?? {}));
  await py.runPythonAsync(job.code);
  const result = py.globals.get('RESULT');
  reply({ ok: true, result: result?.toJs ? result.toJs({ dict_converter: Object.fromEntries }) : (result ?? null) });
} catch (error) {
  reply({ ok: false, error: String(error?.message ?? error).split('\n').filter(Boolean).slice(-6).join('\n') });
}
