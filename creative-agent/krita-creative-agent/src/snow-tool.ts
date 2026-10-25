// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// paint_snow (openspec snow; the artist approved "a real snow method", 2026-10-25). In the live test of that day (the
// Dostoevsky mock execution, 6000 x 4500, impasto oil) the painter, asked for "falling snow over the whole scene, and fresh
// snow settled on the shoulders, hats, the posts and the rooftops", made about 20 dashes of one size and angle (they read
// as rain or scratches), no settled snow on any form and a flake by the main figure's nose, and called it done after 12
// strokes. Snow is a method, not a few typed strokes:
// - falling: the plugin's `snow` operation (snow_craft.py, snow_raster.py) paints thousands of soft flakes in 2-3 depth
//   layers (far small and dim, near few large and blurred), slanted by the wind, in the scene's own light, sizes and
//   counts from the canvas; never on the keep_clear parts (faces by default), feathered around them;
// - settled: a cap of snow on the top edges of each named part (hats, shoulders, posts, roofs), found by Find it (the
//   studio's proposeArea, the same path a plan step's parts take), thick in proportion to the part, with a soft shadow.
// Each is one reversible pass, one layer in the move's group ("Snow: settled on <parts>", "Snow: falling"): the move's
// Undo removes them. The result counts what was painted per depth and per part, so a token effort cannot pass as done.
// The studio's calls come in as dependencies, so this module imports no .mjs.
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';

export const THICKNESS = { thin: 0.6, normal: 1, thick: 1.6 } as const;
export const DEFAULT_WIND = 10;
export const DEFAULT_KEEP_CLEAR = ['faces'];
const MOST_PARTS = 8;

const names = (description: string) => Type.Array(Type.String({ minLength: 1, maxLength: 60 }), { maxItems: MOST_PARTS, description });
const snowSchema = Type.Object({
  mode: Type.Optional(Type.Union([Type.Literal('falling'), Type.Literal('settled'), Type.Literal('both')], { description:
    'falling: snow in the air over the whole picture. settled: fresh snow lying on the tops of settle_on. both: settled, then falling. '
    + 'Default: both when settle_on is given, else falling.' })),
  density: Type.Optional(Type.Number({ minimum: 0.2, maximum: 3, description: 'Falling snow: 1 (default) a steady snowfall, thousands of '
    + 'flakes on a large canvas; 0.5 light flurries; 2 heavy; 3 a blizzard.' })),
  wind_deg: Type.Optional(Type.Number({ minimum: -60, maximum: 60, description: `The flakes' slant from straight down, degrees: 0 still air, positive drifts right, negative left (default ${DEFAULT_WIND}).` })),
  depth_layers: Type.Optional(Type.Union([Type.Literal(2), Type.Literal(3)], { description: '3 (default): far, mid and near flakes; 2: far and near.' })),
  settle_on: Type.Optional(names('Parts the snow lies on, by name as you see them (e.g. "hats", "shoulders", "posts", "rooftops"); each is found by Find it. Settled snow needs at least one.')),
  keep_clear: Type.Optional(names(`Parts that get no snow at all, feathered around (default ${JSON.stringify(DEFAULT_KEEP_CLEAR)}: the faces when people are in the scene; [] for none).`)),
  thickness: Type.Optional(Type.Union([Type.Literal('thin'), Type.Literal('normal'), Type.Literal('thick')], { description: 'Settled snow: how deep it lies (default normal: about a tenth of each part’s width).' })),
}, { additionalProperties: false });
export type SnowArgs = Static<typeof snowSchema>;

type Result = AgentToolResult<unknown>;
type Shape = { mask_path: string; bounds: number[] };
export type SnowParams = { name: string; mode: 'falling' | 'settled'; density?: number; wind_deg?: number; layers?: number;
  settle_on?: { name: string; inside_shape: Shape }[]; keep_clear?: Shape[]; thickness?: number };
type FallingReport = { layers?: Record<string, { flakes?: number }>; light?: number[]; kept_clear?: number; ms?: number };
type SettledReport = { parts?: { name: string; caps?: number; thickness_px?: number }[]; ms?: number };
export type SnowRuntime = {
  decisionObservation?: unknown;
  emit(event: Record<string, unknown>): void;
  callNative(operation: string, params: Record<string, unknown>, id?: string): Promise<unknown>;
};
export type SnowDependencies = {
  /** A part's outline on the painting as Find it finds it (the studio's proposeArea), or null when it is not found or Find
   * it cannot run without asking the artist. */
  findPart(name: string, signal?: AbortSignal): Promise<Shape | null>;
  /** The plugin's `snow` operation (snow_craft.py) through the studio's native call: one reversible pass. */
  snow(id: string, params: SnowParams, signal?: AbortSignal): Promise<Result>;
};

const DESCRIPTION = 'Snow as a painter paints it, for a scene that should have snow: falling snow (thousands of soft flakes in '
  + 'depth layers over the whole picture: far ones small, dense and dim, near ones few, large and blurred, slanted by the wind, '
  + 'in the scene’s own light, so a sunset gets warm-white flakes) and settled snow (fresh caps on the top edges of the parts '
  + 'you name, such as hats, shoulders, posts and rooftops, found by Find it, thick in proportion to each part, with a soft '
  + 'shadow under them). Faces are kept clear by default. Each kind is one layer in the move ("Snow: settled on <parts>", '
  + '"Snow: falling"); the move’s Undo removes them. Never paint snowflakes or snow caps with paint_pass or typed strokes: '
  + 'one call of this tool is the whole snowfall. To change it, Undo the move and call it again with other settings (density, '
  + 'wind, thickness). A few seconds for falling snow on a 6000 x 4500 canvas; a few more per part for settled snow '
  + '(finding it and capping it). Call it on its own, not inside paint_batch.';

const json = (value: unknown): Result['content'][number] => ({ type: 'text', text: JSON.stringify(value) });
const shape = (found: Shape): Shape => ({ mask_path: found.mask_path, bounds: found.bounds });

export function snowTools(runtime: SnowRuntime, dependencies: SnowDependencies): ToolDefinition<any, unknown>[] {
  return [{
    name: 'paint_snow', label: 'Painting snow', executionMode: 'sequential', parameters: snowSchema, description: DESCRIPTION,
    execute: async (id: string, args: SnowArgs, signal?: AbortSignal): Promise<Result> => {
      signal?.throwIfAborted();
      const started = Date.now();
      const settleOn = [...new Set((args.settle_on ?? []).map(n => n.trim()).filter(Boolean))];
      const mode = args.mode ?? (settleOn.length ? 'both' : 'falling');
      if (mode !== 'falling' && !settleOn.length)
        throw new Error('Settled snow needs settle_on: the parts it lies on, by name (e.g. ["hats", "posts", "rooftops"]). Nothing was painted.');
      const seen = await runtime.callNative('observe', {}) as { width?: unknown; height?: unknown };
      runtime.decisionObservation = seen;
      if (!(Number(seen?.width) > 0 && Number(seen?.height) > 0)) throw new Error('Open the painting first: there is no canvas to snow on.');
      // The parts by name, through Find it; what it could not find is said, never guessed.
      const clearNames = [...new Set((args.keep_clear ?? DEFAULT_KEEP_CLEAR).map(n => n.trim()).filter(Boolean))];
      const clear: Shape[] = [], clearFound: string[] = [], clearMissing: string[] = [];
      for (const name of clearNames) {
        signal?.throwIfAborted();
        runtime.emit({ type: 'status', phase: 'painting', message: `Snow: finding ${name} to keep clear…` });
        const found = await dependencies.findPart(name, signal).catch(() => null);
        if (found) { clear.push(shape(found)); clearFound.push(name); } else clearMissing.push(name);
      }
      const parts: { name: string; inside_shape: Shape }[] = [], missing: string[] = [];
      if (mode !== 'falling') for (const name of settleOn) {
        signal?.throwIfAborted();
        runtime.emit({ type: 'status', phase: 'painting', message: `Snow: finding ${name}…` });
        const found = await dependencies.findPart(name, signal).catch(() => null);
        if (found) parts.push({ name, inside_shape: shape(found) }); else missing.push(name);
      }
      if (mode === 'settled' && !parts.length)
        throw new Error(`Find it could not find ${missing.join(', ')} on the painting, so there is nothing for the snow to settle on. Nothing was painted. `
          + 'Name the parts as they look (e.g. "the men’s hats", "wooden posts"), or ask the artist to select them.');
      const keep = clear.length ? { keep_clear: clear } : {};
      const results: Result[] = [];
      let settled: SettledReport | null = null, falling: FallingReport | null = null;
      if (parts.length) {
        signal?.throwIfAborted();
        runtime.emit({ type: 'status', phase: 'painting', message: `Snow: settling on ${parts.map(p => p.name).join(', ')}…` });
        const params: SnowParams = { name: `Snow: settled on ${parts.map(p => p.name).join(', ')}`.slice(0, 120), mode: 'settled', settle_on: parts, ...keep,
          ...(args.thickness && args.thickness !== 'normal' ? { thickness: THICKNESS[args.thickness] } : {}) };
        const result = await dependencies.snow(mode === 'both' ? `${id}/settled` : id, params, signal);
        results.push(result);
        settled = ((result.details ?? {}) as { snow?: SettledReport }).snow ?? {};
      }
      if (mode !== 'settled') {
        signal?.throwIfAborted();
        runtime.emit({ type: 'status', phase: 'painting', message: 'Snow: falling flakes in depth…' });
        const params: SnowParams = { name: 'Snow: falling', mode: 'falling', density: args.density ?? 1, wind_deg: args.wind_deg ?? DEFAULT_WIND,
          layers: args.depth_layers ?? 3, ...keep };
        const result = await dependencies.snow(parts.length ? `${id}/falling` : id, params, signal);
        results.push(result);
        falling = ((result.details ?? {}) as { snow?: FallingReport }).snow ?? {};
      }
      const flakes = falling ? Object.fromEntries(Object.entries(falling.layers ?? {}).map(([k, v]) => [k, Number(v?.flakes ?? 0)])) : null;
      const total = flakes ? Object.values(flakes).reduce((a, b) => a + b, 0) : 0;
      const report = {
        ...(falling ? { falling: { layer: 'Snow: falling', flakes: { ...flakes, total }, depth_layers: Object.keys(flakes ?? {}).length,
          density: args.density ?? 1, wind_deg: args.wind_deg ?? DEFAULT_WIND, light_bgr: falling.light ?? null, flakes_kept_off: falling.kept_clear ?? 0 } } : {}),
        ...(mode !== 'falling' ? { settled: { layer: settled ? `Snow: settled on ${parts.map(p => p.name).join(', ')}` : null,
          parts: (settled?.parts ?? []).map(p => ({ part: p.name, caps: p.caps ?? 0, thickness_px: p.thickness_px ?? 0 })), not_found: missing } } : {}),
        kept_clear: { found: clearFound, not_found: clearMissing },
        ms: Date.now() - started,
      };
      const notes = [
        ...(missing.length ? [`Find it could not find ${missing.join(', ')}: no snow settled there (name them as they look, or ask the artist to select them).`] : []),
        ...(clearMissing.length ? [`${clearMissing.join(', ')} not found: nothing was kept clear for them; check the canvas for flakes there.`] : []),
        'This was the whole snow pass: look at the canvas at full size. To change it, Undo the move and call paint_snow again with other settings; never add flakes or caps by hand.',
      ];
      const said = [falling ? `${total.toLocaleString('en-US')} flakes in ${Object.keys(flakes ?? {}).length} depths (${Object.entries(flakes ?? {}).map(([k, v]) => `${k} ${v.toLocaleString('en-US')}`).join(', ')})` : '',
        settled ? `caps on ${(settled.parts ?? []).map(p => `${p.name} (${p.caps ?? 0})`).join(', ')}` : '',
        clearFound.length ? `${clearFound.join(', ')} kept clear` : ''].filter(Boolean).join('; ');
      runtime.emit({ type: 'action', seconds: Math.round(report.ms / 100) / 10, message: `Snow: ${said}.` });
      const last = results.at(-1);
      return { content: [...results.flatMap(r => (r.content ?? []).filter(c => c.type !== 'text' || r === last)), json({ snow: report, note: notes.join(' ') })],
        details: { ...((last?.details ?? {}) as object), snow_report: report } };
    },
  }];
}
