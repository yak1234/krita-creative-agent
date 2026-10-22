// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Guides from a reference's own edges (draw_guide from_reference): the element's outline and inner structural lines,
// and the outlines of its brightest shapes, as a few clean polylines in reference pixels. guide-tool.ts maps them onto
// the canvas with the reference tools' mapping and draws them as guide lines; no reference pixel reaches the canvas.
//
// Ruling: this runs in the companion, as paint_reference_edges does (the plugin only decodes the reference), so the
// plugin's draw_guide stays a painter of lines and the work is testable without Krita.
//
// Method, on the source crop shrunk to about WORK cells on its long side (block means, which also average texture):
// - silhouette: a lightly blurred luminance split at Otsu's threshold, used only when the split is clearly two-toned
//   (blurred texture noise is one-toned); specks and holes smaller than a share of the crop are dropped; the boundary is
//   traced with marching squares (it stops at the crop's edge, which is never an outline);
// - inner structure: edges of a more blurred luminance, thinned (non-maximum suppression) and followed while they keep
//   their direction; only long ones that run straight or gently curved are kept, and none along the silhouette;
// - lights: the brightest share of the crop, well above its median, traced like the silhouette.
// Every line is simplified (Douglas-Peucker), at most GUIDE_POINTS points, and only the longest are kept.
//
// With an element's shape (element-shapes 1.4: one element's pixels, found by the shape service from a box or points),
// the shape stands in for the silhouette: everything outside it counts as transparent, so the outline is the shape's
// boundary and inner structure and lights are found only inside it. Clutter in the same box gives no line.

export type Pixels = { width: number; height: number; data: Uint8Array | Buffer };
export type Detail = 'simple' | 'medium';
/** One element's shape on the image: one byte a pixel of bounds [x,y,w,h], above 127 inside. */
export type Shape = { bounds: number[]; data: Uint8Array };
type Point = [number, number];

export const TRACE_LIMITS = { simple: 8, medium: 24 } as const;
export const LIGHT_LIMIT = 8;
const POINTS = 64;                                   // guide-tool.ts GUIDE_POINTS
const WORK = 360;                                    // cells on the working grid's long side
const SETTINGS = {
  //       smallest speck kept (share of the crop), simplification (cells), structure edge threshold, shortest edge chain (share of the long side)
  simple: { area: 0.005, epsilon: 1.2, edge: 0.12, chain: 0.12, lightArea: 0.002 },
  medium: { area: 0.0015, epsilon: 0.7, edge: 0.08, chain: 0.06, lightArea: 0.0005 },
} as const;
// Otsu's separability (between-class / total variance) a crop needs before its split is taken for a silhouette: a
// silhouette against its ground is clearly two-toned, while blurred texture noise is about 0.64.
const TWO_TONE = 0.72;
const STRAIGHT_RUN = 10;                             // cells per straight piece a structural line has at least, on average

type Grid = { w: number; h: number; f: number; sx: number; sy: number; L: Float32Array; A: Float32Array };

/** The crop as block means: luminance 0-1 (transparent counts as dark, as in the edge tools) and alpha 0-1; outside
 * the shape, when one is given, counts as transparent. */
function grid(image: Pixels, source: number[], shape?: Shape): Grid {
  const [sx = 0, sy = 0, sw = 0, sh = 0] = source;
  if (!(sw > 0 && sh > 0 && sx >= 0 && sy >= 0 && sx + sw <= image.width && sy + sh <= image.height)) throw new Error('Source crop must fit the reference.');
  if (image.data.length !== image.width * image.height * 4) throw new Error('Invalid decoded reference.');
  const [bx = 0, by = 0, bw = 0, bh = 0] = shape?.bounds ?? [];
  if (shape && shape.data.length !== bw * bh) throw new Error('Invalid shape.');
  const f = Math.max(1, Math.ceil(Math.max(sw, sh) / WORK)), w = Math.ceil(sw / f), h = Math.ceil(sh / f);
  const L = new Float32Array(w * h), A = new Float32Array(w * h), n = new Float32Array(w * h);
  for (let y = 0; y < sh; y++) for (let x = 0; x < sw; x++) {
    const i = ((sy + y) * image.width + sx + x) * 4, k = Math.floor(y / f) * w + Math.floor(x / f), d = image.data;
    let alpha = (d[i + 3] ?? 0) / 255;
    if (shape) {
      const px = sx + x - bx, py = sy + y - by;
      alpha *= px >= 0 && py >= 0 && px < bw && py < bh ? (shape.data[py * bw + px] ?? 0) / 255 : 0;
    }
    L[k] = (L[k] ?? 0) + ((d[i] ?? 0) * 0.2126 + (d[i + 1] ?? 0) * 0.7152 + (d[i + 2] ?? 0) * 0.0722) / 255 * alpha;
    A[k] = (A[k] ?? 0) + alpha; n[k] = (n[k] ?? 0) + 1;
  }
  for (let k = 0; k < w * h; k++) { L[k] = (L[k] ?? 0) / (n[k] || 1); A[k] = (A[k] ?? 0) / (n[k] || 1); }
  return { w, h, f, sx, sy, L, A };
}

/** Two passes of a separable box blur of radius r. */
function blur(values: Float32Array, w: number, h: number, r: number): Float32Array {
  let out = values;
  for (let pass = 0; pass < 2; pass++) {
    const tmp = new Float32Array(values.length), next = new Float32Array(values.length);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let sum = 0, n = 0;
      for (let d = -r; d <= r; d++) { const xx = x + d; if (xx >= 0 && xx < w) { sum += out[y * w + xx] ?? 0; n++; } }
      tmp[y * w + x] = sum / n;
    }
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let sum = 0, n = 0;
      for (let d = -r; d <= r; d++) { const yy = y + d; if (yy >= 0 && yy < h) { sum += tmp[yy * w + x] ?? 0; n++; } }
      next[y * w + x] = sum / n;
    }
    out = next;
  }
  return out;
}

/** Otsu's threshold of values in 0-1, and how well it separates them (0-1). */
function otsu(values: Float32Array): { threshold: number; separability: number } {
  const bins = new Float64Array(256);
  let mean = 0;
  for (const v of values) { bins[Math.max(0, Math.min(255, Math.round(v * 255)))]! += 1; mean += v; }
  const total = values.length; mean /= total;
  let variance = 0;
  for (const v of values) variance += (v - mean) ** 2;
  variance /= total;
  if (variance < 1e-5) return { threshold: 1, separability: 0 };
  let best = 0, threshold = 0.5, weight = 0, sum = 0;
  for (let t = 0; t < 255; t++) {
    weight += bins[t]!; sum += t / 255 * bins[t]!;
    if (!weight || weight === total) continue;
    const low = sum / weight, high = (mean * total - sum) / (total - weight);
    const between = weight / total * (1 - weight / total) * (low - high) ** 2;
    if (between > best) { best = between; threshold = (t + 0.5) / 255; }
  }
  return { threshold, separability: best / variance };
}

/** Components (4-connected) of `value` smaller than `area` cells take the other value: specks and holes go. */
function dropSmall(mask: Uint8Array, w: number, h: number, area: number, value: number): void {
  const seen = new Uint8Array(mask.length), stack: number[] = [], members: number[] = [];
  for (let start = 0; start < mask.length; start++) {
    if (seen[start] || mask[start] !== value) continue;
    stack.push(start); seen[start] = 1; members.length = 0;
    while (stack.length) {
      const k = stack.pop()!; members.push(k);
      const x = k % w, y = (k - x) / w;
      for (const [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]] as const) {
        if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
        const n = ny * w + nx;
        if (!seen[n] && mask[n] === value) { seen[n] = 1; stack.push(n); }
      }
    }
    if (members.length < area) for (const k of members) mask[k] = 1 - value;
  }
}

/** The boundary of a mask (cell centres at integer + 0.5 of the grid), as chains in grid coordinates: marching squares,
 * a saddle split so the mask's diagonal neighbours stay apart; open chains end at the grid's edge. */
function boundaries(mask: Uint8Array, w: number, h: number): Point[][] {
  const at = (x: number, y: number) => mask[y * w + x] ?? 0;
  const position = new Map<string, Point>(), links = new Map<string, string[]>();
  const link = (a: string, pa: Point, b: string, pb: Point) => {
    position.set(a, pa); position.set(b, pb);
    links.set(a, [...(links.get(a) ?? []), b]); links.set(b, [...(links.get(b) ?? []), a]);
  };
  for (let y = 0; y + 1 < h; y++) for (let x = 0; x + 1 < w; x++) {
    const tl = at(x, y), tr = at(x + 1, y), bl = at(x, y + 1), br = at(x + 1, y + 1);
    const edges: [string, Point][] = [];
    if (tl !== tr) edges.push([`h${x},${y}`, [x + 1, y + 0.5]]);           // top (centres at +0.5)
    if (tr !== br) edges.push([`v${x + 1},${y}`, [x + 1.5, y + 1]]);       // right
    if (bl !== br) edges.push([`h${x},${y + 1}`, [x + 1, y + 1.5]]);       // bottom
    if (tl !== bl) edges.push([`v${x},${y}`, [x + 0.5, y + 1]]);           // left
    if (edges.length === 2) link(edges[0]![0], edges[0]![1], edges[1]![0], edges[1]![1]);
    else if (edges.length === 4) {
      const [top, right, bottom, left] = edges as [[string, Point], [string, Point], [string, Point], [string, Point]];
      if (tl) { link(top[0], top[1], left[0], left[1]); link(bottom[0], bottom[1], right[0], right[1]); }
      else { link(top[0], top[1], right[0], right[1]); link(bottom[0], bottom[1], left[0], left[1]); }
    }
  }
  const used = new Set<string>(), chains: Point[][] = [];
  const walk = (start: string) => {
    const chain: Point[] = [position.get(start)!];
    used.add(start);
    let current = start;
    for (;;) {
      const next = (links.get(current) ?? []).find(key => !used.has(key));
      if (next === undefined) {
        if ((links.get(current) ?? []).includes(start) && chain.length > 2) chain.push(position.get(start)!);   // a loop closes
        break;
      }
      used.add(next); chain.push(position.get(next)!); current = next;
    }
    if (chain.length > 1) chains.push(chain);
  };
  for (const [key, ends] of links) if (ends.length === 1 && !used.has(key)) walk(key);
  for (const key of links.keys()) if (!used.has(key)) walk(key);
  return chains;
}

/** Long, coherent edges of the blurred luminance away from the silhouette, as chains in grid coordinates. */
function structure(L: Float32Array, w: number, h: number, mask: Uint8Array | null, threshold: number, shortest: number, epsilon: number, inside = false): Point[][] {
  const at = (x: number, y: number) => L[Math.max(0, Math.min(h - 1, y)) * w + Math.max(0, Math.min(w - 1, x))] ?? 0;
  const GX = new Float32Array(w * h), GY = new Float32Array(w * h), M = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const gx = (at(x + 1, y - 1) + 2 * at(x + 1, y) + at(x + 1, y + 1) - at(x - 1, y - 1) - 2 * at(x - 1, y) - at(x - 1, y + 1)) / 4;
    const gy = (at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1) - at(x - 1, y - 1) - 2 * at(x, y - 1) - at(x + 1, y - 1)) / 4;
    const k = y * w + x; GX[k] = gx; GY[k] = gy; M[k] = Math.hypot(gx, gy);
  }
  // Thin: a cell is an edge only where it is the strongest across the edge.
  const edge = new Uint8Array(w * h), low = threshold / 2;
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const k = y * w + x, m = M[k]!;
    if (m < low) continue;
    const dx = Math.round(GX[k]! / m), dy = Math.round(GY[k]! / m);
    if (m >= (M[(y + dy) * w + x + dx] ?? 0) && m >= (M[(y - dy) * w + x - dx] ?? 0)) edge[k] = 1;
  }
  // Not along the silhouette: cells within 2 of its boundary are taken already.
  const taken = new Uint8Array(w * h);
  if (mask) for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const k = y * w + x;
    if ((x + 1 < w && mask[k] !== mask[k + 1]) || (y + 1 < h && mask[k] !== mask[k + w]))
      for (let yy = Math.max(0, y - 2); yy <= Math.min(h - 1, y + 3); yy++) for (let xx = Math.max(0, x - 2); xx <= Math.min(w - 1, x + 3); xx++) taken[yy * w + xx] = 1;
  }
  if (mask && inside) for (let k = 0; k < w * h; k++) if (!mask[k]) taken[k] = 1;     // a shape's structure lies inside it
  const seeds: number[] = [];
  for (let k = 0; k < w * h; k++) if (edge[k] && M[k]! >= threshold) seeds.push(k);
  seeds.sort((a, b) => M[b]! - M[a]! || a - b);
  const chains: Point[][] = [];
  for (const seed of seeds) {
    if (taken[seed]) continue;
    const x0 = seed % w, y0 = (seed - x0) / w, path: Point[] = [[x0, y0]], cells = [seed];
    const tangent = (k: number): Point => [-GY[k]! / M[k]!, GX[k]! / M[k]!];
    for (const direction of [1, -1]) {
      let [x, y] = [x0, y0];
      let [dx, dy] = tangent(seed).map(v => v * direction) as Point;
      for (;;) {
        let best = -1, bestScore = 0.7;                      // the next cell within about 45 degrees of the way it runs
        for (let ny = -1; ny <= 1; ny++) for (let nx = -1; nx <= 1; nx++) {
          if (!nx && !ny) continue;
          const xx = x + nx, yy = y + ny, k = yy * w + xx;
          if (xx < 0 || yy < 0 || xx >= w || yy >= h || !edge[k] || taken[k] || cells.includes(k)) continue;
          const step = (nx * dx + ny * dy) / Math.hypot(nx, ny), [ex, ey] = tangent(k), along = Math.abs(ex * dx + ey * dy);
          const score = Math.min(step, along);
          if (score > bestScore) { bestScore = score; best = k; }
        }
        if (best < 0) break;
        const bx = best % w, by = (best - bx) / w;
        let [ex, ey] = tangent(best);
        if (ex * dx + ey * dy < 0) { ex = -ex; ey = -ey; }
        direction > 0 ? path.push([bx, by]) : path.unshift([bx, by]);
        cells.push(best); x = bx; y = by; dx = ex; dy = ey;
      }
    }
    for (const k of cells) {
      const cx = k % w, cy = (k - cx) / w;
      for (let yy = Math.max(0, cy - 1); yy <= Math.min(h - 1, cy + 1); yy++) for (let xx = Math.max(0, cx - 1); xx <= Math.min(w - 1, cx + 1); xx++) taken[yy * w + xx] = 1;
    }
    // Structure runs straight or gently curved: a chain that needs a corner every few cells is texture wandering.
    const run = length(path);
    if (run >= shortest && simplifyPolyline(path, epsilon).length - 1 <= Math.max(2, run / STRAIGHT_RUN))
      chains.push(path.map(([x, y]): Point => [x + 0.5, y + 0.5]));
  }
  return chains;
}

const length = (points: Point[]) => points.slice(1).reduce((n, p, i) => n + Math.hypot(p[0] - points[i]![0], p[1] - points[i]![1]), 0);

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

/** Chains in grid coordinates to simplified polylines in reference pixels, the longest first, at most `limit`. */
function finish(chains: { points: Point[]; weight: number }[], g: Grid, epsilon: number, limit: number): Point[][] {
  return chains
    .map(({ points, weight }) => {
      let e = epsilon, simple = simplifyPolyline(points, e);
      while (simple.length > POINTS) { e *= 1.5; simple = simplifyPolyline(points, e); }
      return { points: simple.map(([x, y]): Point => [g.sx + x * g.f, g.sy + y * g.f]), score: length(points) * weight };
    })
    .filter(line => line.points.length >= 2)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map(line => line.points);
}

/** The crop to trace a shape on: its bounds and a margin (so its outline never lies on the crop's edge), on the image. */
export function shapeSource(bounds: number[], width: number, height: number): number[] {
  const [x = 0, y = 0, w = 0, h = 0] = bounds, margin = Math.ceil(0.03 * Math.max(w, h)) + 2;
  const left = Math.max(0, x - margin), top = Math.max(0, y - margin);
  return [left, top, Math.min(width, x + w + margin) - left, Math.min(height, y + h + margin) - top];
}

/** The element's outline and inner structural lines inside `source` [x,y,w,h], in reference pixels; with a shape,
 * its boundary and the structure inside it only. */
export function traceOutlines(image: Pixels, source: number[], detail: Detail = 'simple', shape?: Shape): Point[][] {
  const g = grid(image, source, shape), { w, h } = g, settings = SETTINGS[detail], cells = w * h;
  const smooth = blur(g.L, w, h, 1);
  let mask: Uint8Array | null = null;
  // A part (see-through outside the area the artist chose) is outlined by its alpha.
  let clear = 0;
  for (const a of g.A) if (a < 0.5) clear++;
  if (shape || (clear > cells * 0.02 && clear < cells * 0.98)) {
    mask = new Uint8Array(cells);
    for (let k = 0; k < cells; k++) mask[k] = g.A[k]! >= 0.5 ? 1 : 0;
  } else {
    const { threshold, separability } = otsu(smooth);
    if (separability >= TWO_TONE) {
      mask = new Uint8Array(cells);
      for (let k = 0; k < cells; k++) mask[k] = smooth[k]! > threshold ? 1 : 0;
    }
  }
  const chains: { points: Point[]; weight: number }[] = [];
  const shortest = settings.chain * Math.max(w, h);
  if (mask) {
    const area = Math.max(4, settings.area * cells);
    dropSmall(mask, w, h, area, 1); dropSmall(mask, w, h, area, 0);
    for (const points of boundaries(mask, w, h)) if (length(points) >= shortest / 2) chains.push({ points, weight: 1.5 });
  }
  for (const points of structure(blur(g.L, w, h, 2), w, h, mask, settings.edge, shortest, settings.epsilon, !!shape)) chains.push({ points, weight: 1 });
  return finish(chains, g, settings.epsilon, TRACE_LIMITS[detail]);
}

/** The outlines of the brightest shapes inside `source`, measured over its opaque cells only (a part's transparent
 * surround is no dark ground): cells well above the darker class (Otsu's low mean), and in the top few percent unless
 * the light fills most of the crop (a moon cropped to its box). */
export function traceLights(image: Pixels, source: number[], detail: Detail = 'simple', shape?: Shape): Point[][] {
  const g = grid(image, source, shape), { w, h } = g, settings = SETTINGS[detail], cells = w * h;
  const smooth = blur(g.L, w, h, 1);
  const opaque = Float32Array.from(Array.from(smooth).filter((_, k) => g.A[k]! >= 0.5)).sort();
  if (opaque.length < 4) return [];
  const { threshold: split } = otsu(opaque);
  let low = 0, n = 0;
  for (const v of opaque) if (v <= split) { low += v; n++; }
  const dark = n ? low / n : opaque[0]!, top = opaque[opaque.length - 1]!, high = opaque[Math.floor(opaque.length * 0.95)]!;
  if (top - dark < 0.25) return [];
  const threshold = Math.max((top + dark) / 2, Math.min(high, top - 0.25 * (top - dark)));
  const mask = new Uint8Array(cells);
  for (let k = 0; k < cells; k++) mask[k] = smooth[k]! >= threshold && g.A[k]! >= 0.5 ? 1 : 0;
  const area = Math.max(4, settings.lightArea * cells);
  dropSmall(mask, w, h, area, 1); dropSmall(mask, w, h, area, 0);
  return finish(boundaries(mask, w, h).map(points => ({ points, weight: 1 })), g, settings.epsilon, LIGHT_LIMIT);
}
