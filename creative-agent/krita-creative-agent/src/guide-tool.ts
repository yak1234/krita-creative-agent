// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Guided trace (project-folder A2): the painter's draw_guide and finish_guide. A guide is a few construction lines
// (horizon, vanishing lines, a silhouette's block-in, key proportions) on the element's own guide layer, which the
// plugin paints in its guide brush (guide_craft.py). Lines are canvas pixels, or reference pixels mapped exactly as the
// reference tools map them (mapReferencePoint). The guided-trace skill says when and what to draw.
// The studio's native call and the mapping come in as dependencies, so this module imports no .mjs.
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';

const object = <T extends Parameters<typeof Type.Object>[0]>(properties: T) => Type.Object(properties, { additionalProperties: false });
const rect = (description: string) => Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4, description });
const point = Type.Array(Type.Number({ minimum: -100000, maximum: 100000 }), { minItems: 2, maxItems: 2 });

export const GUIDE_LINES = 128;
export const GUIDE_POINTS = 64;
export const GUIDE_WEIGHTS = ['construction', 'contour', 'light'] as const;
export type GuideWeight = typeof GUIDE_WEIGHTS[number];
const weight = Type.Union(GUIDE_WEIGHTS.map(name => Type.Literal(name)), { description:
  'construction: thin (eye level, rays, centre lines); contour: stronger (silhouettes, the default); light: warm, the outline of a light source or the brightest areas. Widths follow the canvas size.' });
export const DEFAULT_RAYS = 8;
const perspectiveSchema = object({
  eye_level_y: Type.Optional(Type.Number({ minimum: -100000, maximum: 100000, description: 'The eye level (horizon) in canvas pixels: drawn across the canvas.' })),
  vanishing_points: Type.Optional(Type.Array(point, { maxItems: 3, description: 'Vanishing points [x,y] in canvas pixels, on or off the canvas (usually on the eye level).' })),
  rays: Type.Optional(Type.Integer({ minimum: 2, maximum: 24, description: `Rays fanned from each vanishing point across the canvas (default ${DEFAULT_RAYS}).` })),
});
const drawSchema = object({
  element: Type.String({ minLength: 1, maxLength: 60, description: 'The element this guide is for, as its layer will be named ("Kremlin towers").' }),
  reference_id: Type.Optional(Type.String({ minLength: 1, description: 'Points are pixels of this attached reference, mapped from source onto target.' })),
  source: Type.Optional(rect('[x,y,w,h] of the reference the lines come from (default: the whole reference).')),
  target: Type.Optional(rect('[x,y,w,h] of the canvas the source maps onto, same aspect ratio. Needed with reference_id.')),
  lines: Type.Optional(Type.Array(object({
    points: Type.Array(point, { minItems: 2, maxItems: GUIDE_POINTS, description: 'A polyline: straight segments from point to point.' }),
    weight: Type.Optional(weight),
  }), { minItems: 1, maxItems: GUIDE_LINES })),
  perspective: Type.Optional(perspectiveSchema),
  replace: Type.Optional(Type.Boolean({ description: 'Tighten: hide this element\u2019s earlier guide and draw on a new layer (undoing the move shows it again).' })),
});
const finishSchema = object({ element: Type.String({ minLength: 1, maxLength: 60 }) });

type Rect = [number, number, number, number];
type Reference = { id: string; width?: number; height?: number };
type Result = AgentToolResult<unknown>;
export type GuideRuntime = { study?: { references?: Reference[] };
  decisionObservation?: { width?: unknown; height?: unknown } | null; emit(event: Record<string, unknown>): void };
type Point = [number, number];

/** The part of segment a-b inside [0,width] x [0,height] (Liang-Barsky), or null when none is. */
function clipSegment(a: Point, b: Point, width: number, height: number): [Point, Point] | null {
  let low = 0, high = 1;
  const dx = b[0] - a[0], dy = b[1] - a[1];
  for (const [p, q] of [[-dx, a[0]], [dx, width - a[0]], [-dy, a[1]], [dy, height - a[1]]] as const) {
    if (p === 0) { if (q < 0) return null; continue; }
    const r = q / p;
    if (p < 0) { if (r > high) return null; low = Math.max(low, r); }
    else { if (r < low) return null; high = Math.min(high, r); }
  }
  return [[a[0] + low * dx, a[1] + low * dy], [a[0] + high * dx, a[1] + high * dy]];
}

/** A polyline cut to the canvas: the pieces of it on the canvas (a line that leaves and comes back is two). */
export function clipPolyline(points: Point[], width: number, height: number): Point[][] {
  const pieces: Point[][] = [];
  let current: Point[] | null = null;
  for (let index = 1; index < points.length; index++) {
    const from = points[index - 1], to = points[index];
    const clipped = from && to ? clipSegment(from, to, width, height) : null;
    if (!clipped || (clipped[0][0] === clipped[1][0] && clipped[0][1] === clipped[1][1])) { current = null; continue; }   // a touch is no line
    const last = current?.at(-1);
    if (current && last && last[0] === clipped[0][0] && last[1] === clipped[0][1]) current.push(clipped[1]);
    else { current = [clipped[0], clipped[1]]; pieces.push(current); }
  }
  return pieces;
}
export type GuideDependencies = {
  /** The studio's native call for an operation: revision, stage and recovery handling, the canvas image in the result. */
  execute(operation: 'draw_guide' | 'finish_guide'): (id: string, params: Record<string, unknown>, signal?: AbortSignal) => Promise<Result>;
  /** reference-generator.mjs mapReferencePoint: throws for a source and target of different aspect ratios. */
  mapPoint(source: number[], target: number[]): (x: number, y: number) => [number, number];
};
export type GuideStroke = { start: [number, number]; segments: number[][]; weight: GuideWeight };
type Line = { points: Point[]; weight: GuideWeight };

/** Eye level and rays (construction lines, canvas pixels): each vanishing point fans `rays` rays evenly across the
 * angle under which it sees the canvas (all round when it lies on the canvas), each long enough to cross it. */
/** How many lines perspectiveLines draws. */
export const perspectiveCount = (perspective?: Static<typeof perspectiveSchema>) => !perspective ? 0
  : (perspective.eye_level_y !== undefined ? 1 : 0) + (perspective.vanishing_points?.length ?? 0) * (perspective.rays ?? DEFAULT_RAYS);

export function perspectiveLines(perspective: Static<typeof perspectiveSchema>, width: number, height: number): Line[] {
  const lines: Line[] = [];
  if (perspective.eye_level_y !== undefined) lines.push({ points: [[0, perspective.eye_level_y], [width, perspective.eye_level_y]], weight: 'construction' });
  const corners: Point[] = [[0, 0], [width, 0], [width, height], [0, height]];
  const count = perspective.rays ?? DEFAULT_RAYS;
  for (const vp of perspective.vanishing_points ?? []) {
    const [vx, vy] = [vp[0] ?? 0, vp[1] ?? 0];
    const reach = Math.max(...corners.map(([x, y]) => Math.hypot(x - vx, y - vy))) + 1;
    // Well inside the canvas the rays go all round; on or near its edge (or off it) they fan across the canvas only.
    const margin = 0.05 * Math.min(width, height);
    const inside = vx > margin && vx < width - margin && vy > margin && vy < height - margin;
    let low = 0, span = 2 * Math.PI;
    if (!inside) {
      const centre = Math.atan2(height / 2 - vy, width / 2 - vx);
      const offsets = corners.filter(([x, y]) => Math.hypot(x - vx, y - vy) > 1e-6).map(([x, y]) => { let a = Math.atan2(y - vy, x - vx) - centre; while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; });
      low = centre + Math.min(...offsets); span = Math.max(...offsets) - Math.min(...offsets);
    }
    for (let index = 0; index < count; index++) {
      const angle = low + (index + 0.5) * span / count;
      lines.push({ points: [[vx, vy], [vx + Math.cos(angle) * reach, vy + Math.sin(angle) * reach]], weight: 'construction' });
    }
  }
  return lines;
}

/** The plugin's strokes for a draw_guide call: one per polyline, its points mapped to canvas pixels. */
export function guideStrokes(runtime: GuideRuntime, args: Static<typeof drawSchema>, mapPoint: GuideDependencies['mapPoint']): GuideStroke[] {
  let map = (x: number, y: number): [number, number] => [x, y];
  if (args.reference_id !== undefined) {
    const reference = runtime.study?.references?.find(item => item.id === args.reference_id);
    if (!reference) throw new Error('Unknown reference ID. Use the attachment list in the study context.');
    if (!args.target) throw new Error('A guide from a reference needs target: the canvas rectangle [x,y,w,h] the reference area maps onto.');
    const width = reference.width ?? 0, height = reference.height ?? 0;
    const source: Rect = (args.source as Rect | undefined) ?? [0, 0, width, height];
    if (!(source[2] > 0 && source[3] > 0 && source[0] + source[2] <= width && source[1] + source[3] <= height))
      throw new Error('Source crop must fit the reference.');
    map = mapPoint(source, args.target);
  } else if (args.source || args.target) {
    throw new Error('source and target map reference pixels: give them with reference_id, or leave them out for canvas pixels.');
  }
  // Cut to the canvas the painter last saw, so a point off it does not refuse the whole guide; before any look the
  // plugin checks the points.
  const canvas = runtime.decisionObservation, width = Number(canvas?.width), height = Number(canvas?.height);
  const known = Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0;
  if (!args.lines?.length && !args.perspective)
    throw new Error('A guide needs lines or perspective.');
  if (args.perspective && args.perspective.eye_level_y === undefined && !args.perspective.vanishing_points?.length)
    throw new Error('perspective needs eye_level_y or vanishing_points (canvas pixels).');
  if (args.perspective && !known) throw new Error('Perspective rays cross the whole canvas: look at the canvas first (observe), then draw them.');
  // Construction first, then the painter's own lines: later lines draw over earlier ones.
  const lines: Line[] = [
    ...(args.perspective ? perspectiveLines(args.perspective, width, height) : []),
    ...(args.lines ?? []).map(line => ({ points: line.points.map(([x, y]): Point => map(x ?? 0, y ?? 0)), weight: line.weight ?? 'contour' as GuideWeight })),
  ];
  if (lines.length > GUIDE_LINES) throw new Error(`At most ${GUIDE_LINES} guide lines in one call; draw again for the same element to add more.`);
  const strokes: GuideStroke[] = [];
  for (const { points, weight } of lines) {
    for (const piece of known ? clipPolyline(points, width, height) : [points]) {
      const segments = piece.slice(1).map((end, index) => {
        const from = piece[index] ?? end;
        return [from[0], from[1], end[0], end[1], end[0], end[1]];
      });
      strokes.push({ start: piece[0] ?? [0, 0], segments, weight });
    }
  }
  if (!strokes.length) throw new Error('Every guide line lies outside the canvas: give points inside it (canvas pixels, or a target on the canvas).');
  return strokes;
}

export function guideTools(runtime: GuideRuntime, dependencies: GuideDependencies): ToolDefinition<any, unknown>[] {
  const draw = dependencies.execute('draw_guide'), finish = dependencies.execute('finish_guide');
  return [
    {
      name: 'draw_guide', label: 'Drawing a guide', executionMode: 'sequential', parameters: drawSchema,
      description: 'Sketch construction lines for one element before painting it, a few dozen at most, on the element’s '
        + 'own guide layer (light blue, warm for light; never merged, never judged as the painting). perspective draws the '
        + 'eye level and rays from vanishing points; each line has a weight (construction, contour, light). Points are '
        + 'canvas pixels, or with reference_id pixels of that reference mapped from source onto target (same aspect). '
        + 'Only when the artist asks for guides; nothing is traced from a reference. '
        + 'Draw again to add lines; replace: true tightens (the earlier guide is hidden). Read the guided-trace skill '
        + 'first. Paint the element over the guide in your own strokes, then finish_guide.',
      execute: async (id: string, args: Static<typeof drawSchema>, signal?: AbortSignal): Promise<Result> => {
        signal?.throwIfAborted();
        const strokes = guideStrokes(runtime, args, dependencies.mapPoint);
        const result = await draw(id, { element: args.element, strokes, ...(args.replace ? { replace: true } : {}) }, signal);
        runtime.emit({ type: 'action', seconds: 0, message: `Drew a guide for ${args.element} (hidden when the element is finished).` });
        return result;
      },
    },
    {
      name: 'finish_guide', label: 'Finishing a guide', executionMode: 'sequential', parameters: finishSchema,
      description: 'Hide the element’s guide once the element is painted. The artist can show it again; it is never '
        + 'deleted or merged. Call it before moving on to the next element.',
      execute: async (id: string, args: Static<typeof finishSchema>, signal?: AbortSignal): Promise<Result> => {
        signal?.throwIfAborted();
        const result = await finish(id, { element: args.element }, signal);
        runtime.emit({ type: 'action', seconds: 0, message: `The guide for ${args.element} is hidden.` });
        return result;
      },
    },
  ];
}
