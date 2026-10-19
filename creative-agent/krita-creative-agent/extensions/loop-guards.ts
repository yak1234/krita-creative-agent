// Loop guards: hints added to the painter's tool results, inside Pi's tool loop, so they cannot be skipped the way
// prompt text can and cost nothing in the prompt. A shipped Pi extension, registered inline (src/extensions.mjs)
// with Pi's extension discovery off. It never blocks a call and adds at most one hint per result.
//
// Its state comes only from the events it sees: a successful result with a new canvas revision is a canvas change;
// an observe_canvas with the same revision is one more look. Settings arrive on Pi's event bus ('krita:guards').
import type { ExtensionAPI, ToolResultEvent, ToolResultEventResult } from '@earendil-works/pi-coding-agent';

const LOOKS = 4;
const STREAK = 4;
export const MASS_SHARE = 0.12;
const STROKE_TOOLS = ['paint_pass', 'paint_recipe'];
const MARK_TOOLS = ['paint_contours', 'painting_toolbox'];
// Calls that read or prepare without acting: they neither count as a look nor reset the count.
const READING_TOOLS = ['view_reference', 'sample_canvas_colors', 'list_brushes', 'krita_capabilities', 'painting_tool_help', 'read'];

export type Action = { tool: string; args: Record<string, any> };
type Details = { width?: number; height?: number; revision?: string };

const REFUSALS: [RegExp, string][] = [
  [/coordinate must be between/, 'Stroke points may lie up to one brush size outside the canvas; keep the rest of each stroke on the canvas.'],
  [/no longer in this painting/, 'Use a layer id from the latest observation’s layer_index, or "$N" for a layer made earlier in the same paint_batch.'],
];

/** The actions a painting call made: a batch's actions, or the call itself. */
export function actionsOf(toolName: string, input: Record<string, any>): Action[] {
  return toolName === 'paint_batch'
    ? (input.actions ?? []).map((a: any) => ({ tool: a.tool, args: a.arguments ?? {} }))
    : [{ tool: toolName, args: input }];
}

/** A stroke pass that builds paint on a normal, unclipped layer of its own. */
export function plain({ tool, args }: Action): boolean {
  return STROKE_TOOLS.includes(tool) && !args.clip_to && (!args.blend_mode || args.blend_mode === 'normal') && !args.continue_layer_id;
}

/** The canvas area a stroke pass spans: a recipe's region, or the box around a pass's stroke points. */
export function area({ tool, args }: Action): number {
  if (tool === 'paint_recipe' && Array.isArray(args.region)) return args.region[2] * args.region[3];
  const points: number[][] = (args.strokes ?? []).flatMap((s: any) => [s.start, ...(s.segments ?? []).flatMap((g: number[]) => [[g[0], g[1]], [g[2], g[3]], [g[4], g[5]]])]).filter(Array.isArray);
  if (!points.length) return 0;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  return (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys));
}

export default function loopGuards(pi: ExtensionAPI): void {
  let nativeCraft = true;
  let revision: string | undefined;
  let size: Details = {};
  let looks = 0;
  let streak = 0;

  pi.events.on('krita:guards', data => { nativeCraft = (data as { native_craft?: boolean })?.native_craft !== false; });

  const craftHint = (actions: Action[]): string | null => {
    const strokesOnly = actions.every(a => plain(a) || MARK_TOOLS.includes(a.tool));
    streak = strokesOnly ? streak + 1 : 0;
    const canvas = size.width && size.height ? size.width * size.height : 0;
    const mass = canvas ? actions.filter(plain).map(a => ({ name: a.args.name, share: area(a) / canvas })).find(m => m.share >= MASS_SHARE) : undefined;
    if (mass) return `"${mass.name ?? 'That pass'}" covered about ${Math.round(mass.share * 100)}% of the canvas with plain strokes. Lay a mass in as fill_region (clip_base) and put strokes on top as texture: paint_recipe or paint_pass with clip_to the flat and blend_mode overlay or soft_light at layer_opacity 0.3-0.5. Shadow and light go on clipped multiply and add layers.`;
    if (streak >= STREAK && streak % STREAK === 0) return `The last ${streak} painting calls were plain strokes. Use the layers: fill_region for masses, clipped multiply and add layers for shadow and light, clipped overlay texture, set_layer style outer_glow for lights, apply_filter blur for distance and bloom. Fix shapes with transform_layer, set_layer or a new flat, not by painting over them.`;
    return null;
  };

  const hintFor = (event: ToolResultEvent): string | null => {
    const toolName = (event as { toolName: string }).toolName;
    if (event.isError) {
      const text = event.content.map(c => (c.type === 'text' ? c.text : '')).join(' ');
      return REFUSALS.find(([pattern]) => pattern.test(text))?.[1] ?? null;
    }
    const details = ((event as { details?: unknown }).details ?? {}) as Details;
    if (details.width && details.height) size = { width: details.width, height: details.height };
    const changed = details.revision !== undefined && details.revision !== revision;
    if (details.revision !== undefined) revision = details.revision;
    if (toolName === 'observe_canvas') {
      looks = changed ? 1 : looks + 1;
      return looks >= LOOKS ? `You have looked ${looks} times without changing anything. Select the area with a seed or split_by_color, take colours with sample_canvas_colors, then act.` : null;
    }
    if (READING_TOOLS.includes(toolName)) return null;
    looks = 0;                                       // any other successful call is acting, not looking
    if (!changed) return null;
    return craftHint(actionsOf(toolName, event.input));
  };

  pi.on('tool_result', (event): ToolResultEventResult | undefined => {
    const hint = hintFor(event);
    if (!hint || !nativeCraft) return undefined;
    return { content: [...event.content, { type: 'text', text: JSON.stringify({ craft_hint: hint }) }] };
  });
}
