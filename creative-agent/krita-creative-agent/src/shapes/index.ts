// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes (openspec/changes/element-shapes): the exact pixels of one named element of a reference (the tower, the
// moon) from a rough box or a few points, found by SAM 2.1 base-plus in a short-lived worker process (worker.ts).
//
//   const shapes = shapeService({ modelDir, cacheDir, onTiming });
//   await shapes.study(referenceHash, rgba, width, height);      // the image encoder, once per reference while the worker lives
//   const tower = await shapes.shape(referenceHash, { box: [282, 24, 201, 354] });
//   // -> { bounds, score, mask_path (8-bit PNG, 255 inside, cropped to bounds), model, revision, ms, peak_mb, provider, cached }
//   await shapes.close();
//
// - The image id is the reference's content hash: shapes are cached in `cacheDir` (the chat folder) by (image id, model
//   revision, prompt), so a repeat prompt never runs the model, even in a later companion, and needs no model at all.
// - The worker keeps what it studied while it lives (never on disk) and exits after `idleMs` idle, freeing its memory.
//   The service keeps the pixels of the last few references studied, so a fresh worker can study them again by itself.
// - A failure is retried once with a fresh worker; a second one is a ShapeError whose message the panel can show as it
//   is ("Finding shapes ran out of memory. Close some apps and try again."). There is never another model.
// - Every study and shape reports {ms, peak_mb, provider}, also through `onTiming`; peak_mb is the worker's own peak.
import { fork, type ChildProcess } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkPrompt, squareRgb, type Box, type ShapePrompt } from './image.ts';
import { encodePlane } from './png.ts';
import type { ShapeReply, StudyReply, WorkerRequest } from './core.ts';
import { SHAPES_MODEL } from './model.ts';

export type { ShapePrompt, Box } from './image.ts';
export type ShapeResult = { bounds: Box; score: number; mask_path: string; model: string; revision: string;
  ms: number; peak_mb: number; provider: string; cached: boolean; attempt?: number };
export type StudyResult = { ms: number; load_ms: number; peak_mb: number; provider: string; studied: boolean; attempt: number };
export type ShapeTiming = { kind: 'study' | 'shape'; image_id: string; ms: number; peak_mb: number; provider: string;
  model: string; revision: string; attempt?: number; cached?: boolean; load_ms?: number; score?: number };
export interface ShapeService {
  study(imageId: string, rgba: Uint8Array, width: number, height: number): Promise<StudyResult>;
  shape(imageId: string, prompt: ShapePrompt): Promise<ShapeResult>;
  /** Drops a reference: its kept square here and its study in the worker (never starts one). */
  forget(imageId: string): Promise<void>;
  /** Stops the worker and cancels what waits or runs, without waiting for it. The service can be used again. */
  close(): Promise<void>;
}
/** The worker as the service sees it: forkWorker's child process, or a test's stand-in. */
export type WorkerLink = {
  call(request: WorkerRequest): Promise<unknown>;
  close(): void;
  onExit(listener: (info: { code?: number | null; signal?: string | null; message?: string }) => void): void;
};
export type ShapeServiceDeps = {
  /** The model's folder; called only when a worker starts (a cached shape needs no model, so no download). */
  modelDir: () => Promise<string>;
  /** Where shapes are cached: the chat folder's shapes folder. */
  cacheDir: () => string;
  model?: { name: string; revision: string };
  spawn?: (modelDir: string) => WorkerLink;
  idleMs?: number;
  onTiming?: (timing: ShapeTiming) => void;
  /** The worker could not load the model: its files are checked again before the next worker (chat.ts). */
  onLoadFailed?: () => void | Promise<void>;
};

export type ShapeErrorCode = 'out_of_memory' | 'failed' | 'invalid' | 'not_studied' | 'empty' | 'declined' | 'model' | 'cancelled';
export class ShapeError extends Error {
  readonly code: ShapeErrorCode;
  constructor(code: ShapeErrorCode, message: string) { super(message); this.name = 'ShapeError'; this.code = code; }
}

/** References the service can study again by itself (a 1024 square each, 3 MB): use.ts's SHAPE_STUDIES. */
export const KEPT_REFERENCES = 4;
/** The one wording for an element with no shape where the painter pointed (the service, use.ts, the canvas). */
export const EMPTY_SHAPE = 'No shape was found there. Try a tighter box, or a point on the element itself.';
const OUT_OF_MEMORY = 'Finding shapes ran out of memory. Close some apps and try again.';

/** The plain message for a worker that failed (out of memory at once, anything else after the retry). A process killed outright (SIGKILL: macOS's memory pressure killer,
 * the Linux OOM killer) or an allocation failure is memory; anything else says what went wrong. */
export function failureError(failure: { message?: string; signal?: string | null; code?: unknown }): ShapeError {
  const text = String(failure.message ?? '');
  if (failure.signal === 'SIGKILL' || /bad_alloc|out of memory|failed to allocate|cannot allocate|ENOMEM|allocation failed/i.test(text))
    return new ShapeError('out_of_memory', OUT_OF_MEMORY);
  const reason = text.trim().split('\n')[0]?.slice(0, 200) || (failure.signal ? 'the worker stopped (' + failure.signal + ')' : 'the worker stopped');
  return new ShapeError('failed', `Finding shapes failed: ${reason.replace(/\.$/, '')}. Try again; if it fails again, export a troubleshooting report.`);
}

/** The worker's file: the TypeScript source in a checkout, or the bundled src/shapes-worker.mjs in a release. */
function workerFile(): string {
  for (const candidate of [new URL('./worker.ts', import.meta.url), new URL('./shapes-worker.mjs', import.meta.url)])
    if (existsSync(candidate)) return fileURLToPath(candidate);
  throw new ShapeError('failed', 'Finding shapes failed: the shape worker is missing from this build.');
}

/** A worker child process. `runtimeModule` replaces ONNX Runtime (tests only). */
export function forkWorker(modelDir: string, { idleMs = 60000, runtimeModule }: { idleMs?: number; runtimeModule?: string } = {}): WorkerLink {
  const args = ['--model', modelDir, '--idle-ms', String(idleMs), ...(runtimeModule ? ['--runtime', runtimeModule] : [])];
  const child: ChildProcess = fork(workerFile(), args, { serialization: 'advanced', execArgv: [], stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
  const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>(), listeners: ((info: object) => void)[] = [];
  let next = 0, stderr = '', exit: { code: number | null; signal: string | null } | null = null;
  child.stderr?.on('data', chunk => { stderr = (stderr + String(chunk)).slice(-4000); });
  // An idle worker must not keep the companion alive: the child, its IPC channel and its stderr pipe are unreferenced
  // between requests (an open pipe alone would hold the event loop), and referenced only while a request is in flight.
  const pipe = child.stderr as unknown as { ref?: () => void; unref?: () => void } | null;
  const hold = (on: boolean) => {
    if (on) { child.ref(); child.channel?.ref(); pipe?.ref?.(); } else { child.unref(); child.channel?.unref(); pipe?.unref?.(); }
  };
  hold(false);
  child.on('message', (reply: { id: number; ok: boolean; result?: unknown; error?: { code: string; message: string } }) => {
    const waiter = pending.get(reply.id); if (!waiter) return;
    pending.delete(reply.id); if (!pending.size) hold(false);
    if (reply.ok) waiter.resolve(reply.result);
    else waiter.reject(Object.assign(new Error(reply.error?.message ?? 'The shape worker failed.'), { code: reply.error?.code }));
  });
  const ended = (code: number | null, signal: string | null, message?: string) => {
    if (exit) return;
    exit = { code, signal };
    const text = message ?? (stderr.trim() || `The shape worker stopped (${signal ?? 'exit ' + code}).`);
    for (const waiter of pending.values()) waiter.reject(Object.assign(new Error(text), { signal, exit: code }));   // exit 0: idle
    pending.clear();
    for (const listener of listeners) listener({ code, signal });
  };
  child.on('exit', (code, signal) => ended(code, signal));
  child.on('error', error => ended(null, null, error.message));
  return {
    call(request) {
      if (exit) return Promise.reject(new Error('The shape worker has stopped.'));
      const id = ++next;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject }); hold(true);
        child.send({ id, ...request }, error => { if (error) { pending.delete(id); reject(error); } });
      });
    },
    close() { if (!exit) child.kill(); },
    onExit(listener) { listeners.push(listener); },
  };
}

/** Promise.withResolvers, which the type-checked library level (es2023) does not name. */
export function resolvers<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
  let resolve: (value: T) => void = () => {}, reject: (error: Error) => void = () => {};
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const canonical = (prompt: ShapePrompt) => 'box' in prompt ? { box: prompt.box } : { points: prompt.points };
type Entry = { link: WorkerLink; studied: Set<string> };
type Failure = Error & { code?: unknown; signal?: string | null; exit?: number | null };
/** An exit with code 0 is the worker's own idle exit (it raced a request): not a failure. */
const idleExit = (error: Failure) => (error.exit ?? error.code) === 0;
const cancelled = () => new ShapeError('cancelled', 'Finding shapes was stopped.');

export function shapeService(deps: ShapeServiceDeps): ShapeService {
  const model = deps.model ?? { name: SHAPES_MODEL.name, revision: SHAPES_MODEL.revision };
  const idleMs = deps.idleMs ?? 60000;
  const spawn = deps.spawn ?? ((dir: string) => forkWorker(dir, { idleMs }));
  // The parent retires an idle worker a little before the worker would exit by itself, so the two never race.
  const retireMs = Math.max(0, idleMs - Math.min(5000, idleMs / 5));
  const kept = new Map<string, { square: Uint8Array; width: number; height: number }>();
  let worker: Entry | null = null, queue: Promise<unknown> = Promise.resolve(), retire: NodeJS.Timeout | undefined;
  let stop = resolvers<never>();
  stop.promise.catch(() => {});

  /** One request at a time; close() cancels what waits or runs. */
  const serial = <T>(work: () => Promise<T>): Promise<T> => {
    const halted = stop.promise;
    const run = queue.then(() => { clearTimeout(retire); return Promise.race([work(), halted]); });
    queue = run.catch(() => {}).then(() => { clearTimeout(retire); if (worker) retire = setTimeout(drop, retireMs); retire?.unref?.(); });
    return run;
  };
  async function current(): Promise<Entry> {
    if (worker) return worker;
    const link = spawn(await deps.modelDir()), entry = { link, studied: new Set<string>() };
    link.onExit(() => { if (worker === entry) worker = null; });          // idle, killed or crashed: the next call starts afresh
    return worker = entry;
  }
  function drop() { clearTimeout(retire); worker?.link.close(); worker = null; }
  const timing = (entry: Omit<ShapeTiming, 'model' | 'revision'>) => deps.onTiming?.({ ...entry, model: model.name, revision: model.revision });

  async function studyIn(entry: Entry, imageId: string, attempt: number): Promise<StudyReply> {
    const image = kept.get(imageId);
    if (!image) throw new ShapeError('not_studied', 'Study this reference before finding its shapes.');
    const reply = await entry.link.call({ op: 'study', image_id: imageId, width: image.width, height: image.height, square: image.square }) as StudyReply;
    entry.studied.add(imageId);
    if (reply.studied) timing({ kind: 'study', image_id: imageId, ms: Math.round(reply.ms), peak_mb: reply.peak_mb, provider: reply.provider, load_ms: reply.load_ms, attempt });
    return reply;
  }
  /** Runs `work` in a worker. Out of memory is reported at once (another 1.6 GB under memory pressure could get Krita
   * killed); the worker's own idle exit restarts it without counting; any other failure is retried once, afresh. */
  async function withRetry<T>(work: (entry: Entry, attempt: number) => Promise<T>): Promise<T> {
    let restarted = false;
    for (let attempt = 1; ; attempt++) {
      try { return await work(await current(), attempt); }
      catch (error) {
        if (error instanceof ShapeError) throw error;
        drop();
        const failure = error as Failure;
        if (idleExit(failure) && !restarted) { restarted = true; attempt--; continue; }
        const plain = failureError(failure);
        if (plain.code === 'out_of_memory') throw plain;
        if (failure.code === 'load_failed') await deps.onLoadFailed?.();
        if (attempt >= 2) throw plain;
      }
    }
  }

  async function cached(key: string): Promise<ShapeResult | null> {
    try {
      const { bounds, score } = JSON.parse(await readFile(join(deps.cacheDir(), key + '.json'), 'utf8'));
      const mask_path = join(deps.cacheDir(), key + '.png');                // never a path stored in the entry
      return existsSync(mask_path) ? { bounds, score, mask_path, model: model.name, revision: model.revision, ms: 0, peak_mb: 0, provider: 'cache', cached: true } : null;
    } catch { return null; }
  }

  return {
    study(imageId, rgba, width, height) {
      if (!(width > 0 && height > 0) || rgba.length !== width * height * 4) return Promise.reject(new ShapeError('invalid', 'Invalid reference pixels for their size.'));
      kept.delete(imageId); kept.set(imageId, { square: squareRgb(rgba, width, height), width, height });
      while (kept.size > KEPT_REFERENCES) kept.delete(kept.keys().next().value as string);
      return serial(() => withRetry(async (entry, attempt) => {
        const reply = await studyIn(entry, imageId, attempt);
        return { ms: Math.round(reply.ms), load_ms: reply.load_ms, peak_mb: reply.peak_mb, provider: reply.provider, studied: reply.studied, attempt };
      }));
    },
    shape(imageId, prompt) {
      return serial(async () => {
        const started = performance.now();
        const key = createHash('sha256').update(JSON.stringify([imageId, model.name, model.revision, canonical(prompt)])).digest('hex').slice(0, 32);
        const hit = await cached(key);
        if (hit) {
          const result = { ...hit, ms: Math.round(performance.now() - started), peak_mb: 0, provider: 'cache', cached: true };
          timing({ kind: 'shape', image_id: imageId, ms: result.ms, peak_mb: 0, provider: 'cache', cached: true, score: result.score });
          return result;
        }
        const image = kept.get(imageId);
        if (!image) throw new ShapeError('not_studied', 'Study this reference before finding its shapes.');
        try { checkPrompt(prompt, image.width, image.height); }
        catch (error) { throw new ShapeError('invalid', (error as Error).message); }
        const { reply, attempt } = await withRetry(async (entry, attempt) => {
          if (!entry.studied.has(imageId)) await studyIn(entry, imageId, attempt);
          const ask = () => entry.link.call({ op: 'shape', image_id: imageId, prompt: canonical(prompt) }) as Promise<ShapeReply>;
          try { return { reply: await ask(), attempt }; }
          catch (error) {
            if ((error as Failure).code !== 'not_studied') throw error;
            entry.studied.delete(imageId);                                 // the worker dropped it: study it again, here
            await studyIn(entry, imageId, attempt);
            return { reply: await ask(), attempt };
          }
        });
        if (!reply.bounds) throw new ShapeError('empty', EMPTY_SHAPE);
        const [, , w, h] = reply.bounds;
        if (!(reply.mask instanceof Uint8Array) || reply.mask.length !== w * h)
          throw new ShapeError('failed', 'Finding shapes failed: the worker gave a shape that does not fit its bounds. Try again.');
        const directory = deps.cacheDir();
        await mkdir(directory, { recursive: true });
        const mask_path = join(directory, key + '.png');
        await writeFile(mask_path, encodePlane({ width: w, height: h, data: reply.mask }));
        const result: ShapeResult = { bounds: reply.bounds, score: Math.round(reply.score * 10000) / 10000, mask_path, model: model.name, revision: model.revision,
          ms: Math.round(reply.ms), peak_mb: reply.peak_mb, provider: reply.provider, cached: false, attempt };
        const temporary = join(directory, key + '.json.' + process.pid);
        await writeFile(temporary, JSON.stringify({ image_id: imageId, model: model.name, revision: model.revision, prompt: canonical(prompt),
          bounds: result.bounds, score: result.score, ms: result.ms, peak_mb: result.peak_mb, provider: result.provider }));
        await rename(temporary, join(directory, key + '.json'));
        timing({ kind: 'shape', image_id: imageId, ms: result.ms, peak_mb: result.peak_mb, provider: result.provider, attempt, score: result.score });
        return result;
      });
    },
    forget(imageId) {
      kept.delete(imageId);
      const entry = worker;
      if (!entry?.studied.delete(imageId)) return Promise.resolve();          // never starts a worker
      return serial(async () => { await entry.link.call({ op: 'forget', image_id: imageId }).catch(() => {}); });
    },
    async close() {
      stop.reject(cancelled());
      stop = resolvers<never>(); stop.promise.catch(() => {});
      queue = Promise.resolve();
      drop(); kept.clear();
    },
  };
}
