// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The sharpening worker's work, apart from its process (worker.ts) and the runtime under it (onnx.ts, or a fake in the
// tests): load the model on the first provider that works, cut the picture into tiles (image.ts), run each tile and
// stitch the 4x results, then write three files: the whole 4x picture, the reference-size copy (the most pixels the
// reference tools read) and the side-by-side crop for the artist. Every reply carries {ms, peak_mb, provider}; peak_mb is
// this process's own peak resident memory, so in the worker it is the sharpening's cost, not the companion's.
// An accelerator is trusted only once its first tile matches the CPU's (within MATCH of a level); otherwise, or when it
// fails mid-way, the rest runs on the CPU.
import { writeFile } from 'node:fs/promises';
import { compareImage, detailCrop, placeTile, referenceSize, resizeRgb, rgbFromRgba, tileInput, tilePlan } from './image.ts';
import { encodeRgb } from './png.ts';

export type Provider = 'coreml' | 'cuda' | 'dml' | 'cpu';
/** One loaded session: a 128-pixel RGB tile (channels first, 0..1) in, its 4x tile out. */
export interface UpscaleSession { run(tile: Float32Array): Promise<Float32Array> }
export interface UpscaleRuntime { load(modelDir: string, provider: Provider): Promise<UpscaleSession> }

export type UpscaleOutputs = { full: string; reference: string; compare: string };
/** max_pixels / max_bytes: what the reference tools read; the reference copy is the 4x picture itself when it fits. */
export type UpscaleRequest = { op: 'upscale'; rgba: Uint8Array; width: number; height: number; outputs: UpscaleOutputs; max_pixels: number; max_bytes?: number;
  tile?: number; pad?: number; scale?: number; compare_size?: number };
export type UpscaleReply = { ms: number; load_ms: number; peak_mb: number; provider: Provider; tiles: number; ms_per_tile: number;
  full: { width: number; height: number }; reference: { width: number; height: number; path: string; bytes: number }; compare: { width: number; height: number; crop: [number, number, number] } };
export type Progress = (done: number, total: number) => void;

/** The most goal pixels the worker sharpens (the 4x picture is 16 times this, 3 bytes a pixel): a larger request is refused. */
export const MAX_INPUT_PIXELS = 2_000_000;
export const TILE_PAD = 10;            // input pixels of context each side of a tile's core (40 output pixels cut away)
export const MATCH = 2 / 255;          // an accelerator's first tile may differ from the CPU's by this much at most
const COMPARE_SIZE = 480;              // each half of the side-by-side

/** Accelerators in the order they are tried: Core ML on a Mac (measured 35x the CPU on Real-ESRGAN, the same pixels within
 * a third of a level; unlike SAM 2.1, which fails on it), CUDA on Linux, DirectML on Windows, then the CPU everywhere. */
export function upscaleProviders(platform: NodeJS.Platform = process.platform): Provider[] {
  return platform === 'darwin' ? ['coreml', 'cpu'] : platform === 'linux' ? ['cuda', 'cpu'] : platform === 'win32' ? ['dml', 'cpu'] : ['cpu'];
}

export function peakMb(): number { return Math.round(process.resourceUsage().maxRSS / 1024); }

export class UpscaleWorkerError extends Error {
  readonly code: string;
  constructor(code: string, message: string) { super(message); this.code = code; }
}

const largest = (a: Float32Array, b: Float32Array) => { let most = 0; for (let i = 0; i < a.length; i++) most = Math.max(most, Math.abs((a[i] ?? 0) - (b[i] ?? 0))); return most; };

export function upscaleCore(runtime: UpscaleRuntime, { modelDir, platform = process.platform, memory = peakMb }:
  { modelDir: string; platform?: NodeJS.Platform; memory?: () => number }) {
  const sessions = new Map<Provider, Promise<UpscaleSession>>();
  const session = (provider: Provider) => {
    let loaded = sessions.get(provider);
    if (!loaded) { loaded = runtime.load(modelDir, provider); sessions.set(provider, loaded); loaded.catch(() => sessions.delete(provider)); }
    return loaded;
  };

  async function upscale(request: UpscaleRequest, progress: Progress): Promise<UpscaleReply> {
    const { width, height, outputs } = request, tile = request.tile ?? 128, pad = request.pad ?? TILE_PAD, scale = request.scale ?? 4;
    if (!(Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0) || request.rgba?.length !== width * height * 4)
      throw new UpscaleWorkerError('invalid', 'Invalid goal pixels for their size.');
    if (width * height > MAX_INPUT_PIXELS) throw new UpscaleWorkerError('invalid', `The goal image is too large to sharpen here (${width} x ${height}; at most ${MAX_INPUT_PIXELS / 1e6} million pixels).`);
    const started = performance.now(), failures: string[] = [];
    let provider: Provider | null = null, current: UpscaleSession | null = null;
    for (const candidate of upscaleProviders(platform)) {
      try { current = await session(candidate); provider = candidate; break; }
      catch (error) { failures.push(`${candidate}: ${(error as Error).message}`); }
    }
    if (!current || !provider) throw new UpscaleWorkerError('load_failed', 'The sharpening model could not be loaded (' + failures.join('; ') + ').');
    const load_ms = Math.round(performance.now() - started);
    const rgb = rgbFromRgba(request.rgba, width, height), W = width * scale, H = height * scale, out = new Uint8Array(W * H * 3);
    const plan = tilePlan(width, height, { tile, pad }), tilesStarted = performance.now();
    for (const [n, cell] of plan.entries()) {
      const input = tileInput(rgb, width, height, cell, tile);
      let result: Float32Array;
      try {
        result = await current.run(input);
        if (n === 0 && provider !== 'cpu') {                // trust an accelerator once its first tile matches the CPU's
          const cpu = await (await session('cpu')).run(input);
          if (largest(result, cpu) > MATCH) { provider = 'cpu'; current = await session('cpu'); result = cpu; }
        }
      } catch (error) {
        if (provider === 'cpu') throw error;
        provider = 'cpu'; current = await session('cpu'); result = await current.run(input);
      }
      placeTile(out, W, result, cell, tile, scale);
      progress(n + 1, plan.length);
    }
    const ms_per_tile = Math.round((performance.now() - tilesStarted) / plan.length);
    const full = encodeRgb(W, H, out, 1);                              // tens of MB: written fast (zlib level 1)
    await writeFile(outputs.full, full);
    // The reference copy: the 4x picture itself when the reference tools read it whole, else the largest smaller one that
    // fits their pixels and file size.
    let [rw, rh] = referenceSize(W, H, request.max_pixels), file = full;
    for (let tries = 0; ; tries++) {
      file = rw === W && rh === H ? full : encodeRgb(rw, rh, resizeRgb(out, W, H, rw, rh), 1);
      if (!request.max_bytes || file.length <= request.max_bytes) break;
      if (tries >= 12) throw new UpscaleWorkerError('failed', 'Sharpening failed: the sharpened goal does not fit the reference tools\u2019 file size');
      [rw, rh] = referenceSize(W, H, Math.floor(rw * rh * 0.7));
    }
    const referencePath = file === full ? outputs.full : outputs.reference;
    if (file !== full) await writeFile(outputs.reference, file);
    const side = Math.max(16, Math.min(width, height, Math.round(Math.min(width, height) / 4)));
    const crop = detailCrop(rgb, width, height, side), compare = compareImage(rgb, width, out, scale, crop, request.compare_size ?? COMPARE_SIZE);
    await writeFile(outputs.compare, encodeRgb(compare.width, compare.height, compare.data));
    return { ms: Math.round(performance.now() - started), load_ms, peak_mb: memory(), provider, tiles: plan.length, ms_per_tile,
      full: { width: W, height: H }, reference: { width: rw, height: rh, path: referencePath, bytes: file.length }, compare: { width: compare.width, height: compare.height, crop } };
  }

  return {
    handle(request: UpscaleRequest, progress: Progress = () => {}): Promise<UpscaleReply> {
      if (request?.op !== 'upscale') return Promise.reject(new UpscaleWorkerError('invalid', 'Unknown sharpening worker request.'));
      return upscale(request, progress);
    },
  };
}
