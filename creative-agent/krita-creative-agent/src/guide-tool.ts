// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Guided trace (project-folder A2): the painter's draw_guide and finish_guide. A guide is a few construction lines
// (horizon, vanishing lines, a silhouette's block-in, key proportions) on the element's own guide layer, which the
// plugin paints in its guide brush (guide_craft.py). Lines are canvas pixels, or reference pixels mapped exactly as the
// reference tools map them (mapReferencePoint). The guided-trace skill says when and what to draw.
// The studio's native call and the mapping come in as dependencies, so this module imports no .mjs.
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';
import { SCALE_RANGE, findBigShapes, labelMap, shapeSource, traceCaps, type Labels, type TraceKind, type TraceReply, type TraceRequest } from './guide-trace.ts';
import { checkPrompt, findShape, imageKey, promptBox, scalePrompt, shapeReport, shapeSchema, shapeTimings,
  type Found, type Rgba, type ShapeHost } from './shapes/use.ts';
type Pixels = Rgba;
import { massGuideLines, describeMasses, MASS_LINES, type MassPixels } from './guide-masses.ts';

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
  from_reference: Type.Optional(Type.Object({
    reference_id: Type.String({ minLength: 1 }),
    source: Type.Optional(rect('[x,y,w,h] of the reference holding the element (default: the shape\u2019s box, else the whole reference).')),
    target: rect('[x,y,w,h] of the canvas where the element goes, same aspect ratio as source (or the shape\u2019s box). With shape points and no source, the element is fitted into target, centred, its proportions kept.'),
    shape: Type.Optional(shapeSchema('reference')),
    detail: Type.Optional(Type.Union([Type.Literal('simple'), Type.Literal('medium')], { description: 'simple: the outlines and main lines; medium: more inner structure. More lines the larger the target. Default simple.' })),
    lights: Type.Optional(Type.Boolean({ description: 'Also outline the brightest shapes (light sources, lit faces) in the warm light colour.' })),
    masses: Type.Optional(Type.Boolean({ description: 'The block-in masses instead of edges: the big areas of about one colour (sky, each building mass, a head, a car, the moon) as thin boundary lines, light masses warm, and a summary of them. With shape, the masses inside it and the shape\u2019s outline.' })),
  }, { additionalProperties: false, description: 'Outline the element from the reference\u2019s own edges inside source (traced at full resolution), mapped onto target: outlines as contour lines, inner structure as construction lines; only the lines are drawn. With shape, only that one element is outlined (its outline and the structure inside it), nothing else in the box; without it, the big shapes of source are found with the shapes model when it is allowed (the result says how the outlines were found).' })),
  replace: Type.Optional(Type.Boolean({ description: 'Tighten: hide this element\u2019s earlier guide and draw on a new layer (undoing the move shows it again).' })),
});
const finishSchema = object({ element: Type.String({ minLength: 1, maxLength: 60 }) });

type Rect = [number, number, number, number];
type Reference = { id: string; width?: number; height?: number };
type Result = AgentToolResult<unknown>;
export type GuideRuntime = ShapeHost & { study?: { references?: Reference[]; shapes_declined?: boolean };
  decisionObservation?: { width?: unknown; height?: unknown } | null; emit(event: Record<string, unknown>): void;
  /** Big shapes found per reference content and crop (findBigShapes), kept for the chat. */
  guideBigShapes?: Map<string, Promise<Found[]>> };
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
  /** An attached reference's RGBA pixels decoded at most maxSide on the long side (reference-tool.mjs), for its shapes. */
  referencePixels?(id: string, maxSide: number): Promise<Pixels>;
  /** The plugin's trace_edges for an attached reference (reference-tool.mjs traceReferenceEdges): lines in its pixels. */
  traceEdges?(request: TraceRequest): Promise<TraceReply>;
  /** The plugin's smoothed copy of a reference crop (reference-tool.mjs massReferencePixels), for from_reference masses. */
  massPixels?(id: string, source: number[]): Promise<MassPixels>;
};

const TRACE_SIDE = 1440;                     // the shapes model studies a 1024 square: a little more is plenty
const TRACE_PIXELS = 4_000_000;
/** The long side to decode a width x height reference at for its shapes (`source`): about TRACE_SIDE, more when the crop is a
 * small part of a large image (two pixels a working cell), never more than the reference nor four million pixels. */
export function traceSide(width: number, height: number, source: number[]): number {
  const long = Math.max(width, height), crop = Math.max(source[2] ?? 0, source[3] ?? 0, 1);
  const cap = Math.floor(long * Math.sqrt(TRACE_PIXELS / (width * height)));
  return Math.max(1, Math.min(long, cap, Math.max(TRACE_SIDE, Math.ceil(720 * long / crop))));
}

/** What the painter and diagnostics read about a trace: how the outlines were found, and why not by shape. */
export type TraceReport = { silhouette: TraceReply['silhouette']; lines: number; ms: number; shapes?: number; note?: string };
const KEPT_BIG_SHAPES = 4;
const LIGHT_LINES = 8;                       // the plugin's LIGHT_LIMIT: lights come on top of max_lines
const WEIGHTS: Record<TraceKind, GuideWeight> = { outline: 'contour', structure: 'construction', light: 'light' };

/** Whether a plain block-in may use the shapes model: only when nothing need be asked, so never the download question. */
export async function shapesAllowed(runtime: GuideRuntime): Promise<'missing' | 'declined' | 'absent' | 'allowed'> {
  const service = runtime.shapes;
  return !service ? 'missing' : runtime.study?.shapes_declined ? 'declined' : service.ready && !(await service.ready()) ? 'absent' : 'allowed';
}

/** from_reference: the element's outlines, inner structure (and lights) traced by the plugin at full resolution, mapped
 * onto the target. With a shape prompt, that one element's shape gives the outline; without one, the big shapes of the
 * source when the shapes model is allowed, else the plugin's brightness split, which the report says. `room`: how many
 * lines the call can still take. */
export async function tracedLines(runtime: GuideRuntime, from: NonNullable<Static<typeof drawSchema>['from_reference']>,
  dependencies: GuideDependencies, room = GUIDE_LINES, signal?: AbortSignal): Promise<{ lines: Line[]; shape: Found | null; trace: TraceReport }> {
  const reference = runtime.study?.references?.find(item => item.id === from.reference_id);
  if (!reference) throw new Error('Unknown reference ID. Use the attachment list in the study context.');
  const width = reference.width ?? 0, height = reference.height ?? 0;
  const prompt = from.shape ? checkPrompt(from.shape) : null;
  // With a box and no source, the box is what maps onto the target (clamped to the reference, whole pixels).
  const boxed = (box: number[]): Rect => {
    const left = Math.max(0, Math.floor(box[0] ?? 0)), top = Math.max(0, Math.floor(box[1] ?? 0));
    return [left, top, Math.min(width, Math.ceil((box[0] ?? 0) + (box[2] ?? 0))) - left, Math.min(height, Math.ceil((box[1] ?? 0) + (box[3] ?? 0))) - top];
  };
  // The source that maps onto the target: given; a box's own (whole pixels, clamped to the reference); with points and
  // no source, the shape's bounds, fitted into the target (found below); else the whole reference.
  const fitted = !from.source && prompt !== null && 'points' in prompt;
  const source: Rect = (from.source as Rect | undefined) ?? (prompt && 'box' in prompt ? boxed(promptBox(prompt)) : [0, 0, width, height]);
  if (!(source[2] > 0 && source[3] > 0 && source[0] + source[2] <= width && source[1] + source[3] <= height))
    throw new Error('Source crop must fit the reference.');
  let map = fitted ? null : dependencies.mapPoint(source, from.target);
  const canvas = runtime.decisionObservation;
  if (!(Number(canvas?.width) > 0 && Number(canvas?.height) > 0))
    throw new Error('A guide from a reference is placed on the canvas: look at the canvas first (observe), then draw it.');
  if (!dependencies.traceEdges || !dependencies.referencePixels) throw new Error('from_reference needs the reference pixels, which this companion cannot read.');
  const detail = from.detail ?? 'simple', lights = from.lights ?? false;
  if (room < 1 + (lights ? LIGHT_LINES : 0))
    throw new Error(`No room for traced lines in this call (at most ${GUIDE_LINES} lines, with your own lines and perspective): draw from_reference in its own draw_guide call, then add the rest.`);
  const max_lines = Math.max(1, Math.min(traceCaps(from.target, detail), room - (lights ? LIGHT_LINES : 0)));
  // The shapes are found on the whole reference decoded at one size whatever the crop, so one reference is one study.
  const decode = async () => dependencies.referencePixels!(from.reference_id, traceSide(width, height, [0, 0, width, height]));
  let shape: Found | null = null, labels: Labels | undefined, traced: Rect = source, scale = from.target[2] / source[2], note: string | undefined, count: number | undefined;
  if (prompt) {
    const pixels = await decode(), kx = pixels.width / width, ky = pixels.height / height;
    shape = await findShape(runtime, imageKey('reference:' + from.reference_id, pixels), pixels, scalePrompt(prompt, kx, ky, pixels));
    const [bx, by, bw, bh] = shape.bounds, own: Rect = [bx / kx, by / ky, bw / kx, bh / ky];
    if (fitted) {
      const [tx, ty, tw, th] = from.target, fit = Math.min(tw / own[2], th / own[3]);
      map = dependencies.mapPoint(own, [tx + (tw - own[2] * fit) / 2, ty + (th - own[3] * fit) / 2, own[2] * fit, own[3] * fit]);
      scale = fit;
    }
    // Its lines are not cut to the source (the canvas cuts them, as for any guide line): the crop is round the shape.
    traced = shapeSource(own, width, height);
    labels = labelMap([shape], shapeSource(shape.bounds, pixels.width, pixels.height), pixels.width, pixels.height, true);
  } else {
    // A plain block-in uses the shapes model only when nothing need be asked: never the download question from here.
    const allowed = await shapesAllowed(runtime);
    signal?.throwIfAborted();
    if (allowed === 'allowed') {
      try {
        const pixels = await decode(), kx = pixels.width / width, ky = pixels.height / height;
        const left = Math.min(pixels.width - 1, Math.floor(source[0] * kx)), top = Math.min(pixels.height - 1, Math.floor(source[1] * ky));
        const crop: Rect = [left, top, Math.max(1, Math.min(pixels.width, Math.ceil((source[0] + source[2]) * kx)) - left),
          Math.max(1, Math.min(pixels.height, Math.ceil((source[1] + source[3]) * ky)) - top)];
        const key = imageKey('reference:' + from.reference_id, pixels), kept = runtime.guideBigShapes ??= new Map(), id = `${key}:${crop.join(',')}`;
        let found = kept.get(id);
        if (!found) {
          found = findBigShapes(runtime, key, pixels, crop, undefined, signal);
          kept.set(id, found);
          found.catch(() => { if (kept.get(id) === found) kept.delete(id); });
          while (kept.size > KEPT_BIG_SHAPES) kept.delete(kept.keys().next().value as string);
        }
        const shapes = await found;
        count = shapes.length;
        if (shapes.length) labels = labelMap(shapes, crop, pixels.width, pixels.height);
        else note = 'The shapes model found no big shapes here: outlines from brightness.';
      } catch (error) {
        // Stop (the tool's signal, or the shapes model cancelled) stops the guide: it is no reason to fall back.
        if (signal?.aborted || (error as { name?: string }).name === 'AbortError' || (error as { code?: unknown }).code === 'cancelled') throw error;
        note = `The shapes model could not find the shapes (${(error as Error).message}): outlines from brightness.`;
      }
    } else note = allowed === 'declined'
      ? 'Outlines from brightness: the artist has not allowed the shapes model in this chat, so shapes as bright as their ground (a blue tower on a blue sky) may have no outline. The shapes model would sharpen them: the artist can allow it with "Ask again" in the panel.'
      : allowed === 'absent'
        ? 'Outlines from brightness, so shapes as bright as their ground (a blue tower on a blue sky) may have no outline. The shapes model would sharpen them: it is a one-time download the artist is asked for the first time you point at one element (from_reference with shape).'
        : 'Outlines from brightness: the shapes model, which would sharpen them, is not available in this companion.';
  }
  signal?.throwIfAborted();
  // The source and the lines are in the listed pixels: the plugin maps them onto the file, whatever its own size.
  const clamped = Math.min(SCALE_RANGE[1], Math.max(SCALE_RANGE[0], scale));
  const reply = await dependencies.traceEdges({ reference_id: from.reference_id, source: traced, size: [width, height], scale: clamped, detail, max_lines, lights,
    ...(labels ? { labels } : {}) });
  const to = map!;
  const lines = reply.lines.map(({ kind, points }) => ({ weight: WEIGHTS[kind] ?? 'contour', points: points.map(([x, y]) => to(x, y)) }));
  const trace: TraceReport = { silhouette: reply.silhouette, lines: lines.length, ms: reply.ms, ...(count !== undefined ? { shapes: count } : {}), ...(note ? { note } : {}) };
  return { shape, lines, trace };
}
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
export function guideStrokes(runtime: GuideRuntime, args: Static<typeof drawSchema>, mapPoint: GuideDependencies['mapPoint'], traced: Line[] = []): GuideStroke[] {
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
  if (!args.lines?.length && !args.perspective && !traced.length)
    throw new Error('A guide needs lines, perspective or from_reference.');
  if (args.perspective && args.perspective.eye_level_y === undefined && !args.perspective.vanishing_points?.length)
    throw new Error('perspective needs eye_level_y or vanishing_points (canvas pixels).');
  if (args.perspective && !known) throw new Error('Perspective rays cross the whole canvas: look at the canvas first (observe), then draw them.');
  // Construction first, then the traced outlines, then the painter's own lines: later lines draw over earlier ones.
  const lines: Line[] = [
    ...(args.perspective ? perspectiveLines(args.perspective, width, height) : []),
    ...traced,
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
        + 'canvas pixels, or with reference_id pixels of that reference mapped from source onto target (same aspect); '
        + 'from_reference outlines the element from the reference\u2019s own edges (lights: its brightest shapes); with shape '
        + '(one box or a few points per element) only that element. '
        + 'Draw again to add lines; replace: true tightens (the earlier guide is hidden). Read the guided-trace skill '
        + 'first. Paint the element over the guide in your own strokes, then finish_guide.',
      execute: async (id: string, args: Static<typeof drawSchema>, signal?: AbortSignal): Promise<Result> => {
        signal?.throwIfAborted();
        const room = GUIDE_LINES - (args.lines?.length ?? 0) - perspectiveCount(args.perspective), from = args.from_reference;
        // Masses (guide-masses.ts) stand in for the edges. A shape pointed at keeps its outline and inner structure (traced
        // as before, the masses inside it); for the whole picture, the big shapes' outlines win where the shapes model is
        // ready without asking anything (the same rule as a plain block-in), and nothing else is traced.
        const outlines = from && (!from.masses || !!from.shape || await shapesAllowed(runtime) === 'allowed');
        const traceRoom = from?.masses ? Math.max(1, room - MASS_LINES) : room;
        const edges = outlines ? await tracedLines(runtime, from.masses ? { ...from, lights: false } : from, dependencies, traceRoom, signal)
          : { lines: [], shape: null, trace: null };
        const { shape } = edges;
        // Big shapes' outlines only: brightness outlines would draw the masses' boundaries a second time. The report
        // counts the lines drawn.
        const kept = from?.masses && !from.shape ? (edges.trace?.silhouette === 'shapes' ? edges.lines.filter(line => line.weight === 'contour') : []) : edges.lines;
        const trace = edges.trace && kept !== edges.lines ? { ...edges.trace, lines: kept.length } : edges.trace;
        signal?.throwIfAborted();
        const massed = from?.masses ? await massGuideLines(runtime, from, { ...dependencies, shapeSide: traceSide }, shape, room - kept.length) : null;
        const traced = [...kept, ...(massed?.lines ?? [])];
        signal?.throwIfAborted();
        if (args.from_reference && !traced.length && !args.lines?.length && !args.perspective)
          throw new Error(shape ? `No clear outline in that shape (score ${shapeReport(shape).score}): give a tighter box or points on the element, or draw its lines yourself.`
            : 'No clear outline in that part of the reference: choose a source around the element, try detail medium, or draw its lines yourself.'
              + (trace?.note ? ' ' + trace.note : ''));
        const strokes = guideStrokes(runtime, args, dependencies.mapPoint, traced);
        const result = await draw(id, { element: args.element, strokes, ...(args.replace ? { replace: true } : {}) }, signal);
        runtime.emit({ type: 'action', seconds: 0, message: shape
          ? `Drew a guide for ${args.element} from its shape (hidden when the element is finished).`
          : `Drew a guide for ${args.element} (hidden when the element is finished).` });
        // The painter reads the shape's score (and a note when it is uncertain), how the outlines were found and the
        // masses' summary; diagnostics get the timings.
        const masses = massed ? { masses: describeMasses(massed.masses) } : {};
        const massDetails = massed ? { masses: { ms: massed.ms, paths: massed.paths, kept: massed.masses.length, lines: massed.lines.length } } : {};
        if (!shape && !trace && !massed) return result;
        const report = shape ? shapeReport(shape) : null;
        return { ...result, content: [...result.content, { type: 'text', text: JSON.stringify({ ...(report ? { shape: report } : {}), ...(trace ? { trace } : {}), ...masses }) }],
          details: { ...(result.details as object ?? {}), ...(report && shape ? { shape: { ...report, ...shapeTimings(shape) } } : {}), ...(trace ? { trace } : {}), ...massDetails } };
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
