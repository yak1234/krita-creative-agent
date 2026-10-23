// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The mass map: the big masses of a reference (sky, each building mass, a head, a car, the moon) as boundary lines for a
// block-in, and a short text summary of them for the painter.
//
// The plugin smooths the crop first (creative_masses.py: bilateral passes, then mean shift, at most 720 px), so a mass is
// about one colour with a sharp edge; VTracer (@visioncortex/vtracer, WebAssembly) then cuts it into colour regions
// (MASS_OPTIONS) and writes them as SVG polygons. Here the polygons become lines: tiny masses go, each shared boundary is
// drawn once (the light masses' first, so a moon stays warm), and each line is simplified to at most GUIDE_POINTS
// points. With a shape (one element's pixels), only what lies inside it is traced and its own outline is left to the
// outline tracer. Lines only: no mass is ever filled and no reference pixel reaches the canvas.
//
// Everything here is in the smoothed copy's pixels; guide-tool.ts maps the lines onto the canvas.
import type { Rgba } from './shapes/use.ts';

type Pixels = Rgba;
type Point = [number, number];

/** Douglas-Peucker: the fewest points within epsilon of the polyline (a closed one keeps its closing point). */
export function simplifyPolyline(points: Point[], epsilon: number): Point[] {
  if (points.length < 3) return points.slice();
  const first = points[0]!, last = points.at(-1)!;
  let index = 0, worst = -1;
  for (let i = 1; i < points.length - 1; i++) {
    const p = points[i]!, dx = last[0] - first[0], dy = last[1] - first[1], span = Math.hypot(dx, dy);
    const d = span ? Math.abs(dx * (first[1] - p[1]) - dy * (first[0] - p[0])) / span : Math.hypot(p[0] - first[0], p[1] - first[1]);
    if (d > worst) { worst = d; index = i; }
  }
  if (worst <= epsilon) return [first, last];
  return [...simplifyPolyline(points.slice(0, index + 1), epsilon).slice(0, -1), ...simplifyPolyline(points.slice(index), epsilon)];
}
export type Rgb = [number, number, number];
/** One VTracer path: its fill and its rings (the first is the outline, the rest are holes). */
export type SvgMass = { fill: Rgb; rings: Point[][] };
/** A mass kept: its fill, luminance 0-1, area (pixels), share of the image, centre and box (fractions 0-1), light. */
export type Mass = { fill: Rgb; lum: number; area: number; share: number; centre: Point; box: [number, number, number, number]; light: boolean };
export type MassLine = { points: Point[]; light: boolean };
export type Vectorize = (rgba: Uint8Array, width: number, height: number, options: Record<string, unknown>) => string;

/** VTracer's options for masses: regions cut apart (not stacked), straight polygons, a few colours, no specks. */
// filterSpeckle is in the smoothed copy's pixels (720 on its long side): 12 here is the lead's 24 at 1440 (a moon stays).
export const MASS_OPTIONS = { hierarchical: 'cutout', mode: 'polygon', maxColors: 6, filterSpeckle: 12 } as const;
export const MASS_LINES = 80;          // boundary lines one call draws at most (draw_guide takes GUIDE_LINES in all)
export const MASS_LIMIT = 24;          // masses kept, the largest, besides the lights
export const MASS_LIGHTS = 6;          // light masses kept, the largest
const POINTS = 64;                     // guide-tool.ts GUIDE_POINTS
const SMALLEST = 0.001;                // a mass under this share of the image is dropped
const EPSILON = 1;                    // simplification, pixels of the smoothed copy (about 1/720 of its long side)
const SHORTEST = 0.03;                 // a boundary piece under this share of the long side is dropped
const LIGHT_LUM = 0.5;                 // a light mass is at least this bright,
const LIGHT_ABOVE = 0.3;               // well above the picture's typical (area median) value,
const LIGHT_SHARE = 0.25;              // and the light masses together cover at most this share (a bright day sky is no light)

let vectorizer: Promise<Vectorize> | null = null;
/** VTracer's convertPixels, loaded on first use (its WebAssembly is compiled once per process). */
export function loadVectorizer(): Promise<Vectorize> {
  vectorizer ??= import('@visioncortex/vtracer').then(module => {
    const convert = (module as { convertPixels?: Vectorize; default?: { convertPixels?: Vectorize } }).convertPixels
      ?? (module as { default?: { convertPixels?: Vectorize } }).default?.convertPixels;
    if (!convert) throw new Error('VTracer has no convertPixels.');
    return convert;
  });
  return vectorizer;
}

/** VTracer's SVG as masses: each <path>'s fill and rings, in pixels (M/m, L/l, H/h, V/v, Z/z and a translate). */
export function parseSvgMasses(svg: string): SvgMass[] {
  const masses: SvgMass[] = [];
  for (const [tag] of svg.matchAll(/<path\b[^>]*>/g)) {
    const d = /\bd="([^"]*)"/.exec(tag)?.[1];
    if (!d) continue;
    const hex = /\bfill="#([0-9a-fA-F]{6})"/.exec(tag)?.[1] ?? '000000';
    const fill: Rgb = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)) as Rgb;
    const shift = /\btransform="translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)\s*\)"/.exec(tag);
    const ox = shift ? Number(shift[1]) : 0, oy = shift ? Number(shift[2]) : 0;
    const rings: Point[][] = [];
    let ring: Point[] | null = null, x = 0, y = 0, startX = 0, startY = 0, command = '';
    const tokens = d.match(/[MmLlHhVvZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?/g) ?? [];
    for (let i = 0; i < tokens.length;) {
      const token = tokens[i]!;
      if (/[A-Za-z]/.test(token)) { command = token; i++; if (command !== 'Z' && command !== 'z') continue; }
      const take = () => Number(tokens[i++]);
      switch (command) {
        case 'M': case 'm': {
          const nx = take(), ny = take();
          x = command === 'm' ? x + nx : nx; y = command === 'm' ? y + ny : ny;
          startX = x; startY = y; ring = [[x, y]]; rings.push(ring);
          command = command === 'm' ? 'l' : 'L';       // further pairs are lines
          break;
        }
        // VTracer may start a path with L (no M): the first point then starts the ring.
        case 'L': { x = take(); y = take(); if (ring) ring.push([x, y]); else { startX = x; startY = y; ring = [[x, y]]; rings.push(ring); } break; }
        case 'l': { x += take(); y += take(); if (ring) ring.push([x, y]); else { startX = x; startY = y; ring = [[x, y]]; rings.push(ring); } break; }
        case 'H': { x = take(); ring?.push([x, y]); break; }
        case 'h': { x += take(); ring?.push([x, y]); break; }
        case 'V': { y = take(); ring?.push([x, y]); break; }
        case 'v': { y += take(); ring?.push([x, y]); break; }
        case 'Z': case 'z': {
          if (ring && (ring.at(-1)![0] !== startX || ring.at(-1)![1] !== startY)) ring.push([startX, startY]);
          x = startX; y = startY; ring = null; command = '';
          break;
        }
        default: i++;                                    // a stray number
      }
    }
    masses.push({ fill, rings: rings.filter(r => r.length >= 3).map(r => r.map(([px, py]): Point => [px + ox, py + oy])) });
  }
  return masses;
}

/** The mean colour of the image under a mass's rings (even-odd, scanlines through pixel centres), or null if none. */
function meanColour(image: Pixels, rings: Point[][]): Rgb | null {
  const ys = rings.flat().map(p => p[1]);
  const top = Math.max(0, Math.floor(Math.min(...ys))), bottom = Math.min(image.height - 1, Math.ceil(Math.max(...ys)));
  let r = 0, g = 0, b = 0, n = 0;
  for (let y = top; y <= bottom; y++) {
    const cy = y + 0.5, cuts: number[] = [];
    for (const ring of rings) for (let i = 1; i < ring.length; i++) {
      const [ax, ay] = ring[i - 1]!, [bx, by] = ring[i]!;
      if ((ay <= cy) !== (by <= cy)) cuts.push(ax + (cy - ay) / (by - ay) * (bx - ax));
    }
    cuts.sort((p, q) => p - q);
    for (let k = 0; k + 1 < cuts.length; k += 2) {
      for (let x = Math.max(0, Math.ceil(cuts[k]! - 0.5)); x < Math.min(image.width, Math.ceil(cuts[k + 1]! - 0.5)); x++) {
        const i = (y * image.width + x) * 4;
        r += image.data[i] ?? 0; g += image.data[i + 1] ?? 0; b += image.data[i + 2] ?? 0; n++;
      }
    }
  }
  return n ? [Math.round(r / n), Math.round(g / n), Math.round(b / n)] : null;
}

const ringArea = (ring: Point[]) => ring.reduce((sum, p, i) => { const q = ring[(i + 1) % ring.length]!; return sum + p[0] * q[1] - q[0] * p[1]; }, 0) / 2;
const luminance = ([r, g, b]: Rgb) => (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
const lineLength = (points: Point[]) => points.slice(1).reduce((n, p, i) => n + Math.hypot(p[0] - points[i]![0], p[1] - points[i]![1]), 0);

/** A ring sampled about every pixel (its own points kept). */
function dense(ring: Point[]): Point[] {
  const out: Point[] = [];
  for (let i = 1; i < ring.length; i++) {
    const a = ring[i - 1]!, b = ring[i]!, n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1])));
    for (let k = 0; k < n; k++) out.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]);
  }
  if (ring.length) out.push(ring.at(-1)!);
  return out;
}

export type MassOptions = {
  /** Only pixels where this is true take part (an element's shape), in the image's pixels. */
  inside?: (x: number, y: number) => boolean;
  limit?: number;
  /** Boundary lines at most (default MASS_LINES). */
  maxLines?: number;
  vectorize?: Vectorize;
};

/** The masses of a smoothed image and their boundary lines, in its pixels. */
export async function traceMasses(image: Pixels, options: MassOptions = {}): Promise<{ masses: Mass[]; lines: MassLine[]; paths: number }> {
  const { width: w, height: h } = image;
  if (image.data.length !== w * h * 4) throw new Error('Invalid smoothed reference.');
  const inside = options.inside;
  let rgba = new Uint8Array(image.data.buffer, image.data.byteOffset, image.data.length);
  if (inside) {                                          // outside the shape is see-through: VTracer leaves it out
    rgba = Uint8Array.from(rgba);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (!inside(x + 0.5, y + 0.5)) rgba[(y * w + x) * 4 + 3] = 0;
  }
  const vectorize = options.vectorize ?? await loadVectorizer();
  const parsed = parseSvgMasses(vectorize(rgba, w, h, { ...MASS_OPTIONS }));
  const total = w * h, speck = MASS_OPTIONS.filterSpeckle ** 2;
  const all = parsed.map(({ fill, rings }) => {
    const outline = rings[0] ?? [];
    const area = Math.abs(ringArea(outline)) - rings.slice(1).reduce((n, ring) => n + Math.abs(ringArea(ring)), 0);
    // Its own colour under it: VTracer's fill is one of a few palette colours, which a small light (a moon) loses.
    return { fill: meanColour(image, rings) ?? fill, outline, area };
  }).filter(mass => mass.outline.length >= 3 && mass.area >= speck);
  // Light masses: bright, well above the picture's typical value, and together not most of it. A light may be small (a
  // moon, a lamp); any other mass under SMALLEST of the image is dropped.
  const byLum = all.map(mass => ({ mass, lum: luminance(mass.fill) })).sort((a, b) => a.lum - b.lum);
  const coverage = byLum.reduce((n, item) => n + item.mass.area, 0);
  let seen = 0, median = 0;
  for (const item of byLum) { seen += item.mass.area; if (seen >= coverage / 2) { median = item.lum; break; } }
  const lights = new Set<typeof all[number]>();
  let lit = 0;
  for (const item of [...byLum].reverse()) {
    if (item.lum < LIGHT_LUM || item.lum < median + LIGHT_ABOVE || lit + item.mass.area > LIGHT_SHARE * coverage) break;
    lights.add(item.mass); lit += item.mass.area;
  }
  // The largest few lights, then the largest other masses: many small lamps never crowd out the sky and the buildings.
  const largest = (a: { area: number }, b: { area: number }) => b.area - a.area;
  const chosen = [...[...lights].sort(largest).slice(0, MASS_LIGHTS),
    ...all.filter(mass => !lights.has(mass) && mass.area >= SMALLEST * total).sort(largest).slice(0, options.limit ?? MASS_LIMIT)];
  const masses: Mass[] = chosen.map(mass => {
    let cx = 0, cy = 0, a = 0;
    const ring = mass.outline;
    for (let i = 0; i < ring.length; i++) {
      const p = ring[i]!, q = ring[(i + 1) % ring.length]!, cross = p[0] * q[1] - q[0] * p[1];
      a += cross; cx += (p[0] + q[0]) * cross; cy += (p[1] + q[1]) * cross;
    }
    const xs = ring.map(p => p[0]), ys = ring.map(p => p[1]);
    const centre: Point = a ? [cx / (3 * a) / w, cy / (3 * a) / h] : [0.5, 0.5];
    return { fill: mass.fill, lum: Math.round(luminance(mass.fill) * 100) / 100, area: Math.round(mass.area), share: mass.area / total,
      centre, box: [Math.min(...xs) / w, Math.min(...ys) / h, Math.max(...xs) / w, Math.max(...ys) / h], light: lights.has(mass) };
  });
  // Boundaries, each drawn once: a cell grid marks where lines already run; a ring is cut where it meets one, where it
  // runs along the image's edge (never a boundary) and, with a shape, along the shape's outline.
  const cell = 2, gw = Math.ceil(w / cell) + 2, gh = Math.ceil(h / cell) + 2, taken = new Uint8Array(gw * gh);
  const key = (x: number, y: number) => (Math.floor(y / cell) + 1) * gw + Math.floor(x / cell) + 1;
  const onEdge = (x: number, y: number) => x <= 0.5 || y <= 0.5 || x >= w - 0.5 || y >= h - 0.5;
  const nearOutline = (x: number, y: number) => !!inside && [[-2, 0], [2, 0], [0, -2], [0, 2], [0, 0]].some(([dx, dy]) => !inside(x + dx!, y + dy!));
  const shortest = SHORTEST * Math.max(w, h), pieces: { points: Point[]; light: boolean; length: number }[] = [];
  chosen.forEach((mass, index) => {
    const light = masses[index]!.light, mine: number[] = [];
    let piece: Point[] = [];
    const close = () => {
      if (piece.length >= 2 && lineLength(piece) >= shortest) pieces.push({ points: piece, light, length: lineLength(piece) });
      piece = [];
    };
    for (const [x, y] of dense(mass.outline)) {
      const k = key(x, y);
      if (taken[k] || onEdge(x, y) || nearOutline(x, y)) { close(); continue; }
      piece.push([x, y]); mine.push(k);
    }
    close();
    for (const k of mine) for (const d of [0, 1, -1, gw, -gw, gw + 1, gw - 1, -gw + 1, -gw - 1]) taken[k + d] = 1;
  });
  // Simplified within EPSILON (not coarser, so a skyline keeps its towers); a long one goes in runs of POINTS points.
  const lines: MassLine[] = [];
  for (const { points, light } of pieces.sort((a, b) => Number(b.light) - Number(a.light) || b.length - a.length)) {
    const simple = simplifyPolyline(points, EPSILON);
    for (let start = 0; start < simple.length - 1 && lines.length < (options.maxLines ?? MASS_LINES); start += POINTS - 1)
      lines.push({ points: simple.slice(start, start + POINTS), light });
  }
  return { masses, lines, paths: parsed.length };
}

const HUES = [[15, 'red'], [45, 'orange'], [70, 'yellow'], [160, 'green'], [200, 'teal'], [255, 'blue'], [290, 'violet'], [340, 'magenta'], [360, 'red']] as const;
/** A rough colour name: value, temperature and hue ("dark cool blue", "light warm yellow", "mid grey"). */
export function colourWords([r, g, b]: Rgb): string {
  const max = Math.max(r, g, b), min = Math.min(r, g, b), lum = luminance([r, g, b]);
  const value = lum < 0.25 ? 'dark' : lum < 0.6 ? 'mid' : 'light';
  if (max - min < 0.15 * Math.max(max, 1) || max - min < 18) return `${value} grey`;
  let hue = max === r ? 60 * (((g - b) / (max - min)) % 6) : max === g ? 60 * ((b - r) / (max - min) + 2) : 60 * ((r - g) / (max - min) + 4);
  if (hue < 0) hue += 360;
  const name = HUES.find(([limit]) => hue < limit)?.[1] ?? 'red';
  return `${value} ${hue < 75 || hue >= 330 ? 'warm' : 'cool'} ${name}`;
}
const place = ([x, y]: Point) => {
  const row = y < 0.34 ? 'top' : y < 0.67 ? 'middle' : 'bottom', column = x < 0.34 ? 'left' : x < 0.67 ? 'centre' : 'right';
  return row === 'middle' && column === 'centre' ? 'centre' : row === 'middle' ? column : column === 'centre' ? row : `${row} ${column}`;
};
const percent = (value: number) => Math.round(value * 100);

/** The masses in a line of text for the painter: the largest few, each with share, colour and value, place and span;
 * light masses marked. About ten words a mass. */
export function describeMasses(masses: Mass[], most = 8): string {
  if (!masses.length) return 'no clear masses';
  const lights = masses.filter(mass => mass.light).sort((a, b) => b.share - a.share).slice(0, 3);
  const shown = [...masses.filter(mass => !mass.light).sort((a, b) => b.share - a.share).slice(0, most - lights.length), ...lights];
  const parts = shown.map(mass => `${Math.max(1, percent(mass.share))}% ${colourWords(mass.fill)}${mass.light ? ' (light)' : ''} ${place(mass.centre)}`
    + ` [x ${percent(mass.box[0])}-${percent(mass.box[2])}%, y ${percent(mass.box[1])}-${percent(mass.box[3])}%]`);
  return `${masses.length} masses, largest first: ${parts.join('; ')}`;
}

// ------------------------------------------------------------------------------------------- draw_guide's masses option

/** The smoothed crop the plugin returns (reference-tool.mjs massReferencePixels): its pixels and the crop it shows. */
export type MassPixels = Pixels & { source?: number[]; ms?: number };
type Rect = [number, number, number, number];
export type MassRequest = { reference_id: string; source?: number[]; target: number[]; shape?: unknown; detail?: 'simple' | 'medium' };
export type MassContext = {
  study?: { references?: { id: string; width?: number; height?: number }[] };
  decisionObservation?: { width?: unknown; height?: unknown } | null;
};
export type MassDependencies = {
  mapPoint(source: number[], target: number[]): (x: number, y: number) => [number, number];
  /** The plugin's smoothed copy of `source` (reference pixels) of a reference (reference-tool.mjs massReferencePixels). */
  massPixels?(id: string, source: number[]): Promise<MassPixels>;
  /** The decode an element's shape was found in (guide-tool.ts tracedLines: referencePixels at shapeSide), to read its mask. */
  referencePixels?(id: string, maxSide: number): Promise<Pixels>;
  shapeSide?(width: number, height: number, source: number[]): number;
  vectorize?: Vectorize;
};
/** An element's shape as guide-tool.ts found it: bounds and mask in the pixels of the shape decode. */
export type FoundShape = { bounds: number[]; data: Uint8Array } | null;
export type GuideMassLine = { points: Point[]; weight: 'light' | 'construction' };

/** from_reference masses: the masses inside source (or inside the element's shape, when one was found) as guide lines
 * on the canvas: light masses' boundaries warm ('light'), the others thin ('construction'). The shape's own outline is
 * left out (guide-tool.ts draws it as the contour). Also the masses, for the painter's summary. */
export async function massGuideLines(runtime: MassContext, from: MassRequest, dependencies: MassDependencies, found: FoundShape = null,
  room = MASS_LINES): Promise<{ lines: GuideMassLine[]; masses: Mass[]; ms: number; paths: number }> {
  const reference = runtime.study?.references?.find(item => item.id === from.reference_id);
  if (!reference) throw new Error('Unknown reference ID. Use the attachment list in the study context.');
  if (room < 1) throw new Error('No room for the masses in this call (with your own lines and perspective): draw them in their own draw_guide call.');
  if (!dependencies.massPixels) throw new Error('Masses need the plugin’s smoothed reference, which this companion cannot ask for.');
  const canvas = runtime.decisionObservation;
  if (!(Number(canvas?.width) > 0 && Number(canvas?.height) > 0))
    throw new Error('A guide from a reference is placed on the canvas: look at the canvas first (observe), then draw it.');
  const width = reference.width ?? 0, height = reference.height ?? 0;
  const fits = (r: number[]) => (r[2] ?? 0) > 0 && (r[3] ?? 0) > 0 && (r[0] ?? -1) >= 0 && (r[1] ?? -1) >= 0
    && (r[0] ?? 0) + (r[2] ?? 0) <= width && (r[1] ?? 0) + (r[3] ?? 0) <= height;
  const whole = (box: number[]): Rect => {               // whole reference pixels covering box, clamped to the reference
    const left = Math.max(0, Math.floor(box[0] ?? 0)), top = Math.max(0, Math.floor(box[1] ?? 0));
    return [left, top, Math.min(width, Math.ceil((box[0] ?? 0) + (box[2] ?? 0))) - left, Math.min(height, Math.ceil((box[1] ?? 0) + (box[3] ?? 0))) - top];
  };
  let crop: Rect, map: (x: number, y: number) => [number, number], inside: ((x: number, y: number) => boolean) | undefined;
  if (!found) {
    crop = (from.source as Rect | undefined) ?? [0, 0, width, height];
    if (!fits(crop)) throw new Error('Source crop must fit the reference.');
    map = dependencies.mapPoint(crop, from.target);
  } else {
    if (!dependencies.referencePixels || !dependencies.shapeSide) throw new Error('Masses inside a shape need the shape’s decode.');
    const decoded = await dependencies.referencePixels(from.reference_id, dependencies.shapeSide(width, height, [0, 0, width, height]));
    const kx = decoded.width / width, ky = decoded.height / height;
    const [bx = 0, by = 0, bw = 0, bh = 0] = found.bounds;
    const own: Rect = [bx / kx, by / ky, bw / kx, bh / ky];
    crop = whole(own);
    inside = (x, y) => {
      const px = Math.floor(x * kx - bx), py = Math.floor(y * ky - by);
      return px >= 0 && py >= 0 && px < bw && py < bh && (found.data[py * bw + px] ?? 0) > 127;
    };
    // The same mapping as the shape's outline (guide-tool.ts tracedLines): the source given, the box prompt's own box, or
    // with points the shape fitted into target, centred, its proportions kept.
    const prompt = from.shape as { box?: number[] } | undefined;
    if (from.source) map = dependencies.mapPoint(from.source, from.target);
    else if (prompt?.box) map = dependencies.mapPoint(whole(prompt.box), from.target);
    else {
      const [tx = 0, ty = 0, tw = 0, th = 0] = from.target, scale = Math.min(tw / own[2], th / own[3]);
      map = dependencies.mapPoint(own, [tx + (tw - own[2] * scale) / 2, ty + (th - own[3] * scale) / 2, own[2] * scale, own[3] * scale]);
    }
  }
  const smoothed = await dependencies.massPixels(from.reference_id, crop);
  const shown = smoothed.source ?? crop, sx = smoothed.width / (shown[2] ?? 1), sy = smoothed.height / (shown[3] ?? 1);
  const toReference = (x: number, y: number): Point => [(shown[0] ?? 0) + x / sx, (shown[1] ?? 0) + y / sy];
  const started = performance.now();
  const traced = await traceMasses(smoothed, {
    ...(inside ? { inside: (x: number, y: number) => inside(...toReference(x, y)) } : {}),
    limit: from.detail === 'medium' ? MASS_LIMIT : Math.round(MASS_LIMIT / 2), maxLines: Math.min(MASS_LINES, room),
    ...(dependencies.vectorize ? { vectorize: dependencies.vectorize } : {}) });
  const lines = traced.lines.map(line => ({ weight: line.light ? 'light' as const : 'construction' as const,
    points: line.points.map(([x, y]) => map(...toReference(x, y))) }));
  return { lines, masses: traced.masses, paths: traced.paths, ms: Math.round(performance.now() - started) + (smoothed.ms ?? 0) };
}
