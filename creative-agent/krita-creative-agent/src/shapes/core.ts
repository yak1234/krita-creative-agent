// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The shape worker's work, apart from the process around it (worker.ts) and the runtime under it (onnx.ts, or a fake in
// the tests): load the model on the first provider that works, study a reference once (the vision encoder), then answer
// each prompt with the decoder's best mask, its bounds and a crop. Every reply carries {ms, peak_mb, provider}; peak_mb
// is this process's own peak resident memory, so in the worker it is the model's cost, not the companion's.
import { checkPrompt, cropMask, decoderPrompt, maskBounds, maskFromLogits, normalise, type Box, type ShapePrompt } from './image.ts';

export type Provider = 'cuda' | 'dml' | 'cpu';
export type Tensor = { name: string; data: Float32Array; dims: readonly number[] };
export type DecoderFeed = ReturnType<typeof decoderPrompt>;
/** A loaded model: what a runtime (ONNX Runtime, or a test's fake) gives the worker. */
export interface LoadedModel {
  encode(pixelValues: Float32Array): Promise<Tensor[]>;
  /** Scores of the 3 candidate masks, their logits (3 x maskSize x maskSize) and the mask side. */
  decode(feed: DecoderFeed, embeddings: Tensor[]): Promise<{ iou: Float32Array; masks: Float32Array; maskSize: number }>;
}
export interface ShapeRuntime { load(modelDir: string, provider: Provider): Promise<LoadedModel> }

/** A study: the reference as its 1024 square of RGB (image.ts squareRgb) and its own size, for the masks and prompts. */
export type StudyRequest = { op: 'study'; image_id: string; width: number; height: number; square: Uint8Array };
export type ShapeRequest = { op: 'shape'; image_id: string; prompt: ShapePrompt };
export type ForgetRequest = { op: 'forget'; image_id: string };
export type WorkerRequest = StudyRequest | ShapeRequest | ForgetRequest;
export type Timing = { ms: number; peak_mb: number; provider: string };
export type StudyReply = Timing & { load_ms: number; studied: boolean };
export type ShapeReply = Timing & { score: number; bounds: Box | null; mask: Uint8Array };

/** Studies a worker keeps (~17 MB of embeddings each for base-plus): as many as the service keeps references and the
 * chat keeps studies (use.ts SHAPE_STUDIES), so the three never disagree about what is studied. */
export const KEPT_STUDIES = 4;

/** Accelerators in the order they are tried: CUDA (NVIDIA, Linux), DirectML (Windows), then the CPU everywhere. On a
 * Mac the CPU is the default: CoreML was slower for EdgeTAM and fails on SAM 2.1 (an ONNX Runtime CoreML shape error). */
export function providerOrder(platform: NodeJS.Platform = process.platform): Provider[] {
  return platform === 'linux' ? ['cuda', 'cpu'] : platform === 'win32' ? ['dml', 'cpu'] : ['cpu'];
}

/** This process's peak resident memory in MB (maxRSS is in kilobytes on every platform). */
export function peakMb(): number { return Math.round(process.resourceUsage().maxRSS / 1024); }

export class WorkerError extends Error {
  readonly code: string;
  constructor(code: string, message: string) { super(message); this.code = code; }
}

export function workerCore(runtime: ShapeRuntime, { modelDir, platform = process.platform, memory = peakMb }:
  { modelDir: string; platform?: NodeJS.Platform; memory?: () => number }) {
  let loaded: Promise<{ model: LoadedModel; provider: Provider; ms: number }> | null = null;
  const studies = new Map<string, { width: number; height: number; embeddings: Tensor[] }>();

  async function load() {
    const started = performance.now(), failures: string[] = [];
    for (const provider of providerOrder(platform)) {
      try { return { model: await runtime.load(modelDir, provider), provider, ms: performance.now() - started }; }
      catch (error) { failures.push(`${provider}: ${(error as Error).message}`); }
    }
    throw new WorkerError('load_failed', 'The shape model could not be loaded (' + failures.join('; ') + ').');
  }
  const model = () => (loaded ??= load().catch(error => { loaded = null; throw error; }));

  async function study({ image_id, width, height, square }: StudyRequest): Promise<StudyReply> {
    const started = performance.now(), first = !loaded, { model: m, provider, ms } = await model();
    const load_ms = first ? Math.round(ms) : 0;      // the first study pays for loading the model; it is in ms too
    const known = studies.get(image_id);
    if (known) {                                     // studied already: now the most recent, the last to be dropped
      studies.delete(image_id); studies.set(image_id, known);
      return { ms: performance.now() - started, load_ms, studied: false, peak_mb: memory(), provider };
    }
    const embeddings = await m.encode(normalise(square));
    // One throwaway decode: ONNX Runtime's first run of a session is about twice as slow (56 ms against 14-25 ms measured).
    await m.decode(decoderPrompt({ box: [0, 0, width, height] }, width, height), embeddings);
    studies.set(image_id, { width, height, embeddings });
    while (studies.size > KEPT_STUDIES) studies.delete(studies.keys().next().value as string);
    return { ms: performance.now() - started, load_ms, studied: true, peak_mb: memory(), provider };
  }

  async function shape({ image_id, prompt }: ShapeRequest): Promise<ShapeReply> {
    const started = performance.now(), studied = studies.get(image_id);
    if (!studied) throw new WorkerError('not_studied', 'This reference has not been studied in this worker.');
    const { model: m, provider } = await model();
    checkPrompt(prompt, studied.width, studied.height);
    const { iou, masks, maskSize } = await m.decode(decoderPrompt(prompt, studied.width, studied.height), studied.embeddings);
    let best = 0;
    for (let i = 1; i < iou.length; i++) if ((iou[i] ?? -Infinity) > (iou[best] ?? -Infinity)) best = i;
    const plane = maskSize * maskSize;
    const mask = maskFromLogits(masks.subarray(best * plane, (best + 1) * plane), maskSize, studied.width, studied.height);
    const bounds = maskBounds(mask, studied.width, studied.height);
    return { score: iou[best] ?? 0, bounds, mask: bounds ? cropMask(mask, studied.width, bounds) : new Uint8Array(0),
      ms: performance.now() - started, peak_mb: memory(), provider };
  }

  return {
    handle(request: WorkerRequest): Promise<StudyReply | ShapeReply | { forgotten: boolean }> {
      if (request.op === 'study') return study(request);
      if (request.op === 'shape') return shape(request);
      if (request.op === 'forget') return Promise.resolve({ forgotten: studies.delete(request.image_id) });
      return Promise.reject(new WorkerError('invalid', 'Unknown shape worker request.'));
    },
  };
}
