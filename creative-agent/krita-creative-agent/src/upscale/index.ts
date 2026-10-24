// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Sharpen a picture 4x (Real-ESRGAN x4plus, model.ts) in a worker process of its own, one job per process:
//
//   const sharpen = upscaleService({ modelDir: async () => dir });
//   const reply = await sharpen.upscale({ rgba, width, height, outputs: { full, reference, compare }, max_pixels }, { onProgress, signal });
//   // -> { full, reference, compare sizes, tiles, ms, load_ms, ms_per_tile, peak_mb, provider }
//
// - The worker writes the three PNGs itself (the 4x picture is tens of MB: it never crosses the IPC channel).
// - An abort kills the worker at once: an UpscaleError 'cancelled', nothing half-written is used (the caller checks).
// - A worker killed outright or out of memory is 'out_of_memory'; anything else 'failed', with what went wrong.
import { fork } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { UpscaleReply, UpscaleRequest } from './core.ts';

export type { UpscaleReply, UpscaleOutputs } from './core.ts';
export type UpscaleInput = Omit<UpscaleRequest, 'op'>;
export type UpscaleErrorCode = 'cancelled' | 'out_of_memory' | 'failed' | 'model';
export class UpscaleError extends Error {
  readonly code: UpscaleErrorCode;
  constructor(code: UpscaleErrorCode, message: string) { super(message); this.name = 'UpscaleError'; this.code = code; }
}
/** The worker as the service sees it: forkUpscaler's child process, or a test's stand-in. */
export type UpscaleLink = { run(request: UpscaleRequest, onProgress: (done: number, total: number) => void): Promise<UpscaleReply>; kill(): void };
export interface UpscaleService {
  upscale(input: UpscaleInput, options?: { onProgress?: (done: number, total: number) => void; signal?: AbortSignal }): Promise<UpscaleReply>;
}

const OUT_OF_MEMORY = 'Sharpening ran out of memory. Close some apps and try again.';
const stopped = () => new UpscaleError('cancelled', 'Sharpening was stopped.');

/** The plain message for a worker that failed. */
export function upscaleFailure(failure: { message?: string; signal?: string | null; code?: unknown }): UpscaleError {
  const text = String(failure.message ?? '');
  if (failure.signal === 'SIGKILL' || /bad_alloc|out of memory|failed to allocate|cannot allocate|ENOMEM|allocation failed/i.test(text))
    return new UpscaleError('out_of_memory', OUT_OF_MEMORY);
  if (failure.code === 'load_failed') return new UpscaleError('model', text.slice(0, 300));
  const reason = text.trim().split('\n')[0]?.slice(0, 200) || 'the worker stopped' + (failure.signal ? ' (' + failure.signal + ')' : '');
  return new UpscaleError('failed', `Sharpening failed: ${reason.replace(/\.$/, '')}.`);
}

/** The worker's file: the TypeScript source in a checkout, or the bundled src/upscale-worker.mjs in a release. */
function workerFile(): string {
  for (const candidate of [new URL('./worker.ts', import.meta.url), new URL('./upscale-worker.mjs', import.meta.url)])
    if (existsSync(candidate)) return fileURLToPath(candidate);
  throw new UpscaleError('failed', 'Sharpening failed: the sharpening worker is missing from this build.');
}

/** One job in a fresh child process. `runtimeModule` replaces ONNX Runtime (tests only). */
export function forkUpscaler(modelDir: string, { runtimeModule }: { runtimeModule?: string } = {}): UpscaleLink {
  const child = fork(workerFile(), ['--model', modelDir, ...(runtimeModule ? ['--runtime', runtimeModule] : [])],
    { serialization: 'advanced', execArgv: [], stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
  let stderr = '';
  child.stderr?.on('data', chunk => { stderr = (stderr + String(chunk)).slice(-4000); });
  return {
    run(request, onProgress) {
      return new Promise<UpscaleReply>((resolve, reject) => {
        let settled = false;
        const settle = (action: () => void) => { if (!settled) { settled = true; action(); } };
        child.on('message', (reply: { progress?: [number, number]; ok?: boolean; result?: UpscaleReply; error?: { code: string; message: string } }) => {
          if (reply.progress) { onProgress(reply.progress[0], reply.progress[1]); return; }
          settle(() => reply.ok && reply.result ? resolve(reply.result) : reject(upscaleFailure(reply.error ?? {})));
        });
        child.on('exit', (code, signal) => settle(() => reject(upscaleFailure({ message: stderr.trim() || `the worker stopped (${signal ?? 'exit ' + code})`, signal }))));
        child.on('error', error => settle(() => reject(upscaleFailure(error))));
        child.send({ id: 1, ...request }, error => { if (error) settle(() => reject(upscaleFailure(error))); });
      });
    },
    kill() { if (child.exitCode === null && child.signalCode === null) child.kill(); },
  };
}

export function upscaleService({ modelDir, spawn = dir => forkUpscaler(dir) }: { modelDir: () => Promise<string>; spawn?: (modelDir: string) => UpscaleLink }): UpscaleService {
  return {
    async upscale(input, { onProgress = () => {}, signal } = {}) {
      if (signal?.aborted) throw stopped();
      const link = spawn(await modelDir());
      if (signal?.aborted) { link.kill(); throw stopped(); }
      const abort = () => link.kill();
      signal?.addEventListener('abort', abort, { once: true });
      try { return await link.run({ ...input, op: 'upscale' }, onProgress); }
      catch (error) { throw signal?.aborted ? stopped() : error instanceof UpscaleError ? error : upscaleFailure(error as Error); }
      finally { signal?.removeEventListener('abort', abort); link.kill(); }
    },
  };
}
