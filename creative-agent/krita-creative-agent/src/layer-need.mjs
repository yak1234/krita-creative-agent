// @ts-check
// Which layer does an area need next? A Luna choice from the canvas (and reference), mapped by
// the host to the craft that makes it. Luna picks the layer's job; the host picks sensible tools
// and blend modes, and the painter may override them. Evaluate records only; Guide advises.
import {QUESTIONS} from './visual-checks.ts';

export const LAYER_NEEDS = Object.keys(QUESTIONS.layer_need.needs);
export const NEED_HINTS = {
  flat:'Lay the area in as a flat: fill_region (clip_base true) in its true value and colour; replace a scribbled mass rather than painting over it.',
  shadow:'Add shadow on a layer clipped to the flat: create_layer or fill_region with clip_to the flat and blend_mode multiply, a colour or gradient, then lower its opacity.',
  light:'Add light on a layer clipped to the flat: blend_mode add for glowing lights and reflections, screen for a soft lift.',
  texture:'Add surface texture clipped to the flat: paint_recipe or paint_pass with clip_to and blend_mode overlay (soft_light for subtle) at layer_opacity 0.3-0.5, or a pattern fill_region with clip_to and blend_mode overlay.',
  glow:'Make the lights glow: set_layer style outer_glow on the light layers, and apply_filter gaussian blur on a copy of a light layer for bloom.',
  depth:'Push the area back: a low-opacity fog fill in the sky colour above it and an apply_filter blur (filter layer on its group), lowering contrast.',
  accents:'Finish with paint_accents on the area: it brightens the lights, deepens the darks and sharpens the thin lines where the canvas is softer than the reference, in its own paint.',
  done:'This area reads as finished; move on to the next one.',
};

/** {need, hint, confidence, probabilities?} for `area`, or {fallback}. */
export async function layerNeedCheck({client, canvas, reference, area, signal}) {
  const {instructions, needs} = QUESTIONS.layer_need;
  const parts = [...(reference ? ['REFERENCE (what the painting aims for):', reference] : []), 'CANVAS (the painting now):', canvas];
  const result = await client.decide({signal, purpose:'choose-next-layer', parts,
    questions:{need:{type:'choice', instructions:instructions.replace('{area}', area), criteria:needs}}});
  if (result.fallback) return {fallback:result.fallback, elapsed_ms:result.elapsed_ms};
  const answer = result.answers?.need;
  if (answer?.type !== 'choice' || !Object.hasOwn(needs, answer.choice)) return {fallback:'service_or_response_error', elapsed_ms:result.elapsed_ms};
  return {need:answer.choice, hint:NEED_HINTS[answer.choice], confidence:answer.confidence ?? null, ...(answer.probabilities ? {probabilities:answer.probabilities} : {}), usage:result.usage, elapsed_ms:result.elapsed_ms};
}

/** The layer job a painting call did, to compare with Luna's choice: the first action that says. */
export function paintedRole(call) {
  const actions = call?.tool === 'paint_batch' ? (call.args?.actions ?? []).map(a => ({tool:a.tool, args:a.arguments ?? {}})) : [{tool:call?.tool, args:call?.args ?? {}}];
  const role = ({tool, args}) => {
    const blend = args.blend_mode;
    if (tool === 'set_layer' && args.style?.outer_glow) return 'glow';
    if (tool === 'apply_filter') return /blur/i.test(args.filter ?? '') ? 'depth' : 'grade';
    if (blend === 'multiply') return 'shadow';
    if (['add','screen','color_dodge','linear_dodge'].includes(blend)) return 'light';
    if (['overlay','soft_light'].includes(blend)) return 'texture';
    if (tool === 'colorize_flats' || ((tool === 'fill_region' || tool === 'create_layer') && (args.clip_base || !args.clip_to))) return 'flat';
    if (['paint_pass','paint_recipe','paint_contours','painting_toolbox'].includes(tool)) return 'strokes';
    return null;
  };
  return actions.map(role).find(Boolean) ?? null;
}
