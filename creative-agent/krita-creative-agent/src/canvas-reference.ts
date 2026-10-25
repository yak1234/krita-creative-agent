// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// /canvas-reference (openspec canvas-reference; the artist, 2026-10-25: "it uses the chatgpt image generation to take image
// of canvas say dostoevsky's painting … what would happen if we added more ghosts, ghost-like lighting, or more snow and
// crisp effects … not make the edits but make a reference generation of what the edit would look like. That way the agent
// has a visual of what it would look like"). The flow:
//
//   /canvas-reference <instruction> [in <part>]
//     -> the canvas as observed goes to the image model (the `assets` setting: Codex by default) with an edit prompt that
//        keeps everything else identical; "in <part>" limits the comparison to Find it's outline of the part
//     -> a card beside the chat: the canvas and the reference side by side, the changed area outlined in red
//        [Use as the target] [Use as the new goal] [Try again] [Discard]; never answered by Auto-approve
//        (auto-approve.ts NEVER_AUTO_APPROVE); Use as the new goal only when the chat has a goal picture
//     -> Use as the target: the difference area becomes the move's Paint only here area (Krita blocks every write outside
//        it) and the move paints toward the reference there (referenceMoveNote); faces and everything outside stay.
//     -> Use as the new goal: the same move, and the change is pasted into the goal picture first (goal-edit.ts), so
//        later moves keep it; /original-goal goes back.
//
// The difference area (differenceMask), at the comparison size (the canvas view, at most MASK_RULES.side on its long side):
//   1. tone: each channel of the reference is shifted by its median difference to the canvas, then fitted to it (gain
//      0.8-1.25 and offset, least squares) over the pixels the shift found unchanged, so a model that warms, lightens or
//      flattens the whole picture changes nothing, while the change itself (a third of the picture) cannot cancel itself;
//   2. both pictures are box-blurred (MASK_RULES.blur of the long side, at least 1 px) and compared in CIELAB (ΔE76);
//   3. the ΔE is thresholded at MASK_RULES.threshold;
//   4. specks (connected pieces smaller than MASK_RULES.speck of the picture) are removed, and holes as small filled;
//   5. the area grows by MASK_RULES.dilate of the long side (at least 3 px), so the paint overlaps the change's edge;
//   6. with a part's area, only what lies inside it.
// More than WIDE_SHARE of the canvas: the card warns that the model changed a lot.
// The studio's calls come in as a small host, so this module imports no .mjs.
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { resizeBilinear } from './shapes/image.ts';
import { decodePlane, encodePlane, encodeRgb, encodeRgba, type Plane } from './shapes/png.ts';

export type Rect = [number, number, number, number];
export type Rgba = { width: number; height: number; data: Uint8Array };
export type Mask = { width: number; height: number; data: Uint8Array; share: number; bounds: Rect | null };

export const CANVAS_REFERENCE_OPTIONS = Object.freeze({ use: 'Use as the target', goal: 'Use as the new goal', retry: 'Try again', discard: 'Discard' } as const);
export type CanvasReferenceAction = keyof typeof CANVAS_REFERENCE_OPTIONS;
/** A difference over more of the canvas than this: the model changed a lot (a narrower instruction or an area helps). */
export const WIDE_SHARE = 0.6;
export const MASK_RULES = Object.freeze({
  /** The comparison's long side at most (pixels). */
  side: 1024,
  /** The blur's radius as a share of the long side. */
  blur: 0.004,
  /** ΔE76 (CIELAB) from which a pixel differs. */
  threshold: 12,
  /** Pieces (and holes) smaller than this share of the picture are specks. */
  speck: 0.002,
  /** The area grows by this share of the long side. */
  dilate: 0.01,
});
const MIN_DILATE = 3;
const REFERENCE_SIDE = 2560;
const FOLDER = 'canvas-reference';

// ----- the command ------------------------------------------------------------------------------------------------------

/** "/canvas-reference <instruction> [in the <part>]" (or /skill:canvas-reference): the instruction, and the part when the
 * message ends with "in the …" (up to five words); null for any other message. */
export function canvasReferenceRequest(text: string | undefined): { instruction: string; part: string | null } | null {
  const match = /^\/(?:skill:)?canvas-reference[.,:;!?]*(?:\s+([\s\S]*))?$/i.exec(String(text ?? '').trim());
  if (!match) return null;
  const said = (match[1] ?? '').trim().replace(/[.!]+$/, '').trim();
  const part = /^(.*\S)\s+in\s+(the\s+(?:[\p{L}\p{N}'-]+\s*){1,5})$/iu.exec(said);
  return part ? { instruction: part[1]!.trim(), part: part[2]!.trim() } : { instruction: said, part: null };
}

/** The edit prompt: the change, and everything else kept exactly. */
export function editPrompt(instruction: string, part: string | null): string {
  return `Edit this painting: ${instruction.trim()}${part ? `, only in ${part}` : ''}. Change only what this asks for. `
    + 'Keep everything else exactly as it is: the same composition and framing (do not crop, zoom, reframe or add a border), '
    + 'every figure, face and building in the same place, shape and pose, the same painting style and brushwork, the same '
    + 'palette, and the same light, except where the change asks for it.';
}

// ----- the difference area ----------------------------------------------------------------------------------------------

const labF = (t: number) => t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116;
/** CIELAB (D65) of RGB values 0-255 (fractional allowed: they are blurred), three floats a pixel. */
function lab(rgb: Float32Array): Float32Array {
  const out = new Float32Array(rgb.length), lin = (v: number) => { const c = Math.min(255, Math.max(0, v)) / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  for (let i = 0; i < rgb.length; i += 3) {
    const r = lin(rgb[i]!), g = lin(rgb[i + 1]!), b = lin(rgb[i + 2]!);
    const x = labF((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047), y = labF(0.2126 * r + 0.7152 * g + 0.0722 * b), z = labF((0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883);
    out[i] = 116 * y - 16; out[i + 1] = 500 * (x - y); out[i + 2] = 200 * (y - z);
  }
  return out;
}

/** RGB floats of an RGBA picture (alpha over white: a clear pixel is paper). */
function rgbOf(image: Rgba): Float32Array {
  const n = image.width * image.height, out = new Float32Array(n * 3);
  for (let p = 0; p < n; p++) {
    const a = image.data[p * 4 + 3]! / 255;
    for (let c = 0; c < 3; c++) out[p * 3 + c] = image.data[p * 4 + c]! * a + 255 * (1 - a);
  }
  return out;
}

/** The reference's channels shifted by the median difference to the canvas (a colour cast or a lighter picture). The
 * median, not the mean: a change over a third of the picture moves the mean, not the median of the rest. */
function shiftTone(canvas: Float32Array, reference: Float32Array): Float32Array {
  const out = new Float32Array(reference.length);
  for (let c = 0; c < 3; c++) {
    const counts = new Uint32Array(511);
    for (let i = c; i < canvas.length; i += 3) counts[Math.max(0, Math.min(510, Math.round(canvas[i]! - reference[i]!) + 255))]!++;
    let seen = 0, median = 0;
    for (let k = 0; k < 511; k++) { seen += counts[k]!; if (seen * 2 >= canvas.length / 3) { median = k - 255; break; } }
    for (let i = c; i < canvas.length; i += 3) out[i] = reference[i]! + median;
  }
  return out;
}

/** The reference's channels fitted to the canvas (canvas = gain x reference + offset, least squares) over the pixels `use`
 * marks: the ones that did not change. The gain stays within GAIN, so a fit never flattens the change itself. */
const GAIN: [number, number] = [0.8, 1.25];
function fitTone(canvas: Float32Array, reference: Float32Array, use: Uint8Array): Float32Array {
  const out = new Float32Array(reference.length);
  for (let c = 0; c < 3; c++) {
    let n = 0, ma = 0, mb = 0;
    for (let p = 0, i = c; i < canvas.length; p++, i += 3) if (use[p]) { n++; ma += canvas[i]!; mb += reference[i]!; }
    ma /= n; mb /= n;
    let cov = 0, vb = 0;
    for (let p = 0, i = c; i < canvas.length; p++, i += 3) if (use[p]) { cov += (canvas[i]! - ma) * (reference[i]! - mb); vb += (reference[i]! - mb) ** 2; }
    const gain = vb > 1e-6 ? Math.min(GAIN[1], Math.max(GAIN[0], cov / vb)) : 1;
    for (let i = c; i < canvas.length; i += 3) out[i] = (reference[i]! - mb) * gain + ma;
  }
  return out;
}

/** A box blur of `channels` interleaved floats, radius `r`, edges clamped. */
function boxBlur(values: Float32Array, width: number, height: number, channels: number, r: number): Float32Array {
  if (r < 1) return values;
  const pass = (src: Float32Array, horizontal: boolean) => {
    const out = new Float32Array(src.length), lines = horizontal ? height : width, length = horizontal ? width : height;
    const at = (line: number, k: number) => (horizontal ? line * width + k : k * width + line) * channels;
    for (let line = 0; line < lines; line++) for (let c = 0; c < channels; c++) {
      let sum = 0;
      for (let k = -r; k <= r; k++) sum += src[at(line, Math.min(length - 1, Math.max(0, k)))! + c]!;
      for (let k = 0; k < length; k++) {
        out[at(line, k) + c] = sum / (2 * r + 1);
        sum += src[at(line, Math.min(length - 1, k + r + 1)) + c]! - src[at(line, Math.max(0, k - r)) + c]!;
      }
    }
    return out;
  };
  return pass(pass(values, true), false);
}

/** Pieces of `value` (4-connected) smaller than `least` pixels turn into the other value. */
function dropSmall(mask: Uint8Array, width: number, height: number, value: number, least: number): void {
  const seen = new Uint8Array(mask.length), stack = new Int32Array(mask.length), piece: number[] = [];
  for (let start = 0; start < mask.length; start++) {
    if (seen[start] || mask[start] !== value) continue;
    let top = 0; stack[top++] = start; seen[start] = 1; piece.length = 0;
    while (top) {
      const p = stack[--top]!, x = p % width; piece.push(p);
      for (const q of [x > 0 ? p - 1 : -1, x < width - 1 ? p + 1 : -1, p >= width ? p - width : -1, p + width < mask.length ? p + width : -1])
        if (q >= 0 && !seen[q] && mask[q] === value) { seen[q] = 1; stack[top++] = q; }
    }
    if (piece.length < least) for (const p of piece) mask[p] = value ? 0 : 255;
  }
}

/** The mask grown by `r` pixels (a chamfer 3-4 distance, near round). */
function dilate(mask: Uint8Array, width: number, height: number, r: number): Uint8Array {
  const far = 1e9, d = new Float64Array(mask.length);
  for (let p = 0; p < mask.length; p++) d[p] = mask[p] ? 0 : far;
  const at = (x: number, y: number) => x >= 0 && y >= 0 && x < width && y < height ? d[y * width + x]! : far;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const p = y * width + x;
    d[p] = Math.min(d[p]!, at(x - 1, y) + 3, at(x, y - 1) + 3, at(x - 1, y - 1) + 4, at(x + 1, y - 1) + 4);
  }
  for (let y = height - 1; y >= 0; y--) for (let x = width - 1; x >= 0; x--) {
    const p = y * width + x;
    d[p] = Math.min(d[p]!, at(x + 1, y) + 3, at(x, y + 1) + 3, at(x + 1, y + 1) + 4, at(x - 1, y + 1) + 4);
  }
  const out = new Uint8Array(mask.length);
  for (let p = 0; p < mask.length; p++) if (d[p]! <= 3 * r) out[p] = 255;
  return out;
}

function measure(data: Uint8Array, width: number, height: number): { share: number; bounds: Rect | null } {
  let n = 0, x0 = width, y0 = height, x1 = -1, y1 = -1;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (data[y * width + x]! >= 128) {
    n++; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  return { share: n / (width * height), bounds: n ? [x0, y0, x1 - x0 + 1, y1 - y0 + 1] : null };
}

/** Where `reference` differs from `canvas` (the same size): 255 inside, 0 outside, its share and bounds. `within` (one
 * byte a pixel, >= 128 inside) keeps it to a part's area. */
export function differenceMask(canvas: Rgba, reference: Rgba, { within, rules = MASK_RULES }: { within?: Uint8Array | null; rules?: typeof MASK_RULES } = {}): Mask {
  const { width, height } = canvas, n = width * height;
  if (reference.width !== width || reference.height !== height) throw new Error('The canvas and the reference are compared at one size.');
  const long = Math.max(width, height), blur = Math.max(1, Math.round(long * rules.blur));
  const canvasRgb = boxBlur(rgbOf(canvas), width, height, 3, blur), a = lab(canvasRgb), raw = boxBlur(rgbOf(reference), width, height, 3, blur);
  const diff = (b: Float32Array) => { const out = new Float32Array(n); for (let p = 0; p < n; p++) out[p] = Math.hypot(a[p * 3]! - b[p * 3]!, a[p * 3 + 1]! - b[p * 3 + 1]!, a[p * 3 + 2]! - b[p * 3 + 2]!); return out; };
  // Tone: shifted by the median difference, then fitted (gain and offset) over the pixels the shift found unchanged.
  let delta = diff(lab(shiftTone(canvasRgb, raw)));
  const calm = new Uint8Array(n); let calmCount = 0;
  for (let p = 0; p < n; p++) if (delta[p]! < rules.threshold) { calm[p] = 1; calmCount++; }
  if (calmCount > n * 0.05) delta = diff(lab(fitTone(canvasRgb, raw, calm)));
  let mask: Uint8Array = new Uint8Array(n);
  for (let p = 0; p < n; p++) if (delta[p]! >= rules.threshold) mask[p] = 255;
  const least = Math.max(4, Math.round(n * rules.speck));
  dropSmall(mask, width, height, 255, least); dropSmall(mask, width, height, 0, least);
  mask = dilate(mask, width, height, Math.max(MIN_DILATE, Math.round(long * rules.dilate)));
  if (within) for (let p = 0; p < n; p++) if ((within[p] ?? 0) < 128) mask[p] = 0;
  return { width, height, data: mask, ...measure(mask, width, height) };
}

/** The mask at canvas size `[cw, ch]`, cropped to its bounds there (nearest pixel): Paint only here's area. */
export function canvasMask(mask: Mask, [cw, ch]: [number, number]): { bounds: Rect; plane: Plane; share: number } {
  if (!mask.bounds) throw new Error('The reference shows no change to paint.');
  const sx = cw / mask.width, sy = ch / mask.height, [mx, my, mw, mh] = mask.bounds;
  const x0 = Math.max(0, Math.floor(mx * sx)), y0 = Math.max(0, Math.floor(my * sy));
  const x1 = Math.min(cw, Math.ceil((mx + mw) * sx)), y1 = Math.min(ch, Math.ceil((my + mh) * sy));
  const w = x1 - x0, h = y1 - y0, data = new Uint8Array(w * h);
  const column = new Int32Array(w).map((_, i) => Math.min(mask.width - 1, Math.floor((x0 + i + 0.5) / sx)));
  let inside = 0;
  for (let j = 0; j < h; j++) {
    const row = Math.min(mask.height - 1, Math.floor((y0 + j + 0.5) / sy)) * mask.width;
    for (let i = 0; i < w; i++) if (mask.data[row + column[i]!]! >= 128) { data[j * w + i] = 255; inside++; }
  }
  return { bounds: [x0, y0, w, h], plane: { width: w, height: h, data }, share: inside / (cw * ch) };
}

/** A picture resized to `width` x `height` (bilinear; stretched when the proportions differ). */
export function resized(image: Rgba, width: number, height: number): Rgba {
  if (image.width === width && image.height === height) return image;
  return { width, height, data: resizeBilinear(image.data, image.width, image.height, 4, width, height) };
}
const fit = (w: number, h: number, side: number): [number, number] => {
  const k = Math.min(1, side / Math.max(w, h));
  return [Math.max(1, Math.round(w * k)), Math.max(1, Math.round(h * k))];
};

/** The canvas and the reference side by side (each at most `side` on its long side), the area's edge in red on both. RGB. */
export function compareImage(canvas: Rgba, reference: Rgba, mask: Mask, { side = 400, gap = 8 }: { side?: number; gap?: number } = {}): Plane {
  const [w, h] = fit(canvas.width, canvas.height, side), left = resized(canvas, w, h), right = resized(reference, w, h);
  const width = 2 * w + gap, out = new Uint8Array(width * h * 3).fill(255);
  const inMask = (x: number, y: number) => x >= 0 && y >= 0 && x < w && y < h
    && mask.data[Math.min(mask.height - 1, Math.floor(y * mask.height / h)) * mask.width + Math.min(mask.width - 1, Math.floor(x * mask.width / w))]! >= 128;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const edge = inMask(x, y) && (!inMask(x - 1, y) || !inMask(x + 1, y) || !inMask(x, y - 1) || !inMask(x, y + 1) || x === 0 || y === 0 || x === w - 1 || y === h - 1);
    for (const [image, offset] of [[left, 0], [right, w + gap]] as const) {
      const o = (y * width + x + offset) * 3, i = (y * w + x) * 4, a = image.data[i + 3]! / 255;
      if (edge) { out[o] = 235; out[o + 1] = 40; out[o + 2] = 40; continue; }
      for (let c = 0; c < 3; c++) out[o + c] = Math.round(image.data[i + c]! * a + 255 * (1 - a));
    }
  }
  return { width, height: h, data: out };
}

/** The reference's size for paint_from_reference: exactly the canvas's proportions, at most REFERENCE_SIDE on its long side. */
export function referenceSize([cw, ch]: [number, number], side = REFERENCE_SIDE): [number, number] {
  const gcd = (a: number, b: number): number => b ? gcd(b, a % b) : a;
  const g = gcd(cw, ch), uw = cw / g, uh = ch / g, m = Math.min(g, Math.floor(side / Math.max(uw, uh)));
  if (m >= 1) return [uw * m, uh * m];
  if (cw * ch <= 25_000_000) return [cw, ch];          // no exact smaller size: the canvas's own
  throw new Error(`The canvas (${cw} x ${ch}) has no exact smaller size for a reference.`);
}

const aspectOf = (w: number, h: number): string => {
  const r = w / h, known: [string, number][] = [['1:1', 1], ['4:3', 4 / 3], ['3:4', 3 / 4], ['3:2', 1.5], ['2:3', 2 / 3], ['16:9', 16 / 9], ['9:16', 9 / 16], ['21:9', 21 / 9]];
  return known.reduce((best, k) => Math.abs(Math.log(k[1] / r)) < Math.abs(Math.log(best[1] / r)) ? k : best)[0];
};

// ----- the card ---------------------------------------------------------------------------------------------------------

export type CanvasReferenceRecord = {
  id: string; instruction: string; part: string | null; step_key?: string;
  state: 'ready' | 'used' | 'discarded' | 'replaced'; goal?: boolean;
  reference_path: string; reference_size: [number, number]; compare_path: string; mask_path: string; mask_size: [number, number];
  canvas: [number, number]; share: number; bounds: Rect | null; wide: boolean; model: string; made_at: string; asset_id?: string;
};
/** A used canvas reference as the likeness target of the moves painting toward it (the artist, 2026-10-25: an edit is not
 * measured against the goal): the reference over the whole canvas. Outside its area it is the canvas, and Krita blocks
 * writes there. Null when it is not used, or was made on a canvas of another size. */
export function referencePlacement(record: Pick<CanvasReferenceRecord, 'id' | 'state' | 'reference_path' | 'reference_size' | 'canvas'> | null | undefined,
  canvas: { width: number; height: number }) {
  if (!record || record.state !== 'used' || record.canvas[0] !== canvas.width || record.canvas[1] !== canvas.height) return null;
  const [width, height] = record.reference_size, id = 'canvas-reference-' + record.id;
  return { mapping: { reference_id: id, source: [0, 0, width, height] as Rect, target: [0, 0, canvas.width, canvas.height] as Rect, from: 'transfer' as const },
    reference: { id, path: record.reference_path, width, height, source: 'canvas_reference' } };
}
export type FoundPart = { mask_path: string; bounds: number[]; canvas: number[] };
export type UseArea = { mask_path: string; bounds: Rect; canvas: [number, number]; share: number };
type Goal = { ai_images_used?: number; canvas_reference_notice?: boolean; canvas_references?: Record<string, CanvasReferenceRecord> };
export type CanvasReferenceHost = {
  readonly study: { directory: string } | null | undefined;
  readonly goal: Goal | null | undefined;
  /** The image backend (the `assets` setting). */
  backend(): 'codex' | 'openrouter';
  /** Throws when the chat's AI image allowance is off or used up (assets.mjs assertAiImageAllowed). */
  allowance(): void;
  /** The canvas as the painter sees it: its view file and the canvas's size. */
  observe(): Promise<{ image_path: string; width: number; height: number }>;
  /** One edited image from the image model. */
  generate(request: { prompt: string; input: { data: Buffer; mimeType: string }; aspect: string }): Promise<{ data: Buffer; model: string }>;
  /** An image file's pixels (RGBA). */
  decode(data: Buffer): Promise<Rgba | null>;
  /** Find it's outline of a part on the canvas (canvas pixels), or null. */
  findArea?(part: string): Promise<FoundPart | null>;
  emit(event: Record<string, unknown>): void;
  persist(): Promise<unknown>;
  publish(): void;
  /** A move paints now (Use waits for it). */
  busy(): boolean;
  /** Use as the target: paint toward the reference inside `area`. */
  use(record: CanvasReferenceRecord, area: UseArea): Promise<void>;
  /** The chat has a goal picture the change can be pasted into (Use as the new goal is offered). */
  hasGoal?(): boolean;
  /** Use as the new goal: paste the reference inside `area` (canvas pixels) into the goal picture. */
  makeGoal?(record: CanvasReferenceRecord, area: { bounds: Rect; plane: Plane }): Promise<void>;
  /** Discard: the card is gone (a plan step it held paints without it). */
  discarded?(record: CanvasReferenceRecord): Promise<void>;
};

const percent = (share: number) => share > 0 ? Math.max(1, Math.round(share * 100)) : 0;
const NOTICE = { codex: 'Your canvas was sent to ChatGPT (your Codex sign-in) to make this picture.', openrouter: 'Your canvas was sent to an OpenRouter image model to make this picture (about 1–2 cents).' };

/** Within a part's area at the comparison size: the found outline (canvas pixels) sampled at each comparison pixel. */
async function partWithin(found: FoundPart, [w, h]: [number, number], [cw, ch]: [number, number]): Promise<Uint8Array> {
  const [bx = 0, by = 0, bw = 0, bh = 0] = found.bounds;
  const plane = decodePlane(await readFile(found.mask_path), { width: bw, height: bh }), out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = Math.floor((x + 0.5) * cw / w) - bx, j = Math.floor((y + 0.5) * ch / h) - by;
    if (i >= 0 && j >= 0 && i < plane.width && j < plane.height && plane.data[j * plane.width + i]! >= 128) out[y * w + x] = 255;
  }
  return out;
}

export function canvasReferencer(host: CanvasReferenceHost) {
  const say = (message: string) => host.emit({ type: 'action', seconds: 0, message });
  const records = (): Record<string, CanvasReferenceRecord> => {
    if (!host.goal) throw new Error('Start a chat first: a canvas reference belongs to a chat.');
    return (host.goal.canvas_references ??= {});
  };
  const card = (record: CanvasReferenceRecord, notes: string[]) => {
    const asked = `“${record.instruction}”${record.part ? ` in ${record.part}` : ''}`;
    const lines = [record.bounds
      ? `A reference of ${asked}: the canvas (left) and the reference (right). The change covers ${percent(record.share)}% of the canvas, outlined in red. Nothing is painted until you use it.`
      : `A reference of ${asked}: the canvas (left) and the reference (right). The reference shows no clear change from the canvas: try again, or say the change differently.`];
    if (record.wide) lines.push(`The model changed a lot (${percent(record.share)}% of the canvas): try a narrower instruction, or name an area (… in the sky).`);
    if (record.step_key) lines.push('The plan step waits for your answer: it paints after it, toward the reference when you use it.');
    lines.push(...notes);
    const options = record.bounds ? [CANVAS_REFERENCE_OPTIONS.use, ...(host.makeGoal && host.hasGoal?.() ? [CANVAS_REFERENCE_OPTIONS.goal] : []),
      CANVAS_REFERENCE_OPTIONS.retry, CANVAS_REFERENCE_OPTIONS.discard] : [CANVAS_REFERENCE_OPTIONS.retry, CANVAS_REFERENCE_OPTIONS.discard];
    host.emit({ type: 'canvas_reference', id: record.id, title: 'Canvas reference', message: lines.join('\n\n'), image_path: record.compare_path,
      options, actions: options.map(label => (Object.keys(CANVAS_REFERENCE_OPTIONS) as CanvasReferenceAction[]).find(k => CANVAS_REFERENCE_OPTIONS[k] === label)),
      share: record.share, wide: record.wide, bounds: record.bounds, auto_approve: false });
  };
  const drop = async (record: CanvasReferenceRecord) => {
    if (host.study) await rm(join(host.study.directory, FOLDER, record.id), { recursive: true, force: true });
  };

  async function start({ instruction, part, step_key }: { instruction: string; part: string | null; step_key?: string }): Promise<CanvasReferenceRecord | null> {
    const goal = host.goal, study = host.study;
    if (!goal || !study) throw new Error('Start a chat first: a canvas reference belongs to a chat.');
    if (!instruction.trim()) { say('Say what to change: /canvas-reference add more snow on the roofs (add "in the sky" to change one part).'); return null; }
    host.allowance();                                    // before anything is sent: a refused image costs nothing
    host.emit({ type: 'status', phase: 'asset', message: `Making a canvas reference: ${instruction}…` });
    const seen = await host.observe(), view = await readFile(seen.image_path);
    const pixels = await host.decode(view);
    if (!pixels) throw new Error('The canvas view could not be read for a canvas reference.');
    const canvas: [number, number] = [seen.width, seen.height], notes: string[] = [];
    const [w, h] = fit(pixels.width, pixels.height, MASK_RULES.side);
    let within: Uint8Array | null = null;
    if (part) {
      const found = await host.findArea?.(part).catch(() => null) ?? null;
      if (found) within = await partWithin(found, [w, h], canvas);
      else notes.push(`${part[0]!.toUpperCase() + part.slice(1)} was not found, so the whole canvas is compared.`);
    }
    const made = await host.generate({ prompt: editPrompt(instruction, part), input: { data: view, mimeType: 'image/png' }, aspect: aspectOf(seen.width, seen.height) });
    goal.ai_images_used = (goal.ai_images_used ?? 0) + 1;     // the image exists: it counts
    const raw = await host.decode(made.data);
    if (!raw) throw new Error('The image model’s picture could not be read.');
    const small = resized(pixels, w, h), other = resized(raw, w, h), mask = differenceMask(small, other, { within });
    const id = randomUUID().slice(0, 12), folder = join(study.directory, FOLDER, id);
    await mkdir(folder, { recursive: true });
    const size = referenceSize(canvas), files = { reference: join(folder, 'reference.png'), compare: join(folder, 'compare.png'), mask: join(folder, 'mask.png') };
    await writeFile(files.reference, encodeRgba(resized(raw, size[0], size[1])));
    await writeFile(files.compare, encodeRgb(compareImage(small, other, mask)));
    await writeFile(files.mask, encodePlane(mask));
    const bounds = mask.bounds ? canvasMask(mask, canvas).bounds : null;
    const record: CanvasReferenceRecord = { id, instruction, part, ...(step_key ? { step_key } : {}), state: 'ready', reference_path: files.reference, reference_size: size,
      compare_path: files.compare, mask_path: files.mask, mask_size: [w, h], canvas, share: mask.share, bounds, wide: mask.share > WIDE_SHARE, model: made.model,
      made_at: new Date().toISOString() };
    records()[id] = record;
    if (!goal.canvas_reference_notice) { notes.push(NOTICE[host.backend()] ?? NOTICE.codex); goal.canvas_reference_notice = true; }
    await host.persist(); host.publish();
    card(record, notes);
    return record;
  }

  async function answer({ id, action }: { id?: unknown; action?: unknown }): Promise<void> {
    const record = typeof id === 'string' ? host.goal?.canvas_references?.[id] : undefined;
    if (!record || record.state !== 'ready') { say('That canvas reference is no longer open.'); return; }
    if (action === 'discard') {
      record.state = 'discarded'; await drop(record);
      await host.persist(); host.publish(); say('Discarded the canvas reference.');
      await host.discarded?.(record);
    } else if (action === 'retry') {
      record.state = 'replaced'; await drop(record); await host.persist();
      await start({ instruction: record.instruction, part: record.part, ...(record.step_key ? { step_key: record.step_key } : {}) });
    } else if (action === 'use' || (action === 'goal' && host.makeGoal)) {
      if (!record.bounds) { say('The reference shows no change to paint.'); return; }
      if (host.busy()) { say('A move is painting: stop it or wait for it, then press Use as the target.'); card(record, []); return; }
      const [w, h] = record.mask_size, plane = decodePlane(await readFile(record.mask_path), { width: w, height: h });
      const area = canvasMask({ ...plane, ...measure(plane.data, w, h) }, record.canvas);
      const file = join(host.study!.directory, FOLDER, record.id, 'area.png');
      await writeFile(file, encodePlane(area.plane));
      if (action === 'goal') {
        // A goal that cannot be changed never stops the move: it paints toward the reference for this move only.
        try { await host.makeGoal!(record, { bounds: area.bounds, plane: area.plane }); record.goal = true; }
        catch (error) { say(`${(error as Error).message} The reference is the target for this move only.`); }
      }
      record.state = 'used'; await host.persist(); host.publish();
      await host.use(record, { mask_path: file, bounds: area.bounds, canvas: record.canvas, share: area.share });
    } else throw new Error('A canvas reference is used, made the new goal, tried again or discarded.');
  }

  return { start, answer };
}

/** The painter's instructions for a move toward an approved canvas reference (its asset and the canvas's size). */
export function referenceMoveNote(record: Pick<CanvasReferenceRecord, 'instruction' | 'part' | 'reference_size' | 'share'>, { asset_id, canvas }: { asset_id: string; canvas: [number, number] }): string {
  const [rw, rh] = record.reference_size, [cw, ch] = canvas;
  return `\nCANVAS REFERENCE: the artist approved a reference picture of this change: "${record.instruction}"${record.part ? ` in ${record.part}` : ''} `
    + `(reference_id ${asset_id}, ${rw} x ${rh}: the whole canvas as it would look). Paint toward it only inside the Paint only here area, `
    + `the part where it differs from the canvas (${percent(record.share)}% of the canvas): Krita blocks every write outside it, so faces and `
    + `everything else stay as they are. First paint_from_reference with reference_id ${asset_id}, source [0,0,${rw},${rh}], target [0,0,${cw},${ch}] `
    + '(the whole canvas: only the dabs inside the area are painted), then paint_accents in the area for its crisp lights, darks and edges. '
    + 'Do not use refine_to_goal here (its goal is the plan’s picture, not this reference). Then look at the canvas and finish_move.\n';
}
