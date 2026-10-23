// One unify pass (after-the-underpainting goal 3). A traced New Moscow chat ran four whole-canvas smudge transfers
// ("Fuse dabs", "Soften every mass", "Big smudge masses"...) and a filter over an excellent underpainting, and each one
// smeared it further. After a whole-picture underpainting a chat gets one whole-canvas softening pass; further
// softening must be scoped to an element or region. This module only recognises such a pass and words the refusal;
// the studio decides when the rule applies and remembers the pass.
//
// Whole-canvas: the call's target covers at least WHOLE_CANVAS_SHARE of the canvas. A pass's region (or how far its
// strokes reach, half a brush past their points), a surface transfer's target, a filter's area. A filter with no area or
// selection works on its whole layer, whose extent is not observed: it counts only on a group or on a layer a
// whole-canvas transfer made (wholeLayers, from the studio), so a bloom blur of a small light layer never does. A named
// selection, an element's shape or an area built from colours, seeds or layers is a scope the painter chose: never counts.
import { SMOOTHING } from './pacing.ts';

export const WHOLE_CANVAS_SHARE = 0.6;
// Krita's Color Smudge blender presets lay no colour of their own (k) Blender Basic and the like).
const BLENDER = /blend|smudg/i;

type Args = Record<string, any>;
export type Call = { tool?: string; args?: Args };
export type Canvas = { width: number; height: number };
export type Rect = [number, number, number, number];
/** A whole-canvas softening action: its tool, a short label for messages, and the share of the canvas it covers. */
export type UnifyAction = { tool: string; what: string; share: number; index: number };
export type Layer = { id?: string; name?: string; type?: string };
export type UnifyCanvas = Canvas & { layers?: Layer[] };
/** wholeLayers: ids (or names) of layers a whole-canvas transfer painted. */
export type UnifyOptions = { wholeLayers?: ReadonlySet<string> };

const actionsOf = (call: Call): { tool?: string; args: Args }[] => call.tool === 'paint_batch'
  ? (call.args?.actions ?? []).map((a: { tool?: string; arguments?: Args }) => ({ tool: a.tool, args: a.arguments ?? {} }))
  : [{ tool: call.tool, args: call.args ?? {} }];
const isRect = (value: unknown): value is Rect => Array.isArray(value) && value.length === 4 && value.every(Number.isFinite);
const finitePoint = (p: unknown): p is [number, number] => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);

function bounds(points: [number, number][]): Rect | null {
  if (!points.length) return null;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]), x = Math.min(...xs), y = Math.min(...ys);
  return [x, y, Math.max(...xs) - x, Math.max(...ys) - y];
}
/** The share of the canvas a rectangle covers, clipped to the canvas. */
function share([x, y, w, h]: Rect, { width, height }: Canvas): number {
  const cw = Math.max(0, Math.min(x + w, width) - Math.max(x, 0)), ch = Math.max(0, Math.min(y + h, height) - Math.max(y, 0));
  return width > 0 && height > 0 ? cw * ch / (width * height) : 0;
}
/** Where a pass's strokes reach: their start and segment points, half a brush size past them. */
function strokeExtent(strokes: unknown): Rect | null {
  if (!Array.isArray(strokes)) return null;
  const points = strokes.flatMap((s: Args) => {
    const r = Number.isFinite(s?.size) ? s.size / 2 : 0;
    const centres = [s?.start, ...(Array.isArray(s?.segments) ? s.segments : []).flatMap((g: number[]) => [[g[0], g[1]], [g[2], g[3]], [g[4], g[5]]])].filter(finitePoint);
    return centres.flatMap(([x, y]): [number, number][] => [[x - r, y - r], [x + r, y + r]]);
  });
  return bounds(points);
}
/** A filter's area as a rectangle, or null when it is not one made of shapes (colours, seeds, layers, inverted...). */
function areaExtent(area: unknown): Rect | null {
  if (!Array.isArray(area) || !area.length) return null;
  const points: [number, number][] = [];
  for (const step of area as Args[]) {
    if (step.invert || ['subtract', 'intersect'].includes(step.mode)) return null;
    if (isRect(step.bounds) && (step.shape === 'rectangle' || step.shape === 'ellipse')) {
      const [x, y, w, h] = step.bounds; points.push([x, y], [x + w, y + h]);
    } else if (step.shape === 'polygon' && Array.isArray(step.points)) points.push(...step.points.filter(finitePoint));
    else return null;
  }
  return bounds(points);
}

/** A filter's whole target: a group (or the image root), or a layer a whole-canvas transfer painted. */
function wholeTarget(target: unknown, canvas: UnifyCanvas, wholeLayers: ReadonlySet<string>): boolean {
  if (typeof target !== 'string') return false;
  if (wholeLayers.has(target) || target === 'root') return true;
  const layer = (canvas.layers ?? []).find(l => l.id === target || l.name === target);
  return !!layer && (layer.type === 'grouplayer' || wholeLayers.has(layer.id ?? '') || wholeLayers.has(layer.name ?? ''));
}

function unifyAction(tool: string | undefined, args: Args, canvas: UnifyCanvas, wholeLayers: ReadonlySet<string>, index: number): UnifyAction | null {
  let rect: Rect | null = null, what = '';
  if (tool === 'paint_reference_surface') { rect = isRect(args.target) ? args.target : null; what = `paint_reference_surface "${args.name}"`; }
  else if ((tool === 'paint_pass' || tool === 'paint_recipe') && (args.smudge_overlay || BLENDER.test(String(args.preset ?? '')))) {
    if (args.selection || args.inside_shape) return null;
    rect = isRect(args.region) ? args.region : strokeExtent(args.strokes); what = `smudge pass "${args.name}"`;
  } else if (tool === 'apply_filter' && SMOOTHING.test(String(args.filter ?? ''))) {
    if (args.selection) return null;
    rect = args.area ? areaExtent(args.area) : wholeTarget(args.target, canvas, wholeLayers) ? [0, 0, canvas.width, canvas.height] : null;
    what = `${args.filter} filter`;
  }
  if (!tool || !rect) return null;
  const covered = share(rect, canvas);
  return covered >= WHOLE_CANVAS_SHARE ? { tool, what, share: Math.round(covered * 100) / 100, index } : null;
}

/** The whole-canvas softening actions of a painting call (a batch's in order; index is the action's place in it). */
export function unifyActions(call: Call, canvas: UnifyCanvas, { wholeLayers = new Set<string>() }: UnifyOptions = {}): UnifyAction[] {
  return actionsOf(call).map(({ tool, args }, index) => unifyAction(tool, args, canvas, wholeLayers, index)).filter((a): a is UnifyAction => a !== null);
}

/** Why `action` is refused: `earlier` was this chat's one unify pass. */
export function unifyRefusal(action: UnifyAction, earlier: { what: string }): string {
  return `One unify pass per chat: ${earlier.what} already softened the whole canvas after the underpainting, and ${action.what} covers `
    + `${Math.round(action.share * 100)}% of the canvas (${Math.round(WHOLE_CANVAS_SHARE * 100)}% or more counts as whole-canvas). Scope further softening to one element or region `
    + '(a region, area or selection around it, such as the hair or the sky), or give it form with your own strokes; another pass over everything smears the underpainting.';
}
