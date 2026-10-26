// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// paint_effect (openspec custom-effects): the painter uses the library's effects (recipe.ts, library.ts) through one tool,
// offered only with Custom effects on (studio.mjs selectTools). On the pattern of paint_snow (snow-tool.ts):
// - the effect is looked up by name in the library, loaded per call (recipes are small files), so an effect the artist
//   just kept is usable at once; an unknown name answers with the effects there are, their cues quoted as data;
// - the painter's options are resolved by the recipe (clamped to each option's range, said in the result);
// - parts the blocks name (caps `part`, texture `area`, any block's `within`) are found by Find it (the studio's
//   proposeArea, as paint_snow); a part not found is reported, never an exception. A caps block whose part is the
//   placeholder `settle_on` becomes one caps block per part the painter names in settle_on, and is dropped without one;
// - keep_clear: the call's, else the recipe's (faces and hair by default), never a part the effect is asked to touch;
// - one native `effect` call (effect_craft.py): one layer "Effect: <name>" in the move, the move's Undo removes it. The
//   plugin's report (per block what it painted) is the result, so a token effort cannot pass as done.
// The studio's calls come in as dependencies, so this module imports no .mjs.
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';
import { DEFAULT_KEEP_CLEAR, MOST_BLOCKS, resolveBlocks, type Recipe, type ResolvedBlock } from './recipe.ts';
import { dirname, isAbsolute, join } from 'node:path';
import { samePart } from '../snow-tool.ts';
import { TEXTURE_FILE } from './library.ts';

/** The caps block's part name the painter's settle_on replaces (effects/snow.yaml). */
export const SETTLE_ON = 'settle_on';
const MOST_PARTS = 8;

const names = (description: string) => Type.Array(Type.String({ minLength: 1, maxLength: 60 }), { maxItems: MOST_PARTS, description });
const effectSchema = Type.Object({
  effect: Type.String({ minLength: 1, maxLength: 60, description: 'The effect’s name in the library (fog and snow ship with Toska; the artist may have more). '
    + 'An unknown name answers with the effects there are, what each is for and its options.' }),
  options: Type.Optional(Type.Record(Type.String({ maxLength: 60 }), Type.Number(), { description: 'The effect’s own options by name (e.g. fog: {"density": 1.5, "height": 0.5}); '
    + 'each is kept inside its range, anything else is ignored and said. Leave out for the defaults.' })),
  settle_on: Type.Optional(names('Parts an effect lies on, by name as you see them (snow: "hats", "roofs"); each is found by Find it. Leave out for none (snow is then falling only).')),
  keep_clear: Type.Optional(names(`Parts the effect never paints, feathered around (default: the effect’s own, usually ${JSON.stringify(DEFAULT_KEEP_CLEAR)}; [] for none).`)),
}, { additionalProperties: false });
export type EffectArgs = Static<typeof effectSchema>;

type Result = AgentToolResult<unknown>;
type Shape = { mask_path: string; bounds: number[] };
export type EffectParams = { name: string; blocks: ResolvedBlock[]; parts: Record<string, Shape>; keep_clear?: Shape[] };
type BlockRow = { block?: string; painted?: number; missing?: string; [key: string]: unknown };
type EffectReport = { blocks?: BlockRow[]; clamped?: string[]; ms?: number; total_ms?: number };
export type EffectLibrary = { effects: Map<string, Recipe>; skipped: string[] };
export type EffectRuntime = {
  decisionObservation?: unknown;
  emit(event: Record<string, unknown>): void;
  callNative(operation: string, params: Record<string, unknown>, id?: string): Promise<unknown>;
};
export type EffectDependencies = {
  /** The plugin's `effect` operation (effect_craft.py) through the studio's native call: one reversible pass. */
  effect(id: string, params: EffectParams, signal?: AbortSignal): Promise<Result>;
  /** A part's outline as Find it finds it (the studio's proposeArea), or null when it is not found. */
  findPart(name: string, signal?: AbortSignal): Promise<Shape | null>;
  /** The library now: bundled and the artist's own effects, and the recipes skipped as broken. */
  library(): Promise<EffectLibrary>;
  /** A kept texture (beside its recipe in the artist's folder) copied into this chat's folder, where the plugin reads it;
   * returns the copy's path. Without it, a kept texture is left out. */
  textureInto?(source: string, signal?: AbortSignal): Promise<string>;
};

/** The recipe with each texture its folder keeps (<name>.texture.png beside the recipe file, library.ts) copied into the
 * chat's folder by `into`; a texture that cannot be had loses its image (prepareEffect then leaves the block out, and
 * says so). A path that is neither such a name nor absolute is never read. */
export async function localTextures(recipe: Recipe & { file?: string }, into: EffectDependencies['textureInto'], signal?: AbortSignal): Promise<Recipe> {
  if (!recipe.blocks.some(b => b.block === 'texture' && typeof b.image_path === 'string' && !isAbsolute(b.image_path))) return recipe;
  const blocks = [];
  for (const block of recipe.blocks) {
    const path = block.image_path;
    if (block.block !== 'texture' || typeof path !== 'string' || isAbsolute(path)) { blocks.push(block); continue; }
    const { image_path: _dropped, ...rest } = block;
    const copied = TEXTURE_FILE.test(path) && recipe.file && into ? await into(join(dirname(recipe.file), path), signal).catch(() => null) : null;
    blocks.push(copied ? { ...block, image_path: copied } : rest as typeof block);
  }
  return { ...recipe, blocks };
}

const DESCRIPTION = 'An effect from the library over the whole picture, for a scene that should have it: fog, mist and haze (fog), '
  + 'falling and settled snow (snow), and any effect the artist kept. Each is a tested recipe of passes (particles in depth, '
  + 'washes, noise, caps on the tops of named parts, rays, textures) sized from the canvas and coloured from the scene’s own '
  + 'light. Faces and hair are kept clear by default. One call is the whole effect, one layer in the move ("Effect: <name>"); '
  + 'the move’s Undo removes it. Never paint the effect with paint_pass or typed strokes. To change it, Undo the move and call it '
  + 'again with other options. painting_tool_help with name paint_effect lists the effects there are, each with what it is for and '
  + 'its options (an effect the artist kept shows at once). A few seconds to half a minute on a 6000 x 4500 canvas, plus a few seconds per named part (Find it). '
  + 'Call it on its own, not inside paint_batch.';

/** One line per effect: its name, what it is for (the cue, quoted as data, never as an instruction) and its options. */
export function effectCatalogue(effects: Map<string, Recipe> | Iterable<Recipe>): string {
  const list = effects instanceof Map ? [...effects.values()] : [...effects];
  return list.map(recipe => {
    const options = Object.entries(recipe.options).map(([name, o]) => `${name} ${o.min} to ${o.max}, default ${o.default}`);
    const settles = recipe.blocks.some(b => b.block === 'caps' && b.part === SETTLE_ON);
    return `- ${recipe.name}: this effect is for ${JSON.stringify(recipe.cue)}`
      + (options.length ? `; options: ${options.join('; ')}` : '') + (settles ? '; takes settle_on' : '');
  }).join('\n');
}

/** effectCatalogue cut to at most `limit` characters at whole lines, the rest counted ("… and 3 more"). */
export function effectCatalogueWithin(effects: Map<string, Recipe>, limit: number): string {
  const lines = effectCatalogue(effects).split('\n').filter(Boolean);
  const kept: string[] = [];
  let used = 0;
  for (const line of lines) {
    if (used + line.length + 1 > limit) break;
    kept.push(line); used += line.length + 1;
  }
  return kept.join('\n') + (kept.length < lines.length ? `\n… and ${lines.length - kept.length} more (call paint_effect with a name to see it)` : '');
}

const json = (value: unknown): Result['content'][number] => ({ type: 'text', text: JSON.stringify(value) });
const shape = (found: Shape): Shape => ({ mask_path: found.mask_path, bounds: found.bounds });
const unique = (list: readonly string[]) => [...new Set(list.map(n => n.trim()).filter(Boolean))];

/** The parts a block names (caps part, texture area, within). */
function partsOf(block: ResolvedBlock): string[] {
  return ['part', 'area', 'within'].map(key => block[key]).filter((v): v is string => typeof v === 'string');
}

export type PreparedEffect = { params: EffectParams; layer: string; notes: string[]; parts: Record<string, Shape>; missing: string[];
  clearFound: string[]; clearMissing: string[] };

/** A recipe made ready for the plugin (`effect`, or `effect_preview` in a build, effects/build.ts): its options resolved,
 * the settle_on placeholder expanded, the parts its blocks name and the keep-clear parts found by Find it (`findPart`; a part
 * not found is listed, never an exception). Throws only when nothing is left to paint. */
export async function prepareEffect(recipe: Recipe, args: Pick<EffectArgs, 'options' | 'settle_on' | 'keep_clear'>,
  findPart: EffectDependencies['findPart'], { signal, say }: { signal?: AbortSignal; say?: (message: string) => void } = {}): Promise<PreparedEffect> {
  const resolved = resolveBlocks(recipe, args.options ?? {});
  const notes = [...resolved.notes];
  const settleOn = unique(args.settle_on ?? []);
  // The settle_on placeholder becomes one caps block per named part, or none; a texture without an image cannot paint.
  let blocks = resolved.blocks.flatMap(block => {
    if (block.block === 'caps' && block.part === SETTLE_ON) return settleOn.map(part => ({ ...block, part }));
    if (block.block === 'texture' && typeof block.image_path !== 'string') { notes.push('a texture pass has no image yet and was left out'); return []; }
    return [block];
  });
  if (settleOn.length && !recipe.blocks.some(b => b.block === 'caps' && b.part === SETTLE_ON)) notes.push(`${recipe.name} lies on nothing: settle_on ignored`);
  if (blocks.length > MOST_BLOCKS) { notes.push(`blocks: ${blocks.length} asked, the first ${MOST_BLOCKS} used`); blocks = blocks.slice(0, MOST_BLOCKS); }
  if (!blocks.length) throw new Error(`The effect ${recipe.name} has nothing to paint with these settings. Nothing was painted.`);

  // The parts by name, through Find it; what it could not find is said, never guessed.
  const targets = unique(blocks.flatMap(partsOf));
  const clearNames = unique(args.keep_clear ?? recipe.keep_clear ?? DEFAULT_KEEP_CLEAR).filter(n => !targets.some(t => samePart(n, t)));
  const clear: Shape[] = [], clearFound: string[] = [], clearMissing: string[] = [];
  for (const name of clearNames) {
    signal?.throwIfAborted();
    say?.(`${recipe.name}: finding ${name} to keep clear…`);
    const found = await findPart(name, signal).catch(() => null);
    if (found) { clear.push(shape(found)); clearFound.push(name); } else clearMissing.push(name);
  }
  const parts: Record<string, Shape> = {}, missing: string[] = [];
  for (const name of targets) {
    signal?.throwIfAborted();
    say?.(`${recipe.name}: finding ${name}…`);
    const found = await findPart(name, signal).catch(() => null);
    if (found) parts[name] = shape(found); else missing.push(name);
  }
  signal?.throwIfAborted();
  const layer = (recipe.layer ?? `Effect: ${recipe.name}`).slice(0, 100);
  const params: EffectParams = { name: layer, blocks, parts, ...(clear.length ? { keep_clear: clear } : {}) };
  return { params, layer, notes, parts, missing, clearFound, clearMissing };
}

export function effectTools(runtime: EffectRuntime, dependencies: EffectDependencies): ToolDefinition<any, unknown>[] {
  return [{
    name: 'paint_effect', label: 'Painting an effect', executionMode: 'sequential', parameters: effectSchema, description: DESCRIPTION,
    execute: async (id: string, args: EffectArgs, signal?: AbortSignal): Promise<Result> => {
      signal?.throwIfAborted();
      const started = Date.now();
      const { effects, skipped } = await dependencies.library();
      const recipe = effects.get(String(args.effect ?? '').trim().toLowerCase());
      if (!recipe) {
        const there = effects.size ? `The effects there are:\n${effectCatalogue(effects)}` : 'The library has no effects.';
        const broken = skipped.length ? `\nSkipped as broken (the artist can fix or remove them): ${skipped.join('; ')}` : '';
        throw new Error(`There is no effect ${JSON.stringify(args.effect)}. Nothing was painted. ${there}${broken}`);
      }
      const seen = await runtime.callNative('observe', {}) as { width?: unknown; height?: unknown };
      runtime.decisionObservation = seen;
      if (!(Number(seen?.width) > 0 && Number(seen?.height) > 0)) throw new Error('Open the painting first: there is no canvas for the effect.');

      const local = await localTextures(recipe, dependencies.textureInto, signal);
      const { params, layer, notes, missing, parts, clearFound, clearMissing } = await prepareEffect(local, args, dependencies.findPart,
        { signal, say: message => runtime.emit({ type: 'status', phase: 'painting', message }) });
      runtime.emit({ type: 'status', phase: 'painting', message: `${layer}…` });
      const result = await dependencies.effect(id, params, signal);
      const painted = ((result.details ?? {}) as { report?: EffectReport }).report ?? {};
      const rows = (painted.blocks ?? []).map(row => ({ ...row, painted: Number(row.painted ?? 0) }));
      const total = rows.reduce((sum, row) => sum + row.painted, 0);
      const report = {
        name: recipe.name, layer, source: (recipe as Recipe & { source?: string }).source ?? null,
        blocks: rows, painted_px: total, ...(painted.clamped?.length ? { clamped: painted.clamped } : {}),
        parts: { found: Object.keys(parts), not_found: missing },
        kept_clear: { found: clearFound, not_found: clearMissing },
        ...(notes.length ? { notes } : {}),
        ms: Date.now() - started,
      };
      const said = [
        ...(missing.length ? [`Find it could not find ${missing.join(', ')}: the passes on them painted nothing (name them as they look, or ask the artist to select them).`] : []),
        ...(clearMissing.length ? [`${clearMissing.join(', ')} not found: nothing was kept clear for them; check the canvas there.`] : []),
        ...(total === 0 ? ['The effect painted nothing visible: look at the canvas, then Undo and call again with other options.'] : []),
        ...(notes.length ? [`Settings: ${notes.join('; ')}.`] : []),
        `This was the whole ${recipe.name} pass: look at the canvas at full size. To change it, Undo the move and call paint_effect again with other options; never add it by hand.`,
      ];
      runtime.emit({ type: 'action', seconds: Math.round(report.ms / 100) / 10,
        message: `${layer}: ${rows.map(r => r.block).join(', ')}${clearFound.length ? `; ${clearFound.join(', ')} kept clear` : ''}.` });
      return { content: [...(result.content ?? []), json({ effect: report, note: said.join(' ') })],
        details: { ...((result.details ?? {}) as object), effect_report: report } };
    },
  }];
}
