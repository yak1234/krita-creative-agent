// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// paint_accents (openspec crisp-accents; the artist, 2026-10-23): the last stage after the underpainting (and the finish,
// finish-tool.ts, since 2026-10-24) adjusts the painting's
// OWN paint with Krita's features where the reference is sharper, brighter or darker than the canvas; it adds no marks.
// The painter names an area, which kinds and how many; the plugin compares the reference with the canvas view and keeps
// only what the canvas lacks (find_accents, accent_find.py: the residual decides, and is the strength); this module maps
// them onto the canvas and asks the plugin's `accents` operation (accent_adjust.py) to adjust the paint there, in soft
// masks: lights by Dodge with a Screen bloom, darks by Burn, lost detail (thin lines, edges) by High Pass in Overlay.
// Each call is one reversible pass: one "Accents" group of baked layers made from the canvas's own pixels, inside the
// move's group. The painter types no coordinates.
//
// - Exempt from the 2x stretch limit (the artist, 2026-10-23): nothing of the reference is placed on the canvas.
// - Skipped: in a protected area (by its bounds; Krita keeps the exact pixels anyway), outside the area, dark specks.
// - More than ASK_ABOVE accents in one call: nothing changes until the artist has answered a question the host asks
//   (askAccents); only their yes, for that move and at most that many, lets confirmed: true through, once.
// The studio's native calls come in as dependencies, so this module imports no .mjs.
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';
import { canvasShape, shapeSchema, type CanvasHost } from './shapes/use.ts';
import { decodePlane } from './shapes/png.ts';
import { loadAreaMask } from './paint-only-here.ts';

export const ACCENT_KINDS = ['lights', 'glints', 'darks', 'lines'] as const;
export type AccentKind = typeof ACCENT_KINDS[number];
export const STRENGTHS = ['bold', 'medium', 'subtle'] as const;
/** Past this many accents in one call the painter shows the count and asks the artist first. */
export const ASK_ABOVE = 150;
export const MOST = 400;
export const DEFAULT_COUNT = 40;
/** A dark smaller than this on the canvas (share of its long side, at least MIN_DARK pixels) reads as a speck: dropped unless
 * very strong. */
const SPECK = 0.0015, MIN_DARK = 4, STRONG_SPECK = 0.8;
const ASPECT_TOLERANCE = 0.03;
/** What each finder kind becomes on the canvas: lights and glints are brightened, darks deepened, lines sharpened. */
export const ADJUSTS = { lights: 'lights', glints: 'lights', darks: 'darks', lines: 'detail' } as const;
/** The plugin's caps (accent_adjust.py MAX_SIZE): an accent is at most this large on the canvas. */
export const MAX_ACCENT_SIZE = 96;
/** The plugin's longest accent line (accent_adjust.py: 4 x TILE). */
export const LINE_SPAN = 1024;
export type Adjustment = { kind: 'lights' | 'darks' | 'detail'; x: number; y: number; size: number; strength: number; points?: number[][] };

const rect = (description: string) => Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4, description });
const accentsSchema = Type.Object({
  reference_id: Type.String({ minLength: 1, description: 'The attached reference the accents are found in (the goal image, or an aligned close-up).' }),
  source: Type.Optional(rect('[x,y,w,h] of the reference that lies on target (default: all of it, when it has the canvas’s proportions).')),
  target: Type.Optional(rect('[x,y,w,h] of the canvas where source sits, same aspect ratio (default: the whole canvas).')),
  area: Type.Optional(Type.Union([
    Type.Literal('whole'),
    Type.Object({ box: rect('[x,y,w,h] on the canvas.') }, { additionalProperties: false }),
    Type.Object({ selection: Type.String({ minLength: 1, maxLength: 2000, description: 'A saved selection, or feature names and expressions such as "Sky - Moon".' }) }, { additionalProperties: false }),
    Type.Object({ shape: shapeSchema('canvas') }, { additionalProperties: false }),
  ], { description: 'Where: whole (the default), a box, a named selection, or one element’s shape (only when the shapes model is already allowed).' })),
  kinds: Type.Optional(Type.Array(Type.Union(ACCENT_KINDS.map(kind => Type.Literal(kind))), { minItems: 1, maxItems: 4, uniqueItems: true,
    description: 'lights (bright spots: windows, lamps, stars), glints (sharp highlights: wet road, snow, chrome, water), darks (the darkest small accents: gaps, deep shadows), lines (thin posts, bars, masts, a spire, frames). Default all.' })),
  count: Type.Optional(Type.Integer({ minimum: 1, maximum: MOST, description: `How many, strongest first, shared between the kinds (default ${DEFAULT_COUNT}).` })),
  strength: Type.Optional(Type.Union(STRENGTHS.map(s => Type.Literal(s)), { description: 'bold: only the standouts; medium (default); subtle: quieter ones too.' })),
  confirmed: Type.Optional(Type.Boolean({ description: `The artist agreed to more than ${ASK_ABOVE} accents in one call.` })),
}, { additionalProperties: false });
export type AccentsArgs = Static<typeof accentsSchema>;

type Rect = [number, number, number, number];
type Point = [number, number];
export type Accent = { kind: AccentKind; x: number; y: number; size: number; colour: string; strength: number; shape: 'dot' | 'stroke';
  direction?: number[]; length?: number; glow?: number; points?: number[][]; bright?: boolean; residual?: number };
export type FindRequest = { reference_id: string; source: Rect; size: [number, number]; kinds: AccentKind[]; strength: string; max_accents: number;
  canvas: { image_base64: string; sha256: string; target: Rect } };
export type FindReply = { accents: Accent[]; found: Record<string, number>; ms: number };
type Result = AgentToolResult<unknown>;
type Observation = { width?: unknown; height?: unknown; image_path?: unknown; unguided_path?: unknown; image_width?: unknown; image_height?: unknown;
  protected_areas?: { name: string; bounds: number[] }[]; region?: unknown };
export type AccentsRuntime = CanvasHost & {
  study: { directory: string; references?: { id: string; width?: number; height?: number }[]; shapes_declined?: boolean };
  decisionObservation?: Observation | null;
  emit(event: Record<string, unknown>): void;
  /** The move (or plan step) a confirmation belongs to (studio.mjs). */
  accentsKey?(): string | null;
  /** Ask the artist (an actual question beside the chat; studio.mjs) before adjusting more than ASK_ABOVE accents. */
  askAccents?(question: { question: string; options: string[]; key: string; count: number }): void;
  /** The artist's answer to that question for `key`, used once: {yes, count} or null. */
  takeAccentsAnswer?(key: string): { key: string; count: number; yes: boolean } | null;
  /** The artist's Paint only here area (paint-only-here.ts), the default area while it is set. */
  paintOnlyArea?(): { mask_path: string; bounds: number[] } | null;
};
export type AccentsDependencies = {
  /** The plugin's find_accents for an attached reference (reference-tool.mjs findReferenceAccents). */
  findAccents(request: FindRequest): Promise<FindReply>;
  /** The plugin's `accents` operation (accent_adjust.py) through the studio's native call: one reversible pass. */
  adjust(id: string, params: { name: string; accents: Adjustment[]; selection?: string; inside_shape?: { mask_path: string; bounds: number[] } }, signal?: AbortSignal): Promise<Result>;
};

/** Whether the shapes model may be used without asking anything (never the download question from here). */
export async function shapesAllowed(runtime: CanvasHost & { study?: { shapes_declined?: boolean } }): Promise<boolean> {
  const service = runtime.shapes;
  return !!service && !runtime.study?.shapes_declined && (!service.ready || await service.ready());
}

/** The count shared fairly: each kind asked for gets up to its share (strongest first), the rest goes to the strongest
 * left over; then strongest first. A kind with few accents (lines) is not crowded out by a kind with many (lights). */
export function chooseAccents<T extends { kind: string; strength: number }>(candidates: T[], kinds: readonly string[], count: number): T[] {
  const ranked = [...candidates].sort((a, b) => b.strength - a.strength);
  const share = Math.ceil(count / Math.max(1, kinds.length)), taken = new Set<T>();
  for (const kind of kinds) ranked.filter(a => a.kind === kind).slice(0, share).forEach(a => taken.add(a));
  let chosen = ranked.filter(a => taken.has(a));
  if (chosen.length > count) chosen = chosen.slice(0, count);
  for (const a of ranked) { if (chosen.length >= count) break; if (!taken.has(a)) { chosen.push(a); taken.add(a); } }
  return chosen.sort((a, b) => b.strength - a.strength);
}

const clamp = (v: number, low: number, high: number) => Math.min(high, Math.max(low, v));
const inside = (x: number, y: number, r: number[]) => x >= (r[0] ?? 0) && y >= (r[1] ?? 0) && x < (r[0] ?? 0) + (r[2] ?? 0) && y < (r[1] ?? 0) + (r[3] ?? 0);

/** The whole reference onto the whole canvas, trimmed by the few pixels the proportions differ; null when they differ more. */
export function wholeMapping(width: number, height: number, canvas: { width: number; height: number }): { source: Rect; target: Rect } | null {
  if (Math.abs(width / height / (canvas.width / canvas.height) - 1) > ASPECT_TOLERANCE) return null;
  const source: Rect = width / height > canvas.width / canvas.height
    ? ((w: number): Rect => [Math.floor((width - w) / 2), 0, w, height])(Math.round(height * canvas.width / canvas.height))
    : ((h: number): Rect => [0, Math.floor((height - h) / 2), width, h])(Math.round(width * canvas.height / canvas.width));
  return { source, target: [0, 0, canvas.width, canvas.height] };
}

/** The adjustments for chosen accents on the canvas (`map` from reference to canvas, `scale` canvas pixels a reference
 * pixel): each a soft spot or band where the plugin brightens, deepens or sharpens the canvas's own paint. */
export function accentAdjustments(accents: Accent[], map: (x: number, y: number) => Point, scale: number, canvas?: { width: number; height: number }): Adjustment[] {
  const on = (v: number, high: number | undefined) => high === undefined ? v : clamp(v, 0, high);
  return accents.map(accent => {
    const [x, y] = map(accent.x, accent.y), kind = ADJUSTS[accent.kind];
    const size = clamp(Math.round((accent.kind === 'glints' ? (accent.length ?? accent.size) : accent.size) * scale * 100) / 100, 1, MAX_ACCENT_SIZE);
    const out: Adjustment = { kind, x: Math.round(x * 100) / 100, y: Math.round(y * 100) / 100, size, strength: Math.round(accent.strength * 1000) / 1000 };
    if (accent.kind === 'lines' && accent.points?.length) {
      const points = accent.points.slice(0, 64).map(([px = 0, py = 0]) => {
        const [cx, cy] = map(px, py);
        return [Math.round(on(cx, canvas?.width) * 100) / 100, Math.round(on(cy, canvas?.height) * 100) / 100];
      });
      // The plugin takes a line spanning at most LINE_SPAN pixels: a longer one keeps its first stretch.
      const kept: number[][] = [];
      for (const point of points) {
        const all = [...kept, point], xs = all.map(p => p[0] ?? 0), ys = all.map(p => p[1] ?? 0);
        if (Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) > LINE_SPAN) break;
        kept.push(point);
      }
      if (kept.length >= 2) out.points = kept;
    }
    return out;
  });
}

const json = (value: unknown): Result['content'][number] => ({ type: 'text', text: JSON.stringify(value) });

export function accentTools(runtime: AccentsRuntime, dependencies: AccentsDependencies): ToolDefinition<any, unknown>[] {
  return [{
    name: 'paint_accents', label: 'Painting accents', executionMode: 'sequential', parameters: accentsSchema,
    description: 'Stage three, after the underpainting and paint_finish: make the painting crisp where the reference is sharper, brighter or darker than '
      + 'the canvas, by adjusting the canvas\u2019s own paint with Krita\u2019s filters (no marks): lights and glints brightened '
      + '(Dodge, with a soft Screen bloom), darks deepened (Burn), thin lines and lost edges sharpened (High Pass in Overlay), each in a '
      + 'soft mask. Name the area (whole picture, a box, a selection, or an element\u2019s shape; the artist\u2019s Paint only here area by default while it is set), the kinds and how many; the host '
      + 'compares the reference with the canvas and adjusts only what the canvas lacks, strongest first, as one Accents group (one '
      + 'Undo). Not stretch-limited. Skips protected areas and says how many. '
      + `More than ${ASK_ABOVE} at once: show the artist the count and ask first.`,
    execute: async (id: string, args: AccentsArgs, signal?: AbortSignal): Promise<Result> => {
      signal?.throwIfAborted();
      const started = Date.now();
      const reference = runtime.study.references?.find(item => item.id === args.reference_id);
      if (!reference) throw new Error('Unknown reference ID. Use the attachment list in the study context.');
      const width = reference.width ?? 0, height = reference.height ?? 0;
      if (args.area && typeof args.area === 'object' && 'shape' in args.area && !(await shapesAllowed(runtime)))
        throw new Error('Accents inside an element’s shape need the shapes model, which is not allowed in this chat: give a box or a selection around it instead.');
      // The canvas as it is now: its size, its protected areas, and the view the likeness is measured on.
      const seen = await runtime.callNative('observe', {}) as Observation & { width: number; height: number };
      runtime.decisionObservation = seen;
      const canvas = { width: Number(seen.width), height: Number(seen.height) };
      if (!(canvas.width > 0 && canvas.height > 0)) throw new Error('Open the painting first: there is no canvas to paint accents on.');
      let source = args.source as Rect | undefined, target = args.target as Rect | undefined;
      if (!source || !target) {
        const whole = wholeMapping(width, height, canvas);
        if (!source && !target && whole) ({ source, target } = whole);
        else if (!source && target) source = [0, 0, width, height];
        else if (source && !target) target = [0, 0, canvas.width, canvas.height];
        else throw new Error('This reference has other proportions than the canvas: give source (the reference area) and target (where it sits on the canvas), same aspect ratio.');
      }
      if (!(source[2] > 0 && source[3] > 0 && source[0] + source[2] <= width && source[1] + source[3] <= height)) throw new Error('Source crop must fit the reference.');
      if (Math.abs(source[2] / source[3] / (target[2] / target[3]) - 1) > 0.02) throw new Error('Source and target must have matching aspect ratios; crop instead of stretching.');
      const scale = target[2] / source[2];
      const map = (x: number, y: number): Point => [target![0] + (x - source![0]) * scale, target![1] + (y - source![1]) * scale];
      // The area on the canvas, and the part of the reference under it.
      let bounds: number[] = target, limit: { selection?: string; inside_shape?: { mask_path: string; bounds: number[] } } = {}, mask: { data: Uint8Array; width: number; bounds: number[] } | null = null;
      const area = args.area ?? 'whole', scoped = args.area === undefined ? runtime.paintOnlyArea?.() ?? null : null;
      if (scoped) {
        // Paint only here: the artist's area is the default, its pixels as the plugin's limit (an element shape's file).
        const plane = await loadAreaMask(scoped, runtime.study.directory);
        bounds = plane.bounds; mask = { data: plane.data, width: plane.width, bounds: plane.bounds };
        limit = { inside_shape: { mask_path: scoped.mask_path, bounds: plane.bounds } };
      } else if (typeof area === 'object' && 'box' in area) bounds = area.box;
      else if (typeof area === 'object' && 'selection' in area) {
        const found = await runtime.callNative('select', { name: 'Accents area', steps: [/[+&-]/.test(area.selection) ? { feature: area.selection } : { saved: area.selection }] }).catch(() =>
          runtime.callNative('select', { name: 'Accents area', steps: [{ feature: area.selection }] }));
        bounds = found.bounds; limit = { selection: area.selection };
      } else if (typeof area === 'object' && 'shape' in area) {
        const shape = await canvasShape(runtime, area.shape);
        const plane = decodePlane(await readFile(shape.mask_path));
        bounds = shape.bounds; mask = { data: plane.data, width: plane.width, bounds: shape.bounds };
        limit = { inside_shape: { mask_path: shape.mask_path, bounds: shape.bounds } };
      }
      const left = Math.max(bounds[0]!, target[0]), top = Math.max(bounds[1]!, target[1]);
      const right = Math.min(bounds[0]! + bounds[2]!, target[0] + target[2]), bottom = Math.min(bounds[1]! + bounds[3]!, target[1] + target[3]);
      if (right <= left || bottom <= top) throw new Error('That area lies outside where the reference sits on the canvas.');
      const sx = Math.max(source[0], Math.floor(source[0] + (left - target[0]) / scale)), sy = Math.max(source[1], Math.floor(source[1] + (top - target[1]) / scale));
      const crop: Rect = [sx, sy, Math.min(source[0] + source[2], Math.ceil(source[0] + (right - target[0]) / scale)) - sx,
        Math.min(source[1] + source[3], Math.ceil(source[1] + (bottom - target[1]) / scale)) - sy];
      // The canvas view (the look just taken), which the plugin compares with the reference: where the crop sits in it.
      const path = seen.unguided_path ?? seen.image_path;
      const vw = Number(seen.image_width), vh = Number(seen.image_height);
      if (!(typeof path === 'string' && vw > 0 && vh > 0 && !seen.region))
        throw new Error('Accents go only where the canvas lacks them, so they need a view of the whole canvas, which the plugin did not return: look at the canvas, then try again.');
      const file = await readFile(path), k = vw / canvas.width;
      const [cx, cy] = map(crop[0], crop[1]), [ex, ey] = map(crop[0] + crop[2], crop[1] + crop[3]);
      const tx = clamp(Math.floor(cx * k), 0, vw - 1), ty = clamp(Math.floor(cy * k), 0, vh - 1);
      const view: FindRequest['canvas'] = { image_base64: file.toString('base64'), sha256: createHash('sha256').update(file).digest('hex'),
        target: [tx, ty, Math.max(1, Math.min(vw - tx, Math.round(ex * k) - tx)), Math.max(1, Math.min(vh - ty, Math.round(ey * k) - ty))] };
      const kinds = [...(args.kinds ?? ACCENT_KINDS)] as AccentKind[], count = args.count ?? DEFAULT_COUNT;
      const reply = await dependencies.findAccents({ reference_id: args.reference_id, source: crop, size: [width, height], kinds,
        strength: args.strength ?? 'medium', max_accents: Math.min(1000, 3 * count + 20), canvas: view });
      signal?.throwIfAborted();
      // Skipped: outside the area, where the canvas changed, in a protected area.
      const skipped = { outside: 0, small: 0, protected: 0 };
      const speck = Math.max(MIN_DARK, SPECK * Math.max(canvas.width, canvas.height));
      const protectedAreas = seen.protected_areas ?? [];
      const kept = reply.accents.filter(accent => {
        const [x, y] = map(accent.x, accent.y);
        if (!inside(x, y, bounds) || (mask && !(mask.data[Math.floor(y - mask.bounds[1]!) * mask.width + Math.floor(x - mask.bounds[0]!)]! > 127))) { skipped.outside++; return false; }
        if (accent.kind === 'darks' && accent.size * scale < speck && accent.strength < STRONG_SPECK) { skipped.small++; return false; }
        if (protectedAreas.some(p => inside(x, y, p.bounds))) { skipped.protected++; return false; }
        return true;
      });
      const chosen = chooseAccents(kept, kinds, count);
      const painted: Record<string, number> = {};
      for (const accent of chosen) painted[accent.kind] = (painted[accent.kind] ?? 0) + 1;
      const report = { painted: chosen.length, kinds: painted, skipped, found: reply.found, find_ms: reply.ms };
      if (!chosen.length) return { content: [json({ ...report, message: 'The canvas already has the accents of those kinds that the reference shows there (or every one was skipped): nothing changed.' })], details: report };
      // Many accents at once: the artist decides first. The host asks an actual question; only the artist's yes for this
      // move, for at most that many, lets confirmed through, and only once.
      const key = runtime.accentsKey?.() ?? 'chat';
      if (chosen.length > ASK_ABOVE) {
        if (!args.confirmed) {
          const question = `Make the painting crisper at ${chosen.length} accents at once (lights, darks and fine detail adjusted in its own paint)?`;
          runtime.askAccents?.({ question, options: [`Yes, all ${chosen.length}`, `No, fewer`], key, count: chosen.length });
          const message = `This would adjust ${chosen.length} accents at once (over ${ASK_ABOVE}): I asked the artist. Stop now and wait for their answer; after a yes call again with confirmed: true, or use a smaller count.`;
          return { content: [json({ ...report, painted: 0, would_paint: chosen.length, asked: true, message })], details: { ...report, painted: 0, would_paint: chosen.length, asked: true } };
        }
        const answer = runtime.takeAccentsAnswer?.(key);
        if (!answer || !answer.yes || answer.key !== key || chosen.length > answer.count)
          throw new Error(`More than ${ASK_ABOVE} accents need the artist\u2019s yes to this move\u2019s question, for at most the count they were asked about: call without confirmed to ask, and wait for their answer.`);
      }
      // One reversible pass: the plugin's Accents group of baked layers from the canvas's own pixels, in the move's group.
      signal?.throwIfAborted();
      const result = await dependencies.adjust(id, { name: 'Accents', accents: accentAdjustments(chosen, map, scale, canvas), ...limit }, signal);
      const ms = Date.now() - started;
      runtime.emit({ type: 'action', seconds: Math.round(ms / 100) / 10, message: `Adjusted ${chosen.length} accents (${Object.entries(painted).map(([k, n]) => `${n} ${k}`).join(', ')})`
        + (skipped.protected ? `; skipped ${skipped.protected} in protected areas.` : '.') });
      const details = result.details as { layer_id?: string; adjustments?: unknown } | undefined;
      const done = { ...report, layer_id: details?.layer_id ?? null, adjustments: details?.adjustments ?? null, ms,
        ...(skipped.protected ? { message: `Skipped ${skipped.protected} in protected areas.` } : {}) };
      return { content: [...(result.content ?? []), json(done)], details: { ...(details as object ?? {}), accents: done } };
    },
  }];
}
