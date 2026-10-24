// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The resolution probe (openspec luna-goal-reviewer goal 3, the artist 2026-10-24: "not assumed, measured"). Many vision
// models shrink a large image before they read it, so a larger canvas view can cost more and show nothing more. The probe
// draws a picture whose fine detail has a fixed size in pixels (a small digit and a row of small dots in each of five
// framed boxes), at each of PROBE_SIZES on the long side (1024 to 2560) and as 1:1 crops of the boxes, and asks a model what each box
// holds. A model that reads the 2048 px picture as well as the 1:1 crops reads 2048 px; one that misses the detail at
// 2048 but not at 1792 shrinks the picture somewhere between. recommendSides turns the scores into the painter's view
// side (view-size.ts, at most MAX_VIEW_SIDE) and the side of Luna's goal-comparison crops (goal-comparison.ts).
// scripts/resolution-probe.ts runs it against a model and records the result; this module only draws, asks and scores.
import type { Rgba } from './bounded-image.ts';

export const PROBE_SIZES = [1024, 1280, 1536, 1792, 2048, 2560] as const;
/** The longest crop Luna's goal comparison sends: three images a crop, up to three crops a call. */
export const MAX_CROP_SIDE = 1536;
/** The painter's view never grows past this: Pi shrinks any image over 2000 px a side before it is sent. */
export const PROBE_VIEW_CAP = 2000;
/** Pixels in one unit of the detail: a digit is 5 x 7 units, a dot 2 x 2 with 2 between. */
export const UNIT = 2;
export const BOX_IDS = ['top_left', 'top_right', 'centre', 'bottom_left', 'bottom_right'] as const;
const WHERE: Record<string, string> = { top_left: 'top left', top_right: 'top right', centre: 'centre', bottom_left: 'bottom left', bottom_right: 'bottom right' };
export type Box = { id: string; rect: [number, number, number, number]; digit: number; dots: number; frame: number };
export type Probe = { image: Rgba; boxes: Box[] };
export type ProbeQuestion = { id: string; text: string; options: string[]; answer: number };
export type Score = { correct: number; total: number; accuracy: number };

// 5 x 7 digits, one row a string, '#' ink.
const FONT: string[][] = [
  ['.###.', '#...#', '#..##', '#.#.#', '##..#', '#...#', '.###.'], ['..#..', '.##..', '..#..', '..#..', '..#..', '..#..', '.###.'],
  ['.###.', '#...#', '....#', '...#.', '..#..', '.#...', '#####'], ['####.', '....#', '....#', '.###.', '....#', '....#', '####.'],
  ['...#.', '..##.', '.#.#.', '#..#.', '#####', '...#.', '...#.'], ['#####', '#....', '####.', '....#', '....#', '#...#', '.###.'],
  ['..##.', '.#...', '#....', '####.', '#...#', '#...#', '.###.'], ['#####', '....#', '...#.', '..#..', '.#...', '.#...', '.#...'],
  ['.###.', '#...#', '#...#', '.###.', '#...#', '#...#', '.###.'], ['.###.', '#...#', '#...#', '.####', '....#', '...#.', '.##..'],
];

/** A small deterministic generator (mulberry32): the same seed draws the same picture and answers. */
function random(seed: number): () => number {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** The probe picture at `width` x `height`: a lightly noisy ground, five framed boxes (the frame thick enough to find at
 * any size), in each a digit 0-9 and a row of 1-9 dots, both at UNIT px a unit whatever the picture's size. */
export function probeImage({ width, height, seed = 1, unit = UNIT }: { width: number; height: number; seed?: number; unit?: number }): Probe {
  const rnd = random(seed), data = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) { const v = 214 + Math.floor(rnd() * 16); data[i * 4] = v; data[i * 4 + 1] = v; data[i * 4 + 2] = v + 6; data[i * 4 + 3] = 255; }
  const fill = (x: number, y: number, w: number, h: number, [r, g, b]: [number, number, number]) => {
    for (let yy = Math.max(0, y); yy < Math.min(height, y + h); yy++) for (let xx = Math.max(0, x); xx < Math.min(width, x + w); xx++) {
      const p = (yy * width + xx) * 4; data[p] = r; data[p + 1] = g; data[p + 2] = b; }
  };
  const inner = [44 * unit, 14 * unit] as const, frame = Math.max(3, Math.round(Math.max(width, height) / 300)), pad = 4 * unit;
  const bw = inner[0] + 2 * (frame + pad), bh = inner[1] + 2 * (frame + pad);
  const at: Record<string, [number, number]> = { top_left: [0.2, 0.2], top_right: [0.8, 0.2], centre: [0.5, 0.5], bottom_left: [0.2, 0.8], bottom_right: [0.8, 0.8] };
  const boxes: Box[] = BOX_IDS.map(id => {
    const [fx, fy] = at[id]!, x = Math.round(fx * width - bw / 2), y = Math.round(fy * height - bh / 2);
    const digit = Math.floor(rnd() * 10), dots = 1 + Math.floor(rnd() * 9);
    fill(x, y, bw, bh, [40, 40, 60]); fill(x + frame, y + frame, bw - 2 * frame, bh - 2 * frame, [250, 250, 245]);
    const ox = x + frame + pad, oy = y + frame + pad + unit * 3;
    FONT[digit]!.forEach((row, r) => [...row].forEach((c, k) => { if (c === '#') fill(ox + k * unit, oy + r * unit, unit, unit, [10, 10, 10]); }));
    for (let d = 0; d < dots; d++) fill(ox + 9 * unit + d * 4 * unit, oy + 3 * unit, 2 * unit, 2 * unit, [10, 10, 10]);
    return { id, rect: [x, y, bw, bh] as [number, number, number, number], digit, dots, frame };
  });
  return { image: { width, height, data }, boxes };
}

/** Each box cut from the picture at its own pixels (1:1), with a margin: the control a model must read. */
export function probeCrops({ image, boxes }: Probe, margin = 24): { id: string; image: Rgba }[] {
  return boxes.map(b => {
    const x = Math.max(0, b.rect[0] - margin), y = Math.max(0, b.rect[1] - margin);
    const w = Math.min(image.width - x, b.rect[2] + 2 * margin), h = Math.min(image.height - y, b.rect[3] + 2 * margin), out = new Uint8Array(w * h * 4);
    for (let r = 0; r < h; r++) out.set(image.data.subarray(((y + r) * image.width + x) * 4, ((y + r) * image.width + x + w) * 4), r * w * 4);
    return { id: b.id, image: { width: w, height: h, data: out } };
  });
}

/** Two questions a box: its digit and its dot count, as choices; with crops, the box is CROP n. */
export function probeQuestions(boxes: Box[], { crops = false }: { crops?: boolean } = {}): ProbeQuestion[] {
  return boxes.flatMap((b, i) => {
    const where = crops ? `the box in CROP ${i + 1}` : `the box at the ${WHERE[b.id]} of the image`;
    return [
      { id: `${b.id}_digit`, text: `Which digit is written in small print in ${where}?`, options: ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'], answer: b.digit },
      { id: `${b.id}_dots`, text: `How many small dots are in the row in ${where}?`, options: ['1', '2', '3', '4', '5', '6', '7', '8', '9'], answer: b.dots },
    ];
  });
}

/** How many answers (strings, null for none) match the known ones. */
export function scoreProbe(questions: ProbeQuestion[], answers: Record<string, string | null | undefined>): Score {
  const correct = questions.filter(q => answers[q.id] === String(q.answer)).length;
  return { correct, total: questions.length, accuracy: Math.round(correct / questions.length * 100) / 100 };
}

export type SizeResult = { accuracy: number; input_tokens?: number; cache_read_tokens?: number; cache_write_tokens?: number; cost?: number };

/** What one size cost the model to read: its input tokens with the cached ones (a provider that caches the image reports
 * it as cache read or write, Anthropic through OpenRouter as 4 input tokens at every size), or 0 when not reported. */
export const sizeTokens = (at: SizeResult | undefined): number => (at?.input_tokens ?? 0) + (at?.cache_read_tokens ?? 0) + (at?.cache_write_tokens ?? 0);

/** The sizes a model reads: the largest probed size that scores within 0.1 of the 1:1 crops (and at least 0.8) of those
 * that still cost more than the size below them: more tokens (input with cached, sizeTokens) when the provider
 * reports them, else more money. Equal tokens at a larger size mean the model shrank it, so the extra pixels are thrown
 * away (measured live on deepseek-flash 2026-10-24). The view at most PROBE_VIEW_CAP, a crop at most MAX_CROP_SIDE. Null
 * when it misses the crops too (it cannot read this detail at all, so the probe says nothing about size). */
export function recommendSides(result: { crops: { accuracy: number }; sizes: Record<number, SizeResult> }): { view_side: number; crop_side: number; reads: number } | null {
  if (!(result.crops.accuracy >= 0.6)) return null;
  const bar = Math.max(0.8, result.crops.accuracy - 0.1);
  const counted = PROBE_SIZES.some(size => sizeTokens(result.sizes[size]) > 0);
  const spent = (at: SizeResult | undefined) => counted ? sizeTokens(at) : at?.cost ?? 0;
  // Sizes are probed until the cost stops growing (the model shrank the picture); of those, the largest that scores the
  // bar is read. A dip at one size between sizes it reads is noise (deepseek-flash at 1280 in two live runs), not a limit.
  let reads = 0, before = 0;
  for (const size of PROBE_SIZES) {
    const at = result.sizes[size], used = spent(at);
    if (before > 0 && used > 0 && used < before * 1.05) break;
    if ((at?.accuracy ?? 0) >= bar) reads = size;
    if (used > 0) before = used;
  }
  const floor = PROBE_SIZES[0];
  return { view_side: Math.min(Math.max(reads, floor), PROBE_VIEW_CAP), crop_side: Math.min(Math.max(reads, floor), MAX_CROP_SIDE), reads };
}
