// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The planner looks up the tools (openspec plan-from-request goal 3, approved by the artist 2026-10-24). In its planning
// turn the painter rewrote a fixed draft without seeing what the painting tools do: their descriptions were only offered
// in painting turns. painting_tool_help now answers in plan turns too:
// - without a name, a catalogue: each painting stage with its tool, what it does, what it needs first and a rough time on
//   this canvas, then every other painting tool in one line;
// - with a name, the tool's full description, its parameters and the text of the skills that use it (any skill whose
//   SKILL.md names the tool: nothing is hard-coded per tool).
// The rough times come from measured numbers on the New Moscow copy (6000 x 4500, 27 MP), scaled by the canvas's pixel
// count (the plugin's passes are per pixel or per tile). They are rough on purpose: a time to plan with, not a promise.
// Mechanism only: the studio passes the painter's tool definitions (tools.mjs) and the canvas; this module imports no .mjs.
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

type Tool = { name: string; description: string; parameters?: unknown };
type Canvas = { width: number; height: number } | null | undefined;
export type StageTool = { stage: string; tool: string; does: string; needs: string; measured: { seconds: [number, number]; source: string }; per_part?: string };

/** Every painting_tool_help answer stays under this many characters (review 2026-10-24: a plan turn's lookups were
 * 8-31k characters each, about 75k a turn; the painting phase's native help came back as a truncated stub). */
export const HELP_LIMIT = 6000;
const cut = (text: unknown, n: number) => { const t = String(text ?? '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, Math.max(0, n - 1)).trimEnd() + '\u2026' : t; };
const size = (value: unknown) => JSON.stringify(value).length;
/** The first text length (tried from the largest down) at which `build` fits HELP_LIMIT. */
function fitted<T>(build: (n: number) => T, sizes: readonly number[]): T {
  for (const n of sizes) { const value = build(n); if (size(value) <= HELP_LIMIT) return value; }
  return build(sizes.at(-1) ?? 0);
}

/** The canvas the times were measured on (New Moscow, finish-stage tasks 1.5 and 2). */
export const MEASURED_PIXELS = 6000 * 4500;

export const STAGE_TOOLS: readonly StageTool[] = Object.freeze([
  { stage: 'underpainting', tool: 'paint_from_reference', does: 'Transfers the goal image onto the whole canvas as dabs of paint: the colours and light of every element where the goal has them. The first stage.',
    needs: 'A goal image (the folder’s). Nothing on the canvas first; the Sharpen goal card may come before it for a small goal.',
    measured: { seconds: [270, 600], source: 'live in Toska on the New Moscow copy, 2026-10-24 (builds c8e5851a, 9cf3db8b)' } },
  { stage: 'finish', tool: 'paint_finish', does: 'Blends the soft areas (sky, mist, water) in the underpainting’s own paint and restrokes the forms from the goal image, on the whole picture or inside an area.',
    needs: 'An underpainting on the canvas (it refuses a canvas without one).',
    measured: { seconds: [60, 72], source: 'offline 60 s and live 70-72 s on the New Moscow copy (finish-stage 1.4-1.5)' } },
  { stage: 'refine', tool: 'refine_to_goal', does: 'The host’s loop: ranks the canvas in squares by what is left to do against the goal at full size and refines the worst first (a fine finish, then accents, finer where needed) until close or out of budget. Works inside the Paint only here area when one is set, so a refine step per part refines just that part.',
    needs: 'The whole-picture Finish first. A part’s area (Find it, or the artist’s selection) for a refine step per part.',
    measured: { seconds: [300, 420], source: 'live on the New Moscow copy: 6 min for the whole picture, 161 regions (finish-stage 2.7); budget 15 min' },
    per_part: 'about the whole-picture time times the part’s share of the canvas, plus 2-6 s to find the part (Find it, measured 1.7-5.8 s)' },
  { stage: 'accents', tool: 'paint_accents', does: 'Crisp lights, glints, darks and lines from the goal image, in the underpainting’s own paint, strongest first. The last stage.',
    needs: 'An underpainting (better after the Finish and Refine).',
    measured: { seconds: [15, 60], source: 'live on the New Moscow copy, 15 s and 1 min (finish-stage 1.5, 2.7)' } },
]);

const trim = (n: number) => String(Math.round(n * 10) / 10);
/** A measured range scaled to this canvas: "15-30 s", "1-2 min", "a few seconds"; unscaled without a canvas. */
export function roughTime(measured: { seconds: readonly number[] }, canvas: Canvas): string {
  const k = canvas && canvas.width > 0 && canvas.height > 0 ? canvas.width * canvas.height / MEASURED_PIXELS : 1;
  const [lo = 0, hi = lo] = measured.seconds.map(s => s * k);
  const text = hi < 5 ? 'a few seconds' : hi < 60 ? `${Math.max(1, Math.round(lo))}-${Math.round(hi)} s` : `${trim(lo / 60)}-${trim(hi / 60)} min`;
  return canvas ? text : `${text} (on a 6000 x 4500 canvas)`;
}

const firstSentence = (text: string) => (/^[\s\S]*?[.!?](?=\s|$)/.exec(text)?.[0] ?? text).trim().slice(0, 240);

/** painting_tool_help without a name: the stages this painter has tools for, then the other painting tools. */
export function toolCatalogue({ tools, canvas }: { tools: readonly Tool[]; canvas: Canvas }) {
  const names = new Set(tools.map(t => t.name));
  const stages = STAGE_TOOLS.filter(s => names.has(s.tool)).map(s => ({ stage: s.stage, tool: s.tool, does: s.does, needs: s.needs,
    rough_time: roughTime(s.measured, canvas), ...(s.per_part ? { per_part: s.per_part } : {}) }));
  const staged = new Set(STAGE_TOOLS.map(s => s.tool)), others = tools.filter(t => !staged.has(t.name) && t.name !== 'painting_tool_help');
  return fitted(n => ({
    how: 'A folder plan is made of these stages, in this order. Call painting_tool_help with a name for a tool\u2019s description, parameters and the skills that use it.',
    canvas: canvas ? [canvas.width, canvas.height] : null, stages,
    tools: others.map(t => ({ name: t.name, does: cut(firstSentence(t.description), n) })),
  }), [240, 120, 60, 0]);
}

/** The skills whose SKILL.md names the tool, each with a short excerpt: its lines that name the tool (read the skill for the rest). */
async function skillsUsing(name: string, dir: string, max = 300): Promise<{ name: string; excerpt: string }[]> {
  const out: { name: string; excerpt: string }[] = [];
  let entries: string[] = [];
  try { entries = (await readdir(dir, { withFileTypes: true })).filter(e => e.isDirectory()).map(e => e.name).sort(); } catch { return out; }
  for (const skill of entries) {
    const text = await readFile(join(dir, skill, 'SKILL.md'), 'utf8').catch(() => '');
    const named = new RegExp(`\\b${name}\\b`);
    if (named.test(text)) out.push({ name: skill, excerpt: cut(text.split('\n').filter(line => named.test(line)).join(' '), max) });
  }
  return out;
}

/** painting_tool_help with a name: the tool's full description and parameters, its stage, and the skills that use it. */
export async function toolHelp(name: string, { tools, canvas, skillsDir }: { tools: readonly Tool[]; canvas: Canvas; skillsDir: string }) {
  const tool = tools.find(t => t.name === String(name ?? '').trim());
  if (!tool) return { error: `${name} is not a painting tool here.`, tools: tools.map(t => t.name) };
  const stage = STAGE_TOOLS.find(s => s.tool === tool.name), skills = await skillsUsing(tool.name, skillsDir);
  const properties = (tool.parameters as { properties?: Record<string, { description?: string; type?: string }> } | undefined)?.properties ?? {};
  return fitted(n => ({ name: tool.name, description: cut(tool.description, n * 10),
    parameters: Object.fromEntries(Object.entries(properties).map(([key, p]) => [key, cut(p?.description ?? p?.type ?? '', n)])),
    ...(stage ? { stage: { stage: stage.stage, needs: stage.needs, rough_time: roughTime(stage.measured, canvas), measured: stage.measured.source, ...(stage.per_part ? { per_part: stage.per_part } : {}) } } : {}),
    skills: skills.map(k => ({ name: k.name, excerpt: cut(k.excerpt, Math.max(80, n * 2)) })),
    how: 'Read a skill with read for its whole text.' }), [150, 100, 60, 30, 10]);
}

type Native = { tools?: Record<string, unknown>; capabilities?: Record<string, unknown>; source_modes?: Record<string, unknown> };
/** While painting, painting_tool_help without a name: the native toolbox's commands in one line each (painting_toolbox);
 * a name gives one command in full (toolboxHelp). The plugin's whole help no longer fits a tool result. */
export function toolboxIndex(native: Native) {
  const commands = native.tools ?? {};
  return fitted(n => ({ how: 'Commands for painting_toolbox. Call painting_tool_help with a command\u2019s name for its full parameters, or with a painting tool\u2019s name for that tool.',
    commands: Object.fromEntries(Object.entries(commands).map(([name, text]) => [name, cut(typeof text === 'string' ? text : JSON.stringify(text), n)])),
    source_modes: Object.fromEntries(Object.entries(native.source_modes ?? {}).map(([k, v]) => [k, cut(v, Math.max(40, n * 2))])) }), [80, 50, 30, 0]);
}
/** One native toolbox command in full, or null when the plugin has none by that name. */
export function toolboxHelp(native: Native, name: string) {
  const text = native.tools?.[name];
  if (text === undefined) return null;
  return fitted(n => ({ command: name, parameters: typeof text === 'string' ? cut(text, n) : text, ...(native.capabilities?.[name] ? { capability: native.capabilities[name] } : {}) }), [HELP_LIMIT - 400, 3000, 1000]);
}
