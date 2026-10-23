// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes for the studio's open chat (studio.mjs's `runtime.shapes`): the ShapeService of index.ts with
// - the model on first use: when it is not in the data folder yet, the panel is told its size (event shapes_model_needed)
//   and the call waits for the artist's answer (the panel's shapes_model command: accept or decline); then it is
//   downloaded with progress in the status line (model.ts: pinned, checked, resumable). No other model, ever;
// - the chat's record: the model and revision it uses (study.shapes_model), kept for the chat. A chat that recorded
//   another revision is refused rather than switched;
// - the cache in the chat folder (<chat>/shapes), and every study and shape's {ms, peak_mb, provider} in the diagnostics
//   and as a shape_timing event, which the test driver's report collects (test-companion.ts).
import { existsSync } from 'node:fs';
import { rm } from 'node:fs/promises';
import { join } from 'node:path';
import { ShapeError, resolvers, shapeService, type ShapePrompt, type ShapeResult, type ShapeService, type ShapeTiming, type StudyResult, type WorkerLink } from './index.ts';
import { SHAPES_MODEL, downloadModel, modelBytes, modelDirectory, modelReady, type ModelSpec } from './model.ts';

/** What the shapes need of the studio runtime. */
export type ChatRuntime = {
  config: { data_dir?: string; output?: string };
  study?: { id: string; directory: string; shapes_model?: { model: string; revision: string }; shapes_declined?: boolean } | undefined;
  emit(event: Record<string, unknown>): void;
  diagnostics?: { record(event: Record<string, unknown>): void } | undefined;
  persist(): Promise<unknown>;
};
export type ChatShapes = ShapeService & {
  /** The artist's answer to shapes_model_needed (accept or decline), or "enable" to allow shapes again after a decline.
   * Returns false when it changed nothing. */
  answer(action: 'accept' | 'decline' | 'enable'): boolean;
  /** The panel's Stop: a pending download question or a download in progress is cancelled. */
  stop(): void;
  /** The model is downloaded and checked, and the artist has not declined it for this chat: no question would be asked. */
  ready(): Promise<boolean>;
};
type Download = (options: { directory: string; spec: ModelSpec; onProgress?: (done: number, total: number) => void; signal?: AbortSignal }) => Promise<void>;

export function chatShapes(runtime: ChatRuntime, { spec = SHAPES_MODEL, download = downloadModel as Download, spawn, idleMs }:
  { spec?: ModelSpec; download?: Download; spawn?: (modelDir: string) => WorkerLink; idleMs?: number } = {}): ChatShapes {
  const size_mb = Math.round(modelBytes(spec) / 1e6);
  let waiting: { resolve: () => void; reject: (error: Error) => void; promise: Promise<void> } | null = null;
  let preparing: Promise<string> | null = null;
  // Stop and close abort what waits for the artist or the network; a fresh controller serves what comes after.
  let controller = new AbortController();

  const declinedError = () => new ShapeError('declined', `Finding shapes needs a one-time ${size_mb} MB download, and it was declined for this chat. `
    + 'Use "Ask again" in the panel to allow it.');
  const dataDir = () => {
    const dir = runtime.config.data_dir ?? runtime.config.output;
    if (!dir) throw new ShapeError('model', 'Finding shapes needs the companion’s data folder, and none is set.');
    return dir;
  };
  function ask(): Promise<void> {
    if (waiting) return waiting.promise;
    const { promise, resolve, reject } = resolvers<void>();
    waiting = { resolve, reject, promise };
    runtime.emit({ type: 'shapes_model_needed', model: spec.name, revision: spec.revision, licence: spec.licence, size_mb,
      message: `Finding the exact shape of an element needs a one-time download of its model, SAM 2.1 base-plus (${size_mb} MB). Download it now?` });
    return promise;
  }
  async function prepare(signal: AbortSignal): Promise<string> {
    if (runtime.study?.shapes_declined) throw declinedError();
    const directory = modelDirectory(dataDir(), spec);
    if (await modelReady(directory, spec)) return directory;
    // The folder is made only after an OK: when it exists the artist agreed already, and what is missing or damaged is
    // fetched again without asking (a resumed download, or a model the worker could not load).
    if (!existsSync(directory)) await ask();
    signal.throwIfAborted();
    let shown = -1;
    runtime.emit({ type: 'status', phase: 'downloading', message: `Downloading the shape model (${size_mb} MB)…` });
    try {
      await download({ directory, spec, signal, onProgress: (done, total) => {
        const percent = Math.floor(done / total * 100);
        if (percent >= shown + 5 || percent === 100) { shown = percent; runtime.emit({ type: 'status', phase: 'downloading', message: `Downloading the shape model: ${percent}% of ${size_mb} MB…` }); }
      } });
    } catch (error) {
      if (signal.aborted) throw new ShapeError('cancelled', 'Finding shapes was stopped; the model download resumes next time.');
      throw new ShapeError('model', 'The shape model could not be downloaded: ' + (error as Error).message);
    }
    runtime.emit({ type: 'shapes_model_ready', model: spec.name, revision: spec.revision });
    return directory;
  }
  /** The model folder, prepared once at a time; Stop or close cancels the wait at once, whatever the download does. */
  const modelDir = () => {
    const signal = controller.signal;
    preparing ??= prepare(signal).finally(() => { preparing = null; });
    const aborted = new Promise<never>((_, reject) => {
      const cancel = () => reject(new ShapeError('cancelled', 'Finding shapes was stopped.'));
      if (signal.aborted) cancel(); else signal.addEventListener('abort', cancel, { once: true });
    });
    aborted.catch(() => {});
    return Promise.race([preparing, aborted]);
  };
  function cancelAll() {
    controller.abort();
    controller = new AbortController();
    waiting?.reject(new ShapeError('cancelled', 'Finding shapes was stopped.'));
    waiting = null; preparing = null;
  }

  const chat = () => {
    const study = runtime.study;
    if (!study) throw new ShapeError('invalid', 'Finding shapes needs an open chat.');
    return study;
  };
  /** The chat's model: recorded once it has been used, and never switched. */
  function checkModel() {
    const recorded = chat().shapes_model;
    if (recorded && (recorded.model !== spec.name || recorded.revision !== spec.revision))
      throw new ShapeError('model', `This chat found its shapes with ${recorded.model} at revision ${recorded.revision}; this Toska has ${spec.name} at ${spec.revision}. Start a new chat to find shapes.`);
  }
  async function recordModel<T>(result: T): Promise<T> {
    const study = runtime.study;
    if (study && !study.shapes_model) { study.shapes_model = { model: spec.name, revision: spec.revision }; await runtime.persist(); }
    return result;
  }
  const log = (timing: ShapeTiming) => {
    const entry = { type: 'shape_timing', chat_id: runtime.study?.id ?? null, ...timing };
    runtime.diagnostics?.record(entry);
    runtime.emit(entry);
  };
  const service = shapeService({ modelDir, cacheDir: () => join(chat().directory, 'shapes'), model: { name: spec.name, revision: spec.revision },
    onTiming: log, onLoadFailed: () => rm(join(modelDirectory(dataDir(), spec), 'verified.json'), { force: true }), ...(spawn ? { spawn } : {}), ...(idleMs ? { idleMs } : {}) });

  return {
    async study(imageId: string, rgba: Uint8Array, width: number, height: number): Promise<StudyResult> {
      checkModel();
      return recordModel(await service.study(imageId, rgba, width, height));
    },
    async shape(imageId: string, prompt: ShapePrompt): Promise<ShapeResult> {
      checkModel();
      return recordModel(await service.shape(imageId, prompt));
    },
    forget: imageId => service.forget(imageId),
    answer(action) {
      if (action === 'enable') {
        const study = runtime.study;
        if (!study?.shapes_declined) return false;
        delete study.shapes_declined; void runtime.persist();
        return true;
      }
      const pending = waiting;
      if (!pending) return false;
      waiting = null;
      if (action === 'accept') { pending.resolve(); return true; }
      const study = runtime.study;
      if (study) { study.shapes_declined = true; void runtime.persist(); }      // for this chat, until "Ask again"
      pending.reject(declinedError());
      return true;
    },
    stop() { cancelAll(); },
    async ready() {
      if (runtime.study?.shapes_declined) return false;
      try { return await modelReady(modelDirectory(dataDir(), spec), spec); } catch { return false; }
    },
    async close() {
      cancelAll();
      await service.close();
    },
  };
}
