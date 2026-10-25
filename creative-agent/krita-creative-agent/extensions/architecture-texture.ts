// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Architecture texture (openspec architecture-texture, approved by the artist 2026-10-25: "make it an agent skill, don't
// make it optional for architectural structures"; "why not make it an agent pi plugin, not an agent skill"). Painted
// architecture reads smooth at full size; painters add stone grain, cobbles and weathering as subtle photo texture. This
// extension does that as one host-run pass per "Refine: <parts>" step:
// - the tool texture_architecture, its how-to in its description: the planner model (Qwen3 VL by default) chooses each
//   architectural part's materials, tile size near and far, direction, vanishing point and strength (texture-choice.ts);
//   the host clamps them, fetches the library's maps (texture-library.ts) and the plugin bakes them into ONE layer
//   "Texture: <part>" in the move's group (texture_craft.py): detail only, never colour, inside each part's found area;
// - mandatory: after refine_to_goal in an architectural refine step the host runs the pass itself (once a step), and
//   finish_move (request_review in Autopilot) is refused while such a step has no texture pass. The studio refuses Met
//   for such a move too (textureRequired). Sky, water, people, vehicles and trees never get texture.
// The move's Undo (the step's Redo) removes the pass with the rest of the move: it is one of the move's passes.
// A shipped Pi extension registered inline (src/extensions.mjs). It knows the studio only through TextureHost.
import type { ExtensionAPI, ToolCallEvent, ToolCallEventResult, ToolResultEvent, ToolResultEventResult } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { partKind, materialById, type Material, type PartKind } from '../src/texture-library.ts';
import { chooseTextures, clampPart, defaultPart, STRENGTH, type PartChoice, type TexturePart } from '../src/texture-choice.ts';
import type { Picture, StudyReader } from '../src/folder-study.ts';

type Content = { type: string; [key: string]: unknown };
type Result = { content: Content[]; details: any };
export type Area = { mask_path: string; bounds: number[] };
/** A step's part: its element file and the artist's name for it, its folder note, its found area. */
export type StepPart = { name: string; guess?: string; note?: string; area?: Area | null };
/** The refine step being painted: its identity, its label ("church and street"), its parts, its whole area. */
export type TextureStep = { key: string; label: string; parts: StepPart[]; area?: Area | null };
export type TextureRecord = { step: string; parts: PartChoice[]; model?: string; fallback?: string; ms: number; layer_id?: string; auto: boolean };
/** What the studio provides (studio.mjs textureHost). */
export interface TextureHost {
  step(): TextureStep | null;                 // the refine step painted now; null outside one
  done(): boolean;                            // its texture pass ran (in this move; in this step in Autopilot)
  record(entry: TextureRecord): void;         // it ran: what was chosen
  canvas(): { width: number; height: number } | null;
  view(): Promise<{ label: string; picture: Picture } | null>;    // the canvas as the planner reads it
  reader(): Promise<StudyReader | null>;      // the planner model, or null
  /** The material's maps as base64 (downloaded and verified on first use), with its detail_from. */
  maps(material: Material, signal?: AbortSignal): Promise<Record<string, unknown>>;
  native(params: Record<string, unknown>, id: string, signal?: AbortSignal): Promise<Result>;   // the plugin's texture operation
  status?(message: string): void;
}
export type ArchitecturalPart = TexturePart & { area: Area };

/** The step's parts that get texture, each with the area it is confined to (see the header). */
export function architecturalParts(step: TextureStep | null): ArchitecturalPart[] {
  if (!step) return [];
  const named = step.parts.map(part => ({ part, label: String(part.guess || part.name), kind: partKind(String(part.guess || part.name)) }));
  // The step's whole area holds every part: it stands in for a part's own area only when every part is architecture.
  const shared = named.every(n => n.kind) ? step.area ?? null : null;
  return named.flatMap(({ part, label, kind }) => {
    const area = part.area ?? shared;
    return kind && area ? [{ name: label, kind: kind as PartKind, bounds: area.bounds, ...(part.note ? { note: part.note } : {}), area }] : [];
  });
}

/** Whether the step may not be met yet: it has architecture and its texture pass has not run. */
export const textureRequired = (step: TextureStep | null, done: boolean): boolean => !done && architecturalParts(step).length > 0;

const json = (value: unknown) => ({ type: 'text' as const, text: JSON.stringify(value) });
const override = Type.Object({
  part: Type.String({ minLength: 1, maxLength: 120, description: 'The part, as the step names it.' }),
  materials: Type.Optional(Type.Array(Type.Object({ id: Type.String({ maxLength: 60 }), weight: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })) }), { minItems: 1, maxItems: 2 })),
  tile_px: Type.Optional(Type.Object({ near: Type.Number({ minimum: 1, maximum: 10000 }), far: Type.Optional(Type.Number({ minimum: 1, maximum: 10000 })) })),
  direction_deg: Type.Optional(Type.Number({ minimum: -360, maximum: 360 })),
  vanishing: Type.Optional(Type.Union([Type.Null(), Type.Array(Type.Number(), { minItems: 2, maxItems: 2 })])),
  strength: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  blend: Type.Optional(Type.Union([Type.Literal('soft_light'), Type.Literal('overlay')])),
}, { additionalProperties: false });
const DESCRIPTION = 'Subtle photo texture on the architecture of the "Refine: <parts>" step being painted: stone grain, brick courses, '
  + 'cobbles, roof scales and weathering from a CC0 library, as detail only, never colour (the painting keeps its own hues), warped to each '
  + 'part’s perspective, inside its found area with a soft edge, at 10-30%. The planner model chooses each part’s material, tile size '
  + 'near and far, direction and strength from the canvas; the host clamps them and bakes ONE layer "Texture: <part>" in the move. '
  + 'The host runs it by itself after refine_to_goal in such a step, and the step cannot finish until it has run. Call it yourself only '
  + 'when it did not run, or to redo it with parts set by you (parts: per part materials, tile_px {near, far} in canvas px, direction_deg '
  + 'the courses’ angle (0 horizontal, -90 up the canvas), vanishing [x, y] or null, strength 0.1-0.3, blend soft_light or overlay). '
  + 'Buildings, church, towers, domes, skyscrapers, bridge, street, railing, walls, roofs and ledges only: never sky, water, people, vehicles '
  + 'or trees. Call it on its own, not inside paint_batch.';

export default function architectureTexture(host: TextureHost): (pi: ExtensionAPI) => void {
  /** One texture pass over the step's architecture; `parts`: the painter's own choices (clamped). */
  async function run(id: string, auto: boolean, given: any[] | undefined, signal?: AbortSignal): Promise<Result> {
    const step = host.step(), parts = architecturalParts(step), canvas = host.canvas();
    if (!step || !parts.length) throw new Error('This step has no architectural part with a found area: nothing to texture (sky, water, people, vehicles and trees never get texture).');
    if (!canvas) throw new Error('Observe the canvas first.');
    const started = Date.now();
    host.status?.(`Texture: choosing materials for ${step.label}…`);
    let chosen: PartChoice[], model: string | undefined, fallback: string | undefined;
    if (given?.length) {
      const byName = new Map(given.map(g => [String(g.part).trim().toLowerCase(), g]));
      chosen = parts.map(p => { const g = byName.get(p.name.trim().toLowerCase()); return g ? clampPart(g, p, canvas) : defaultPart(p, canvas); });
      fallback = 'painter';
    } else {
      const choice = await chooseTextures({ reader: await host.reader(), view: await host.view().catch(() => null), canvas, parts, signal: signal ?? new AbortController().signal });
      ({ model, fallback } = choice); chosen = choice.parts;
    }
    host.status?.(`Texture: fetching the materials for ${step.label}…`);
    const ids = [...new Set(chosen.flatMap(c => c.materials.map(m => m.id)))];
    const materials: Record<string, unknown> = {};
    for (const materialId of ids) materials[materialId] = await host.maps(materialById(materialId)!, signal);
    host.status?.(`Texture: ${step.label}…`);
    const sent = chosen.map((c, i) => ({ name: c.part, inside_shape: { mask_path: parts[i]!.area.mask_path, bounds: parts[i]!.area.bounds },
      materials: c.materials, tile_px: c.tile_px, direction_deg: c.direction_deg, vanishing: c.vanishing, strength: c.strength, blend: c.blend, seed: i + 1 }));
    const result = await host.native({ name: `Texture: ${step.label}`.slice(0, 120), materials, parts: sent }, id, signal);
    const ms = Date.now() - started;
    host.record({ step: step.key, parts: chosen, ...(model ? { model } : {}), ...(fallback ? { fallback } : {}), ms, layer_id: result.details?.layer_id, auto });
    const report = { texture: { layer: `Texture: ${step.label}`, ms, ...(model ? { model } : {}), ...(fallback ? { fallback } : {}),
      parts: chosen.map(c => ({ part: c.part, kind: c.kind, materials: c.materials.map(m => m.id), tile_px: c.tile_px, direction_deg: c.direction_deg,
        vanishing: c.vanishing, strength: c.strength, blend: c.blend, source: c.source })),
      note: `Detail only, at ${STRENGTH[0] * 100}-${STRENGTH[1] * 100}%: look at the canvas at full size; the move's Undo removes it with the step.` } };
    return { content: [...result.content, json(report)], details: { ...(result.details ?? {}), texture_choice: report.texture } };
  }

  return pi => {
    pi.registerTool({
      name: 'texture_architecture', label: 'Texturing the architecture', executionMode: 'sequential', description: DESCRIPTION,
      parameters: Type.Object({ parts: Type.Optional(Type.Array(override, { minItems: 1, maxItems: 8 })) }, { additionalProperties: false }),
      execute: async (id: string, params: any, signal?: AbortSignal) => run(id, false, params?.parts, signal),
    } as any);

    // Mandatory: the pass follows the refine of an architectural step, run by the host itself.
    pi.on('tool_result', async (event: ToolResultEvent): Promise<ToolResultEventResult | undefined> => {
      if (event.isError || (event as { toolName: string }).toolName !== 'refine_to_goal') return undefined;
      if (!textureRequired(host.step(), host.done())) return undefined;
      try {
        const done = await run(event.toolCallId + '/texture', true, undefined);
        return { content: [...event.content, ...done.content.flatMap(c => c.type === 'text' ? [{ type: 'text' as const, text: String(c.text) }] : []), json({ host_texture: 'The host added the step’s architecture texture (texture_architecture): one layer, detail only.' })] };
      } catch (error) {
        // A texture pass must never fail the refine: the painter is told, and the step stays unfinished until it runs.
        return { content: [...event.content, json({ host_texture: `The architecture texture pass could not run: ${(error as Error)?.message ?? error}. Call texture_architecture before finish_move.` })] };
      }
    });

    // The step cannot be finished without it.
    pi.on('tool_call', async (event: ToolCallEvent): Promise<ToolCallEventResult | undefined> => {
      const name = (event as { toolName: string }).toolName;
      if (name !== 'finish_move' && name !== 'request_review') return undefined;
      if (!textureRequired(host.step(), host.done())) return undefined;
      return { block: true, reason: 'This refine step has architecture and its texture pass has not run: call texture_architecture first (it is mandatory for buildings, church, towers, bridge, street, railing, walls and roofs), then finish.' };
    });
  };
}
