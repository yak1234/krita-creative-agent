// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The shape worker process (started by index.ts's forkWorker; a release bundles it as src/shapes-worker.mjs): ONNX
// Runtime and SAM 2.1 base-plus live here, so the ~1.6 GB they take is freed when this short-lived process exits. It
// answers one request at a time over the IPC channel and exits after `--idle-ms` without one, or when the companion goes.
//   node worker.ts --model DIR [--idle-ms 60000] [--runtime MODULE]   (MODULE: a test's stand-in for ONNX Runtime)
import { pathToFileURL } from 'node:url';
import { workerCore, type ShapeRuntime, type WorkerRequest } from './core.ts';

function option(name: string): string | undefined {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

const modelDir = option('--model'), idleMs = Number(option('--idle-ms') ?? 60000), runtimeModule = option('--runtime');
if (!process.send || !modelDir) { console.error('The shape worker runs as a child process of the companion.'); process.exit(2); }

// The handler is in place before the runtime loads, so no request that arrives meanwhile is lost.
const core = (async () => {
  const runtime: ShapeRuntime = runtimeModule ? (await import(pathToFileURL(runtimeModule).href)).default
    : await (await import('./onnx.ts')).onnxRuntime();
  return workerCore(runtime, { modelDir });
})();
core.catch(() => {});                                // reported to each request below

let timer: NodeJS.Timeout | undefined, queue = Promise.resolve(), pending = 0;
const idle = () => { clearTimeout(timer); timer = setTimeout(() => process.exit(0), idleMs); };
process.on('message', (message: { id: number } & WorkerRequest) => {
  clearTimeout(timer); pending++;
  queue = queue.then(async () => {
    try { process.send?.({ id: message.id, ok: true, result: await (await core).handle(message) }); }
    catch (error) {
      const failure = error as Error & { code?: string };
      process.send?.({ id: message.id, ok: false, error: { code: typeof failure.code === 'string' ? failure.code : 'failed', message: failure.message } });
    }
    if (--pending === 0) idle();
  });
});
process.on('disconnect', () => process.exit(0));
idle();
