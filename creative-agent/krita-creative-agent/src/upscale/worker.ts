// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The sharpening worker process (started by index.ts's forkUpscaler; a release bundles it as src/upscale-worker.mjs): ONNX
// Runtime and Real-ESRGAN live here, one job per process, so what they take is freed when it exits. It reports each
// tile ({id, progress: [done, total]}), then the result, and exits; it also exits when the companion goes.
//   node worker.ts --model DIR [--runtime MODULE]   (MODULE: a test's stand-in for ONNX Runtime)
import { pathToFileURL } from 'node:url';
import { upscaleCore, type UpscaleRequest, type UpscaleRuntime } from './core.ts';

function option(name: string): string | undefined {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

const modelDir = option('--model'), runtimeModule = option('--runtime');
if (!process.send || !modelDir) { console.error('The sharpening worker runs as a child process of the companion.'); process.exit(2); }

const core = (async () => {
  const runtime: UpscaleRuntime = runtimeModule ? (await import(pathToFileURL(runtimeModule).href)).default
    : await (await import('./onnx.ts')).onnxUpscaler();
  return upscaleCore(runtime, { modelDir });
})();
core.catch(() => {});                                // reported to the request below

process.on('message', async (message: { id: number } & UpscaleRequest) => {
  try {
    const result = await (await core).handle(message, (done, total) => process.send?.({ id: message.id, progress: [done, total] }));
    process.send?.({ id: message.id, ok: true, result }, undefined, {}, () => process.exit(0));
  } catch (error) {
    const failure = error as Error & { code?: string };
    process.send?.({ id: message.id, ok: false, error: { code: typeof failure.code === 'string' ? failure.code : 'failed', message: failure.message } }, undefined, {}, () => process.exit(0));
  }
});
process.on('disconnect', () => process.exit(0));
