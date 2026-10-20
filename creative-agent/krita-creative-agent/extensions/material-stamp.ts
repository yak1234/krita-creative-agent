// Material stamp: the painter cuts a material (soft greyscale tips) from any source, the painting, a layer, a
// reference or an asset, and stamps it into an area as one reversible pass. In the fork (our Krita) the plugin turns the
// tips into real Krita brush tips and presets and paints the dabs with Krita's brush engine (material_stamp.py, krita-fork
// 5.1); stock Krita 5.3.3 (frozen) paints them with one QPainter. This extension decides what is stamped where: it
// registers the two tools and plans the dabs.
// A New Moscow spike stamped 523 cloud dabs in 0.6 s where a reference transfer planned 156,304 strokes.
// A shipped Pi extension registered inline (src/extensions.mjs). It knows the studio only through MaterialHost.
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';

type Content = { type: string; [key: string]: unknown };
type Result = { content: Content[]; details: any };
/** What the studio provides (studio.mjs materialHost). */
export interface MaterialHost {
  native(operation: 'make_material' | 'stamp', params: Record<string, unknown>, id: string, signal?: AbortSignal): Promise<Result>;
  reference(id: string): Promise<string>;               // an attached reference or asset, base64
  image(path: string): Promise<Content>;                // a file in the chat folder, as image content
  canvas(): { width: number; height: number } | null;   // the painting's size, from the last observation
}
export type Dab = { x: number; y: number; scale: number; stretch: number; rotation: number; opacity: number; tip: number };
export type DabPlan = { within: number[]; count: number; size: number[]; opacity: number[]; rotate: number; stretch: number;
  tips: number; tip_size: number; seed: number };
/** The plugin's limit per stamp: 2000 dabs paint in about 0.6 s on a 6000×1350 area. */
export const MAX_DABS = 2000;

/** mulberry32: a small seeded generator, so the same arguments always plan the same dabs. */
function random(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Dabs scattered uniformly over `within` [x,y,w,h]; Krita skips those centred outside the area's selection. */
export function planDabs({ within: [x, y, w, h], count, size, opacity, rotate, stretch, tips, tip_size, seed }: DabPlan): Dab[] {
  const next = random(seed);
  const between = ([low, high]: number[]) => low + (high - low) * next();
  return Array.from({ length: count }, () => ({
    x: x + next() * w, y: y + next() * h, scale: between(size) / tip_size, stretch,
    rotation: (next() * 2 - 1) * rotate, opacity: between(opacity), tip: Math.floor(next() * tips),
  }));
}

// Selection steps exactly as select and fill_region take them; Krita validates each step (region_craft.py).
const selectionSteps = Type.Array(Type.Record(Type.String(), Type.Unknown()), { minItems: 1, maxItems: 16,
  description: 'Selection steps, as in select: shape, layer_id, color, seed [x,y] (magic wand) or saved, combined by mode, then grow/shrink/feather/invert.' });
const range = (low: number, high: number, description: string) =>
  Type.Array(Type.Number({ minimum: low, maximum: high }), { minItems: 2, maxItems: 2, description });

export default function materialStamp(host: MaterialHost): (pi: ExtensionAPI) => void {
  const made = new Map<string, { tips: number; size: number }>();       // this chat's materials, by name
  const key = (name: string) => name.trim().toLowerCase();

  return pi => {
    pi.registerTool({
      name: 'make_material', label: 'Making a material', executionMode: 'sequential',
      description: 'Cut a material (up to 8 soft greyscale brush tips) from the painting’s own texture, to stamp with stamp_material. ' +
        'source: area (selection steps) or selection (a saved name) on the visible painting, layer_id (read only), or reference_id (an attached reference or make_asset image). ' +
        'kind light (default): light over its surroundings, as in clouds, foam, highlights, foliage edges; give an area of just that material (the sky, not the towers). ' +
        'kind shape: the source’s alpha as one tip, for a cut-out asset (a leaf, a snowflake). Never cut from a protected area. Not a canvas change; returns the tips as one image. Call it on its own, not inside paint_batch.',
      parameters: Type.Object({
        name: Type.String({ minLength: 1, maxLength: 40 }),
        source: Type.Object({ area: Type.Optional(selectionSteps), selection: Type.Optional(Type.String({ maxLength: 40 })),
          layer_id: Type.Optional(Type.String()), reference_id: Type.Optional(Type.String()) }, { additionalProperties: false }),
        kind: Type.Optional(Type.Union([Type.Literal('light'), Type.Literal('shape')])),
        count: Type.Optional(Type.Integer({ minimum: 1, maximum: 8 })), size: Type.Optional(Type.Integer({ minimum: 32, maximum: 512 })),
      }, { additionalProperties: false }),
      execute: async (id: string, params: any, signal?: AbortSignal) => {
        const { reference_id, ...source } = params.source ?? {};
        const sent = { ...params, source: reference_id ? { image_base64: await host.reference(reference_id) } : source };
        const result = await host.native('make_material', sent, id, signal);
        const { tips, size, sheet_path } = result.details ?? {};
        if (tips) made.set(key(params.name), { tips, size });
        return sheet_path ? { ...result, content: [...result.content, await host.image(sheet_path)] } : result;
      },
    } as any);

    pi.registerTool({
      name: 'stamp_material', label: 'Stamping a material', executionMode: 'sequential',
      description: 'Stamp a material from make_material into an area: soft volume and texture in one call, in the painting’s own colours ' +
        '(each dab takes the colour under it). area (selection steps) or selection (a saved name) limits it: select the sky, the water, the foliage, never the whole canvas. ' +
        'count dabs (1-2000, default 400) scattered over within [x,y,w,h] (default the canvas), size [min,max] px across, opacity [min,max] (default [0.25,0.5]), ' +
        'rotate (degrees of jitter, default 25), stretch (width over height, default 1.3), seed. tint {color, amount 0-1, toward top|all} moves the colour toward a light, ' +
        'e.g. moonlight on cloud tops. A stamp lays at most 0.6 ink per selected pixel (coverage in the result); a heavier stamp is thinned evenly (opacity_scaled): ' +
        'many large, opaque dabs merge into a pale veil that flattens the forms, so build volume in two or three light stamps and judge each. ' +
        'The dabs are painted by Krita’s brush engine with a brush made from the material’s tips; brush: a base preset from list_brushes (default b) Basic-1) gives size, opacity and blending behaviour. ' +
        'Rotation and stretch are applied by turned and stretched copies of the tip (the result’s brush.variants says if they had to be dropped). One new layer, one reversible pass; protected areas are kept out. Then strokes for crisp edges. Call it on its own, not inside paint_batch.',
      parameters: Type.Object({
        name: Type.String({ minLength: 1, maxLength: 120 }), material: Type.String({ minLength: 1, maxLength: 40 }),
        area: Type.Optional(selectionSteps), selection: Type.Optional(Type.String({ maxLength: 40 })),
        count: Type.Optional(Type.Integer({ minimum: 1, maximum: MAX_DABS })),
        within: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4 })),
        size: Type.Optional(range(4, 4000, 'Dab size range in canvas pixels.')), opacity: Type.Optional(range(0, 1, 'Dab opacity range.')),
        rotate: Type.Optional(Type.Number({ minimum: 0, maximum: 180 })), stretch: Type.Optional(Type.Number({ minimum: 0.2, maximum: 5 })),
        brush: Type.Optional(Type.String({ minLength: 1, maxLength: 200, description: 'Base brush preset (an exact name from list_brushes) the stamp’s brush is made from.' })),
        tint: Type.Optional(Type.Object({ color: Type.String({ pattern: '^#[0-9a-fA-F]{6}$' }), amount: Type.Number({ minimum: 0, maximum: 1 }),
          toward: Type.Optional(Type.Union([Type.Literal('top'), Type.Literal('all')])) }, { additionalProperties: false })),
        seed: Type.Optional(Type.Integer({ minimum: 0, maximum: 2 ** 31 })),
      }, { additionalProperties: false }),
      execute: async (id: string, params: any, signal?: AbortSignal) => {
        const material = made.get(key(params.material));
        if (!material) throw new Error(`No material "${params.material}" in this chat: call make_material first.`);
        if ((params.area ? 1 : 0) + (params.selection ? 1 : 0) !== 1) throw new Error('Give the area to stamp into: area (selection steps) or selection (a saved name).');
        const count = params.count ?? 400;
        if (count > MAX_DABS) throw new Error(`At most ${MAX_DABS} dabs in one stamp.`);
        const canvas = host.canvas();
        const within = params.within ?? (canvas ? [0, 0, canvas.width, canvas.height] : null);
        if (!within) throw new Error('Observe the canvas first, or give within [x,y,w,h].');
        const dabs = planDabs({ within, count, size: params.size ?? [material.size * 0.8, material.size * 2],
          opacity: params.opacity ?? [0.25, 0.5], rotate: params.rotate ?? 25, stretch: params.stretch ?? 1.3,
          tips: material.tips, tip_size: material.size, seed: params.seed ?? 1 });
        const { count: _c, within: _w, size: _s, opacity: _o, rotate: _r, stretch: _t, seed: _e, ...rest } = params;
        return host.native('stamp', { ...rest, dabs }, id, signal);
      },
    } as any);
  };
}
