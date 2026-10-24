// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Typed strokes after the underpainting (the artist, 2026-10-23). In a live New Moscow chat, after an excellent
// whole-picture underpainting, the painter repainted each element by hand: typed paint_batch strokes and stamp_material
// dabs that read as blobs, "hard graphic" and "mechanical stripes", and the goal likeness got worse (ΔE 0.6 → 0.7).
// Once the canvas has a kept whole-picture underpainting, the studio (studio.mjs paced) refuses a call whose
// typed-coordinate marks exceed MAX_MARKS, or any mark wider than MAX_WIDTH_SHARE of the canvas's long side, unless the
// artist's latest message asks for hand-painted work. Refinement goes through paint_accents and Krita's layers and filters.
//
// Why these caps: twelve marks is a handful of corrections (a glint, a post, a window edge) and far below the 4-8 action
// batches of 20-256 strokes that repainted elements; 2% of the long side (120 px on a 6000 px canvas, 20 px on a 1024 px
// one) is a detail brush, while the blobs and stripes were made with brushes several times wider. Mechanism only: the
// studio decides when the cap holds; this module counts and words the refusal, and imports no .mjs.

export const MAX_MARKS = 12;
export const MAX_WIDTH_SHARE = 0.02;
/** stamp_material's default dab count (extensions/material-stamp.ts). */
const STAMP_DEFAULT = 400;
/** Toolbox commands that paint one typed mark each, and those that cover an area from one point. */
const TOOLBOX_MARKS = new Set(['stroke', 'curve_stroke', 'draw_shape', 'fill']);
const TOOLBOX_BROAD = new Set(['flood_fill', 'clear', 'gradient']);

export type StrokeCall = { tool: string; args?: Record<string, unknown> };
/** marks: typed marks the call paints; widest: the widest of them in canvas px; broad: tools that cover areas instead. */
export type Marks = { marks: number; widest: number; broad: string[] };

const num = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const record = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' ? value as Record<string, unknown> : {});

function toolboxMarks(commands: unknown[]): Marks {
  const out: Marks = { marks: 0, widest: 0, broad: [] };
  let brush = 0;
  for (const item of commands) {
    const { tool, parameters_json } = record(item);
    let p: Record<string, unknown> = {};
    try { p = record(JSON.parse(String(parameters_json ?? '{}'))); } catch { /* the plugin refuses it; it still counts */ }
    if (tool === 'set_brush' && num(p.size)) brush = num(p.size);
    if (typeof tool !== 'string') continue;
    if (TOOLBOX_BROAD.has(tool)) { if (!out.broad.includes(tool)) out.broad.push(tool); continue; }
    if (!TOOLBOX_MARKS.has(tool)) continue;
    out.marks++;
    const width = tool === 'fill' ? 2 * num(p.radius)
      : tool === 'draw_shape' && p.fill ? Math.min(Math.abs(num(p.width) || num(p.x2) - num(p.x)), Math.abs(num(p.height) || num(p.y2) - num(p.y)))
      : num(p.size) || brush;
    out.widest = Math.max(out.widest, width);
  }
  return out;
}

/** The typed-coordinate marks one painting call paints, or null for a call that types none (accents, fills, filters,
 * transfers, layer settings). A paint_batch sums its actions. */
export function typedMarks({ tool, args = {} }: StrokeCall): Marks | null {
  switch (tool) {
    case 'paint_pass': {
      const strokes = list(args.strokes);
      return { marks: strokes.length, widest: Math.max(0, ...strokes.map(s => num(record(s).size))), broad: [] };
    }
    case 'painting_toolbox': return toolboxMarks(list(args.commands));
    case 'paint_contours': {
      const shapes = list(args.shapes).map(s => list(record(s).points).map(p => list(p).map(num)));
      const thin = (points: number[][]) => {
        const xs = points.map(p => p[0] ?? 0), ys = points.map(p => p[1] ?? 0);
        return points.length ? Math.min(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) : 0;
      };
      return { marks: shapes.length, widest: Math.max(0, ...shapes.map(thin)), broad: [] };
    }
    case 'stamp_material': return { marks: num(args.count) || STAMP_DEFAULT, widest: Math.max(0, ...list(args.size).map(num)), broad: [] };
    case 'paint_recipe': return { marks: 0, widest: 0, broad: ['paint_recipe'] };
    case 'paint_batch': {
      const parts = list(args.actions).map(a => typedMarks({ tool: String(record(a).tool), args: record(record(a).arguments) })).filter((m): m is Marks => !!m);
      if (!parts.length) return null;
      return parts.reduce((sum, m) => ({ marks: sum.marks + m.marks, widest: Math.max(sum.widest, m.widest),
        broad: [...sum.broad, ...m.broad.filter(b => !sum.broad.includes(b))] }), { marks: 0, widest: 0, broad: [] });
    }
    default: return null;
  }
}

/** The widest typed mark allowed on this canvas, in px. */
export function widthCap({ width, height }: { width: number; height: number }): number {
  return Math.round(Math.max(width, height) * MAX_WIDTH_SHARE);
}

/** Why this call is refused after the underpainting, or null when it is within the cap (or types no marks). */
export function typedStrokeRefusal(call: StrokeCall, canvas: { width: number; height: number }): string | null {
  const m = typedMarks(call);
  if (!m) return null;
  const cap = widthCap(canvas);
  const over = [m.marks > MAX_MARKS ? `${m.marks} marks` : '', m.widest > cap ? `a mark ${Math.round(m.widest)} px wide` : '',
    m.broad.length ? `broad coverage (${m.broad.join(', ')})` : ''].filter(Boolean);
  if (!over.length) return null;
  return `Nothing was painted: the canvas has its whole-picture underpainting, so typed strokes are limited to ${MAX_MARKS} small marks a call, `
    + `each at most ${cap} px wide (2% of the canvas), and this call has ${over.join(' and ')}. Repainting areas by hand pulls the painting away `
    + 'from the goal. Refine with paint_accents instead (lights, glints, darks and lines from the goal image, on the whole picture or an area), '
    + 'or Krita’s layers and filters; for anything more, ask the artist. Typed strokes beyond this are for when the artist asks for hand-painted work.';
}

const HAND = /\b(?:hand[- ]?paint\w*|by hand|free[- ]?hand\w*|(?:your|its|their) own (?:brush ?)?strokes|own brushwork|(?:visible|loose|expressive|painterly) brush ?(?:strokes|work|marks)|brush ?strokes? you can see)\b/i;
const NOT = /\b(?:no|not|don['’]?t|do not|never|without|stop|avoid|less|fewer)\b[^.!?\n]{0,30}$/i;
/** The phrase of the artist's message that asks for hand-painted work, or null (a refusal of it is null). */
export function handPaintingRequested(text: string): string | null {
  const said = String(text ?? ''), found = HAND.exec(said);
  if (!found) return null;
  return NOT.test(said.slice(0, found.index)) ? null : found[0];
}
