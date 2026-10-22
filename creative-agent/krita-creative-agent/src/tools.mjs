// @ts-check
import { defineTool } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { Value } from 'typebox/value';
import { createHash } from 'node:crypto';
import { imageContent } from './files.mjs';
import {referenceTools,traceReferencePixels} from './reference-tool.mjs';
import { mapReferencePoint } from './reference-generator.mjs';
import { guideTools } from './guide-tool.ts';
import { canvasShape, checkPassLimits, passShape, shapeReport, shapeSchema, shapeTimings } from './shapes/use.ts';
import { recipeTool } from './recipe-tool.mjs';
import { contourTool } from './contour-tool.mjs';
import { brushCards } from './brush-catalog.mjs';
import { COMIC_OPERATIONS, CRAFT_OPERATIONS } from './craft.mjs';
import { assetTools } from './assets.mjs';
import { skillReadTool } from './skills.mjs';

/** @template {import('typebox').TProperties} T @param {T} properties */
const object = properties => Type.Object(properties, { additionalProperties: false });
const unit = Type.Number({ minimum: 0.01, maximum: 1 });
const coordinate = Type.Number({ minimum: 0, maximum: 8192 });
// Stroke points may lie up to one brush size off the canvas (the plugin checks that), so a stroke runs edge to edge.
const strokeCoordinate = Type.Number({ minimum: -10000, maximum: 18192 });
const hex = Type.String({ pattern: '^#[0-9a-fA-F]{6}$' });
const rect = Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4 });
const point = Type.Array(Type.Number({ minimum: -100000, maximum: 100000 }), { minItems: 2, maxItems: 2 });
const amount = Type.Optional(Type.Integer({ minimum: 1, maximum: 128 }));
// A comic panel id from the observation's comic.panels: new layers go inside that panel, clipped to it.
const panel = Type.Optional(Type.String({ pattern: '^P[0-9]{1,2}$', description: 'Comic panel (P1…): the new layer goes inside that panel and nothing shows outside it. Coordinates stay page pixels.' }));
// One step of a selection: a source, combined with the selection so far, then refined.
const selectionStep = object({
  shape: Type.Optional(Type.Union([Type.Literal('rectangle'), Type.Literal('ellipse'), Type.Literal('polygon')])),
  bounds: Type.Optional(rect), points: Type.Optional(Type.Array(point, { minItems: 3, maxItems: 1000 })),
  layer_id: Type.Optional(Type.String()), color: Type.Optional(hex),
  seed: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 2, maxItems: 2 })), tolerance: Type.Optional(Type.Integer({ minimum: 0, maximum: 255 })),
  saved: Type.Optional(Type.String({ maxLength: 40 })),
  feature: Type.Optional(Type.String({ maxLength: 2000, description: 'Named features of the painting (observations list them), combined with " + ", " & " and " - ", e.g. "Sky - Moon"; needs our Krita.' })),
  mode: Type.Optional(Type.Union([Type.Literal('replace'), Type.Literal('add'), Type.Literal('subtract'), Type.Literal('intersect')])),
  grow: amount, shrink: amount, border: amount, feather: amount, smooth: Type.Optional(Type.Boolean()), invert: Type.Optional(Type.Boolean()),
});
const selectionSteps = Type.Array(selectionStep, { minItems: 1, maxItems: 16, description: 'Steps in order. Each has at most one source: shape (rectangle/ellipse with bounds [x,y,w,h], polygon with points), layer_id (that layer\u2019s alpha, read only), color (+tolerance 0-255, optional bounds) on the visible image, seed [x,y] (a magic wand: the area joined to that pixel whose colour is within tolerance of it, default 24, optional bounds; e.g. the whole sky from one point in it, stopping at every roof and spire, without measuring the outline), saved (a selection name) or feature (feature names and expressions such as \"Sky - Moon\", from the observation\u2019s features; our Krita only). Later sources combine by mode (default add). Then grow, shrink, border, feather (pixels), smooth, invert.' });
const styleBlend = Type.Optional(Type.Union(['normal','multiply','screen','overlay','color_dodge','linear_dodge'].map(m => Type.Literal(m))));
const effect = extra => Type.Union([Type.Null(), object({ color: Type.Optional(hex), opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  size: Type.Optional(Type.Number({ minimum: 0, maximum: 250 })), blend_mode: styleBlend, ...extra })]);
const shadow = { angle: Type.Optional(Type.Number({ minimum: -180, maximum: 180 })), distance: Type.Optional(Type.Number({ minimum: 0, maximum: 1000 })),
  spread: Type.Optional(Type.Number({ minimum: 0, maximum: 100 })) };
// A live Krita layer style; sizes and distances in pixels, angle in degrees (120 = light from the upper left).
const layerStyle = object({ drop_shadow: Type.Optional(effect(shadow)), inner_shadow: Type.Optional(effect(shadow)),
  outer_glow: Type.Optional(effect({ spread: Type.Optional(Type.Number({ minimum: 0, maximum: 100 })) })),
  outline: Type.Optional(effect({ position: Type.Optional(Type.Union([Type.Literal('outside'), Type.Literal('inside'), Type.Literal('center')])) })) });
const stroke = object({
  start: Type.Array(strokeCoordinate, { minItems: 2, maxItems: 2, description: 'Canvas pixels; a point may lie up to one brush size off the canvas, so a stroke can run edge to edge.' }),
  segments: Type.Array(Type.Array(strokeCoordinate, { minItems: 6, maxItems: 6 }), { minItems: 1, maxItems: 1000 }),
  size: Type.Number({ minimum: 1, maximum: 10000 }), opacity: unit, flow: unit,
  color: Type.String({ pattern: '^#[0-9a-fA-F]{6}$' }),
  pressure: Type.Optional(Type.Array(Type.Number({ minimum: 0, maximum: 1 }), { minItems: 2, maxItems: 1001,
    description: 'Pen pressure 0-1 at the start, then at each segment end (one more value than segments); Krita eases it along each curve. Pressure presets taper and thin with it, e.g. [0.2, 1, 0.3] for a stroke that swells and lifts off. Omit for full pressure.' })),
  // The rest of the pen, per point like pressure, in Krita's tablet units; presets whose dynamics read them respond.
  tilt: Type.Optional(Type.Array(Type.Array(Type.Number({ minimum: -60, maximum: 60 }), { minItems: 2, maxItems: 2 }), { minItems: 2, maxItems: 1001,
    description: 'Pen tilt [x, y] in degrees (-60 to 60, 0 upright) per point, like pressure. Tilt presets widen or turn with it. Omit for upright.' })),
  rotation: Type.Optional(Type.Array(Type.Number({ minimum: -180, maximum: 180 }), { minItems: 2, maxItems: 1001,
    description: 'Pen barrel rotation in degrees (-180 to 180) per point. Omit for none.' })),
  speed: Type.Optional(Type.Array(Type.Number({ minimum: 0, maximum: 1 }), { minItems: 2, maxItems: 1001,
    description: 'Pen speed 0-1 (1 = fast) per point. Speed presets thin or soften as it rises. Omit for still.' })),
  time_ms: Type.Optional(Type.Array(Type.Number({ minimum: 0, maximum: 3600000 }), { minItems: 2, maxItems: 1001,
    description: 'Milliseconds since the stroke began, per point, never decreasing. Drives time-based presets and airbrush rate. Omit for 0.' })),
});

// Host bookkeeping the model never needs: files, ids, the whole pass history (the
// panel gets it from `details`). One painting result used to carry ~59k characters.
const LAYER_INDEX_LIMIT = 8000;
const FEATURES_LIMIT = 3000;
const HOST_ONLY = ['passes','image_path','path','checkpoint','painting_path','before_path','after_path','document_id',
  'captured_at','content_id','save_number','checkpoint_deferred','unsaved_operations','source_prior','source_after','prior','after','timings_ms','weight','seam_candidates','save_job','previous_save','background_refused','unguided_path','guides_hidden'];
export function modelResultText(result, {compactLayers=false,focusLayerIds=[],limit=compactLayers?2000:6000}=/** @type {{compactLayers?: boolean, focusLayerIds?: any[], limit?: number}} */ ({})) {
  let model=Object.fromEntries(Object.entries(result ?? {}).filter(([key,value])=>!HOST_ONLY.includes(key) && value!==undefined));
  if (compactLayers && Array.isArray(result?.layers)) {
    const focus=new Set([result.layer_id,...focusLayerIds].filter(Boolean));
    model={...model,layer_count:result.layers.length,layer_index:result.layers.map(({id,name})=>({id,name})),
      affected_layers:result.layers.filter(layer=>focus.has(layer.id)),layers:undefined};
  }
  // The layer index lets the model address any layer, so it has its own, larger budget;
  // past that, the newest layers are kept. Everything else shares `limit`.
  let index=model.layer_index;
  while (index && JSON.stringify(index).length>LAYER_INDEX_LIMIT) { index=index.slice(-Math.floor(index.length*0.75)); model.layer_index_truncated=true; }
  // The artist's features likewise (an observation's name and protected flag per feature): a budget of their own,
  // protected ones first, so many features never crowd out the rest of the result.
  let features=model.features;
  while (Array.isArray(features) && JSON.stringify(features).length>FEATURES_LIMIT) { features=features.slice(0,Math.floor(features.length*0.75)); model.features_truncated=true; }
  const size=value=>JSON.stringify({...value,layer_index:undefined,features:undefined}).length;
  // Over budget: shorten the longest string fields, never emitting invalid JSON.
  for (let cap=1200; size(model)>limit && cap>=60; cap=Math.floor(cap/2))
    model=Object.fromEntries(Object.entries(model).map(([key,value])=>[key,typeof value==='string' && value.length>cap ? value.slice(0,cap)+'…' : value]));
  if (size(model)>limit) model={status:model.status,error:model.error,error_code:model.error_code,layer_id:model.layer_id,layer_count:model.layer_count,result_truncated:'Observe the canvas for details.'};
  return JSON.stringify({...model,...(index?{layer_index:index}:{}),...(features?{features}:{})});
}
export async function resultContent(runtime, result, {compactLayers=false,focusLayerIds=[],limit=undefined}={}) {
  /** @type {any[]} */
  const content = [{ type: 'text', text: modelResultText(result,{compactLayers,focusLayerIds,limit}) }];
  if (result.image_path) {
    const image = await imageContent(runtime.study.directory, result.image_path);
    content.push(image.content);
    runtime.emit({ type: 'canvas', ...result, path: result.image_path, checkpoint: result.checkpoint,
      width: result.width, height: result.height, layers: result.layers, saved_at: result.checkpoint ? Date.now() : undefined });
  }
  return { content, details: result };
}

// Krita's own tools as functions (krita-fork 5.3, our Krita only): the option dicts the fork checks key by key, with its ranges.
// Each paints a NEW layer; selection / area limit the call (neither: the whole canvas), region is the stage's clip. Selection steps
// are as in select, checked by the plugin, so the schema stays short (the tool list is sent every turn).
const looseSteps = Type.Array(Type.Record(Type.String(), Type.Unknown()), { minItems: 1, maxItems: 16, description: 'Selection steps, as in select.' });
const toolLimit = { selection: Type.Optional(Type.String({ maxLength: 2000, description: 'A saved selection, or (our Krita) feature names and expressions such as "Sky - Moon", that limit the call.' })), area: Type.Optional(looseSteps),
  region: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 8192 }), { minItems: 4, maxItems: 4, description: 'Stage region [x,y,w,h] to stay inside.' })) };
const toolLayer = { blend_mode: Type.Optional(Type.String({ maxLength: 40 })), opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  clip_to: Type.Optional(Type.String()), clip_base: Type.Optional(Type.Boolean()) };
const whole = (low, high) => Type.Optional(Type.Integer({ minimum: low, maximum: high }));
const flag = () => Type.Optional(Type.Boolean());
const word = list => Type.Optional(Type.Union(list.map(w => Type.Literal(w))));
const fillShared = { sample: word(['layer', 'all', 'labels']), labels: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 8 }), { minItems: 1, maxItems: 9 })),
  threshold: whole(1, 100), spread: whole(0, 100), closeGap: whole(0, 32), grow: whole(-400, 400), feather: whole(0, 400),
  antialias: flag(), stopGrowingAtDarkestPixel: flag(), useSelectionAsBoundary: flag(),
  opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })), compositeOp: Type.Optional(Type.String({ maxLength: 40 })) };

/** How a painting tool runs one native operation: revision and recovery handling, the canvas image in the result.
 * Shared with the shipped extensions' tools (studio.mjs materialHost). */
export function nativeExecute(runtime, operation) {
  return async (id, params, signal) => {
      signal?.throwIfAborted();
      if (runtime.faulted && !['observe','sample_colors'].includes(operation)) throw new Error('The last operation needs reconciliation. Observe, then end this study before making a new working copy.');
      try {
        const result = await runtime.callNative(operation, params, id);
        // The capability manifest is the answer itself, not bookkeeping: it gets its own budget.
        const response = await resultContent(runtime, result, {compactLayers:operation!=='observe',
          focusLayerIds:[params.layer_id,params.source_layer_id], limit:operation==='capabilities' ? (params.full ? 40000 : 6000) : undefined});
        if (result.image_path) runtime.decisionObservation = result;
        return response;
      } catch (error) {
        // Recovered in an active Agent run: the painter gets the fresh canvas and continues.
        if (error.recovered) {
          runtime.decisionObservation = error.recovered;
          return await resultContent(runtime, error.recovered, {compactLayers:true});
        }
        if (error.code === 'outcome_unknown' || error.code === 'partial_change' || error.code === 'checkpoint_failed') {
          runtime.faulted = true;
          runtime.emit({ type: 'status', message: 'Painting paused. Inspect the last saved checkpoint.' });
          if (error.result?.image_path) await resultContent(runtime, error.result);
        }
        throw error;
      }
  };
}

export function paintingTools(runtime) {
  const tool = (name, label, description, parameters, operation) => ({
    name, label, description, parameters, executionMode: /** @type {const} */ ('sequential'), execute: nativeExecute(runtime, operation),
  });
  /** @type {import('@earendil-works/pi-coding-agent').ToolDefinition<any, any>[]} */
  const tools = [
    tool('observe_canvas', 'Looking at the painting',
      'See the current canvas image, document dimensions and layer IDs. Canvas coordinates use width/height, not the resized preview. Inspect before deciding on a change. Optional region [x,y,width,height] returns actual-resolution material detail up to 1568 px on its long side; a larger region comes back shrunk, and scale in the result says by how much (1 = actual pixels).', object({region:Type.Optional(Type.Array(Type.Integer({minimum:0,maximum:8192}),{minItems:4,maxItems:4}))}), 'observe'),
    tool('sample_canvas_colors','Sampling canvas colors',
      'Sample the exact visible canvas colors at up to 16 document-pixel points. Use destination colors for texture and corrections; sampling does not paint. Returns colors, alpha and the sampled revision.',
      object({points:Type.Array(Type.Array(Type.Integer({minimum:0,maximum:8191}),{minItems:2,maxItems:2}),{minItems:1,maxItems:16})}),'sample_colors'),
    {...tool('list_brushes', 'Choosing a brush',
      'Find installed brush presets, each with a card saying what one stroke of it actually paints (null if never probed). Use an exact returned name for painting. A filter matches names only.',
      object({ filter: Type.Optional(Type.String({ maxLength: 80 })) }), 'list_brushes'),
     // The whole library with its cards: an 80-name cap and a 2,000-character result hid two thirds of it.
     execute: async (id, params, signal) => {
       signal?.throwIfAborted();
       const result = await runtime.callNative('list_brushes', params, id);
       return resultContent(runtime, { ...result, brushes: brushCards(result.brushes ?? []) }, { limit: 24000 });
     }},
    tool('paint_pass', 'Painting a pass',
      'Paint up to 256 continuous native cubic brush curves on a NEW named layer. Each segment is [c1x,c1y,c2x,c2y,endx,endy]. The full pass is validated before painting. Automatically updates the study’s single layered painting.kra file and returns its canvas IMAGE. Assess that image before the next pass. Brush width matters for coverage and overlap. A stroke’s optional pressure, tilt, rotation, speed and time_ms lists drive the preset’s pen dynamics; the result says "applied" for each, or "ignored" when this Krita cannot paint it.',
      object({ name: Type.String({ minLength: 1, maxLength: 120 }), preset: Type.String({ minLength: 1 }),
        strokes: Type.Array(stroke, { minItems: 1, maxItems: 256 }),
        region:Type.Optional(Type.Array(Type.Integer({minimum:0,maximum:8192}),{minItems:4,maxItems:4})),
        selection: Type.Optional(Type.String({ maxLength: 2000, description: 'Limit the pass to a saved selection or (our Krita) feature names and expressions such as "Sky - Moon" instead of a region; protected features are kept out either way.' })),
        layer_opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })), panel,
        blend_mode: Type.Optional(Type.String({ maxLength: 40, description: 'Paint on a new layer in this blend mode: overlay or soft_light for texture, multiply for shadow, add or screen for light.' })),
        clip_to: Type.Optional(Type.String({ description: 'Clip the new stroke layer to this layer (usually the area\u2019s flat), so no mark leaves its shape.' })),
        inside_shape: Type.Optional(shapeSchema('canvas', 'Paint only inside one element of the painting (\u201cinside the moon\u201d): one box around it or a few points on it, canvas pixels. Its shape is found on the canvas you last saw; not with region or selection.')) }), 'paint_pass'),
    tool('painting_toolbox', 'Working with painting tools',
      'Execute native painting commands as one reversible contribution. Omit source_layer_id to create a layer; supply an observed layer ID to edit a copy of existing paint; or supply projection_region [x,y,width,height] to retouch a masked copy of the visible composite on a new top layer. projection_feather softens its boundary. These source modes are exclusive. Commands run in order on that layer. Call painting_tool_help first. Returns the actual resulting image. Projection retouch supports selection-aware brush, eraser, gradient and Smart Patch work; filled shapes and whole-layer transforms are excluded there.',
      object({name:Type.String({minLength:1,maxLength:120}),source_layer_id:Type.Optional(Type.String()),
        projection_region:Type.Optional(Type.Array(Type.Integer({minimum:0,maximum:100000}),{minItems:4,maxItems:4})),
        projection_feather:Type.Optional(Type.Integer({minimum:0,maximum:64})),
        commands:Type.Array(object({tool:Type.String(),parameters_json:Type.String({description:'JSON object containing parameters documented by painting_tool_help'})}),{minItems:1,maxItems:256})}), 'painting_toolbox'),
    tool('painting_tool_help', 'Inspecting painting tools',
      'Discover the native painting toolbox and exact parameter formats. Includes brush settings inspection. Read this before painting_toolbox.',
      object({}), 'painting_tool_help'),
    tool('create_layer', 'Creating a layer',
      'Create a layer with its craft settings in one call: paint, fill or group. A fill uses a generator from krita_capabilities: color with generator_config {color:\u0027#RRGGBB\u0027}, pattern with {pattern: name}, gradient with {shape: linear|radial|square|conical|spiral, start_position_x/y and end_position_x/y (percent of the canvas), start_color, end_color, repeat: none|forwards|alternate} (a live, re-editable gradient layer); region [x,y,w,h] limits it. Set blend_mode (multiply for shadow, screen/add for light), opacity, alpha_lock (paint only). clip_base: true puts the layer alone in a clip group so later layers can clip to it live (use for flats). clip_to: a layer ID to clip this layer to: live above a clip base, otherwise a mask of that layer\u2019s current alpha (the artist\u2019s layers are never moved). One reversible pass; returns the canvas image.',
      object({ name: Type.String({ minLength: 1, maxLength: 120 }), type: Type.Union([Type.Literal('paint'), Type.Literal('fill'), Type.Literal('group')]),
        blend_mode: Type.Optional(Type.String({ maxLength: 40, description: 'Krita blend mode id, e.g. normal, multiply, screen, overlay, add, color, soft_light. krita_capabilities lists them.' })), opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
        visible: Type.Optional(Type.Boolean()), alpha_lock: Type.Optional(Type.Boolean()),
        clip_base: Type.Optional(Type.Boolean()), clip_to: Type.Optional(Type.String()),
        generator: Type.Optional(Type.String({ maxLength: 40 })),
        generator_config: Type.Optional(Type.Record(Type.String(), Type.Union([Type.String(), Type.Number(), Type.Boolean()]))),
        region: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4 })), panel }), 'create_layer'),
    tool('set_layer', 'Setting a layer',
      'Change a layer\u2019s settings: opacity and visible on any unlocked layer; blend_mode, alpha_lock (paint layers), clip (live clip above a clip base), name and style on layers the agent created. style is a live layer style that follows the layer\u2019s pixels, without strokes: drop_shadow, inner_shadow, outer_glow (halo for lights) and outline; it replaces the layer\u2019s style, so include every effect you want, and null turns one off. Rejecting the pass restores every previous setting. Returns the canvas image.',
      object({ layer_id: Type.String(), name: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })), blend_mode: Type.Optional(Type.String({ maxLength: 40, description: 'Krita blend mode id, e.g. normal, multiply, screen, overlay, add, color, soft_light. krita_capabilities lists them.' })),
        opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })), visible: Type.Optional(Type.Boolean()),
        alpha_lock: Type.Optional(Type.Boolean()), clip: Type.Optional(Type.Boolean()), style: Type.Optional(layerStyle) }), 'set_layer'),
    tool('select', 'Selecting a region',
      'Build a selection from steps and save it under a name for fill_region and later turns. Example: the figure\u2019s alpha, grown 4 px and feathered 2. The artist\u2019s selection is never changed; not a canvas change. Returns bounds and selected_pixels, and open_edges: straight lines where it cuts through open paint; extend or feather it before painting through it, or the line prints as a hard edge.',
      object({ name: Type.String({ minLength: 1, maxLength: 40 }), steps: selectionSteps }), 'select'),
    tool('propose_protection', 'Marking an area to protect',
      'Mark an area of the painting the artist asked to protect ("protect the woman and the car"), from selection steps like select: polygons around what you see, a layer\u2019s alpha, a colour range, a seed (magic wand); or shape: one finished element\u2019s exact shape from one box around it or a few points on it. It is shown in red and your passes keep out of it at once; the artist keeps or discards it. Propose before you paint near it. You cannot remove or change protection. Not a canvas change.',
      object({ name: Type.String({ minLength: 1, maxLength: 60 }), area: Type.Optional(selectionSteps), shape: Type.Optional(shapeSchema('canvas')) }), 'propose_protection'),
    tool('fill_region', 'Filling a region',
      'Fill an area in one call, without strokes: flats, sky, a shadow shape, a gradient. Area: selection (a saved name) or area (selection steps). Paint: color, gradient {type linear|radial, start, end, stops [{offset 0-1, color}]} or pattern (a krita_capabilities name). Fills a NEW layer named name (with blend_mode, opacity, clip_base, clip_to as in create_layer), or layer_id: an agent paint layer, honouring its alpha lock (fill_region onto a clip_base layer extends the flats and keeps its clipped layers). One reversible pass; returns the canvas image.',
      object({ name: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })), layer_id: Type.Optional(Type.String()),
        selection: Type.Optional(Type.String({ maxLength: 2000, description: 'A saved selection name, or (our Krita) feature names and expressions such as "Sky - Moon".' })), area: Type.Optional(selectionSteps),
        color: Type.Optional(hex), pattern: Type.Optional(Type.String({ maxLength: 200 })),
        gradient: Type.Optional(object({ type: Type.Optional(Type.Union([Type.Literal('linear'), Type.Literal('radial')])), start: point, end: point,
          stops: Type.Array(object({ offset: Type.Number({ minimum: 0, maximum: 1 }), color: hex }), { minItems: 2, maxItems: 16 }) })),
        blend_mode: Type.Optional(Type.String({ maxLength: 40 })), opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
        clip_base: Type.Optional(Type.Boolean()), clip_to: Type.Optional(Type.String()), panel }), 'fill_region'),
    tool('bucket_fill', 'Bucket fill',
      'Krita\u2019s fill tool: flood one region from the point x, y with a colour, onto a NEW layer. options.mode contiguous (default), similar (every pixel of a similar colour) or selection; sample all (default: regions found on the painting as shown), layer or labels; threshold 1-100 (default 8), closeGap 0-32 (bridges gaps in line art), grow, feather. selection or area limits it. For one region from a point; fill_region fills a whole named selection. One reversible pass; returns the canvas image and tool_call (what Krita did).',
      object({ name: Type.String({ minLength: 1, maxLength: 120 }), x: Type.Integer({ minimum: 0, maximum: 100000 }), y: Type.Integer({ minimum: 0, maximum: 100000 }), color: hex,
        options: Type.Optional(object({ ...fillShared, mode: word(['contiguous', 'similar', 'selection']), boundaryColor: Type.Optional(hex) })),
        ...toolLimit, ...toolLayer }), 'bucket_fill'),
    tool('enclose_and_fill', 'Enclose and fill',
      'Krita\u2019s enclose-and-fill tool: flood the regions inside a drawn area onto a NEW layer, where bucket_fill does one. enclose_area (selection steps, e.g. a polygon round a facade) or enclose_selection (a saved name); color. options.regions: all (default), transparent, color (with regionColor), allExcept\u2026 or surroundedBy\u2026 forms; includeContourRegions (regions touching the area\u2019s edge, default off); invert; and the fill options (sample all by default). selection or area limits it. One reversible pass; returns the canvas image and tool_call.',
      object({ name: Type.String({ minLength: 1, maxLength: 120 }), enclose_area: Type.Optional(looseSteps), enclose_selection: Type.Optional(Type.String({ maxLength: 2000 })), color: hex,
        options: Type.Optional(object({ ...fillShared, regionColor: Type.Optional(hex), invert: flag(), includeContourRegions: flag(), includeSurroundingRegions: flag(),
          regions: word(['all', 'color', 'transparent', 'colorOrTransparent', 'allExceptColor', 'allExceptTransparent', 'allExceptColorOrTransparent',
            'surroundedByColor', 'surroundedByTransparent', 'surroundedByColorOrTransparent']) })),
        ...toolLimit, ...toolLayer }), 'enclose_and_fill'),
    tool('krita_gradient', 'Painting a gradient',
      'Krita\u2019s gradient tool: a gradient from start to end (canvas pixels, may lie off the canvas) onto a NEW layer. options.colors (2-16 hex, evenly spaced) or options.gradient (an installed name); shape linear (default), bilinear, radial, square, conical, conicalSymmetric, spiral, reverseSpiral, polygonal; repeat none|forwards|alternate; reverse; dither. selection or area limits it, else the whole layer. For what fill_region\u2019s linear/radial gradient cannot do (conical, spiral, repeating, dithered). One reversible pass; returns the canvas image and tool_call.',
      object({ name: Type.String({ minLength: 1, maxLength: 120 }), start: point, end: point,
        options: object({ colors: Type.Optional(Type.Array(hex, { minItems: 2, maxItems: 16 })), gradient: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
          shape: word(['linear', 'bilinear', 'radial', 'square', 'conical', 'conicalSymmetric', 'spiral', 'reverseSpiral', 'polygonal']), repeat: word(['none', 'forwards', 'alternate']),
          reverse: flag(), dither: Type.Optional(Type.Union([Type.Boolean(), ...['blueNoise', 'bayer2', 'bayer4', 'bayer8'].map(w => Type.Literal(w))])),
          antiAliasThreshold: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })), opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })), compositeOp: Type.Optional(Type.String({ maxLength: 40 })) }),
        ...toolLimit, ...toolLayer }), 'krita_gradient'),
    tool('smart_patch', 'Smart patch',
      'Smart patch repairs a seam inside a small area: Krita\u2019s PatchMatch inpainting re-makes the area (selection or area; bounding rectangle at most 512 x 512 px, larger damage in pieces) from the paint around it. The repair is a NEW layer holding only the patched pixels (the painting is read, never changed); layer_id patches an edited copy of one of your layers instead. options.accuracy 0-99 (default 50), patchRadius 2-8 (default 4); context 8-512 px of painting around the area to copy from (default 96). One reversible pass; returns the canvas image and tool_call.',
      object({ name: Type.String({ minLength: 1, maxLength: 120 }), layer_id: Type.Optional(Type.String()),
        options: Type.Optional(object({ accuracy: whole(0, 99), patchRadius: whole(2, 8) })), context: whole(8, 512),
        selection: toolLimit.selection, area: toolLimit.area, region: toolLimit.region }), 'smart_patch'),
    tool('apply_filter', 'Applying a filter',
      'Apply a Krita filter (krita_capabilities lists them with their settings) to one of your layers or groups; config holds only the settings to change. mode mask (default): a non-destructive filter mask on the target, for colour balance, curves, HSV or blur without repainting. layer: a filter layer inside your group, grading everything below it there (target the group to grade all of it). copy: filters the pixels of a copy, original hidden, when later strokes need the result; in an Agent move only copy is allowed (masks and filter layers recompute on every refresh). selection (a saved name) or area (selection steps) limits it. Colour to alpha is the colortoalpha filter, config {targetcolor: \u0027#RRGGBB\u0027, threshold: 0-255}: it makes that colour transparent, to lift line art off white paper or a glow off black (a mask, or copy on your layer). The artist\u2019s layers are never filtered: to lift the artist\u2019s sketch, clone_layer it and put the filter on the clone as a mask. One reversible pass: reject removes the effect, fade changes its strength. Returns the canvas image.',
      object({ target: Type.String(), filter: Type.String({ minLength: 1, maxLength: 80 }),
        config: Type.Optional(Type.Record(Type.String(), Type.Union([Type.String(), Type.Number(), Type.Boolean()]))),
        mode: Type.Optional(Type.Union([Type.Literal('mask'), Type.Literal('layer'), Type.Literal('copy')])),
        name: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
        selection: Type.Optional(Type.String({ maxLength: 2000, description: 'A saved selection name, or (our Krita) feature names and expressions such as "Sky - Moon".' })), area: Type.Optional(selectionSteps), panel }), 'apply_filter'),
    tool('colorize_flats', 'Colorizing flats',
      'Flat colours from closed line art in one call, with Krita\u2019s colorize mask: put one seed (x, y, color) inside each region; colour grows up to the lines and under them. color "transparent" keeps a region (such as the background) empty. line_layer is any layer with the lines (read only; the artist\u2019s layers are never changed). The flats go on a NEW layer directly below the line art, a clip_base by default so shadow and light layers can clip_to it; a hidden helper keeps the mask so the artist can refine it in Krita. edge_detection helps with thick or sketchy lines. One reversible pass; returns the canvas image.',
      object({ line_layer: Type.String(), name: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
        seeds: Type.Array(object({ x: coordinate, y: coordinate, color: Type.Union([hex, Type.Literal('transparent')]),
          radius: Type.Optional(Type.Integer({ minimum: 1, maximum: 24 })) }), { minItems: 2, maxItems: 48 }),
        clip_base: Type.Optional(Type.Boolean()), edge_detection: Type.Optional(Type.Boolean()),
        cleanup: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })) }), 'colorize_flats'),
    tool('transform_layer', 'Transforming a layer',
      'Move, scale or rotate one of your layers without repainting it: a live transform mask, so the pixels stay intact and reject puts the layer back. move [dx, dy] in pixels, scale (one factor or [x, y]; a negative factor flips, as [1, -1] for a reflection), rotate in degrees, about pivot [x, y] (default the layer\u2019s centre). Use it to fix placement or proportion of a finished part, such as a moon placed too low or a figure too small. The artist\u2019s layers are never moved. One reversible pass; returns the canvas image.',
      object({ layer_id: Type.String(), name: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
        move: Type.Optional(Type.Array(Type.Number({ minimum: -100000, maximum: 100000 }), { minItems: 2, maxItems: 2 })),
        scale: Type.Optional(Type.Union([Type.Number({ minimum: -50, maximum: 50 }), Type.Array(Type.Number({ minimum: -50, maximum: 50 }), { minItems: 2, maxItems: 2 })])),
        rotate: Type.Optional(Type.Number({ minimum: -360, maximum: 360 })),
        pivot: Type.Optional(Type.Array(Type.Number({ minimum: -100000, maximum: 100000 }), { minItems: 2, maxItems: 2 })) }), 'transform_layer'),
    tool('split_by_color', 'Splitting by colour',
      'Split the visible painting (source "visible") or one layer into its main colour regions, each saved as a named selection ("Split 1 1a2440") with its colour, share of the canvas and bounds, largest first, for fill_region, apply_filter or select steps (saved, add). It finds areas of one colour (a sky, a road, a coat), not objects: an object of several colours is several regions combined with select. colors 2-24 (default 8); region [x,y,w,h] limits it; min_area (pixels) drops specks (default 0.2% of the area split). as_layers: true also copies each region to its own layer in one group, one reversible pass; without it nothing on the canvas changes.',
      object({ source: Type.String(), colors: Type.Optional(Type.Integer({ minimum: 2, maximum: 24 })),
        region: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4 })),
        min_area: Type.Optional(Type.Integer({ minimum: 0 })), as_layers: Type.Optional(Type.Boolean()),
        name_prefix: Type.Optional(Type.String({ minLength: 1, maxLength: 30, pattern: '^[A-Za-z0-9][A-Za-z0-9 _-]*$' })) }), 'split_by_color'),
    tool('clone_layer', 'Cloning a layer',
      'A live copy of any layer (Krita\u2019s clone layer) that follows later edits to the original: a repeated motif (lamp posts, windows, trees) with offset [dx, dy] in pixels, or a reflection (clone, then transform_layer to flip and place it, then apply_filter blur as a mask). The source, even an artist\u2019s layer, is only read. Placed like create_layer, with blend_mode, opacity and clip_to. One reversible pass: reject removes only the clone. Returns the canvas image.',
      object({ source: Type.String(), name: Type.String({ minLength: 1, maxLength: 120 }),
        offset: Type.Optional(Type.Array(Type.Number({ minimum: -100000, maximum: 100000 }), { minItems: 2, maxItems: 2 })),
        blend_mode: Type.Optional(Type.String({ maxLength: 40 })), opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
        clip_to: Type.Optional(Type.String()) }), 'clone_layer'),
    tool('krita_action', 'Running a Krita command',
      'Run one of Krita\u2019s own menu commands by id, from the vetted list in krita_capabilities (krita_actions: id, what it does, kind, needs); only commands checked on this Krita to open no dialog are offered. Pixel actions (mirror, rotate, clear inside a selection) change a copy of one of your paint layers, original hidden, so reject restores it. Selection actions (select opaque and its add/subtract/intersect forms, invert) read any layer, start from selection (a saved name) when given, and save the result as save_as; the artist\u2019s own selection is never changed. One reversible pass for pixel actions; returns the canvas image.',
      object({ action: Type.String({ minLength: 1, maxLength: 80 }), target: Type.String(),
        selection: Type.Optional(Type.String({ maxLength: 40 })), save_as: Type.Optional(Type.String({ minLength: 1, maxLength: 40 })),
        name: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })) }), 'krita_action'),
    tool('composition_guides', 'Setting composition guides',
      'Show Krita guides to plan placement: preset thirds or center, horizon (y in pixels), or exact horizontal/vertical positions; clear removes them. A view aid, not paint: no pass, and the artist\u2019s own guides return when the chat ends.',
      object({ preset: Type.Optional(Type.Union([Type.Literal('thirds'), Type.Literal('center'), Type.Literal('horizon')])),
        horizon: Type.Optional(Type.Number({ minimum: 0, maximum: 100000 })),
        horizontal: Type.Optional(Type.Array(Type.Number({ minimum: 0, maximum: 100000 }), { maxItems: 16 })),
        vertical: Type.Optional(Type.Array(Type.Number({ minimum: 0, maximum: 100000 }), { maxItems: 16 })),
        clear: Type.Optional(Type.Boolean()) }), 'guides'),
    tool('letter', 'Lettering',
      'Letter a comic panel: a caption box or a speech, thought or shout balloon with its text, as editable vector shapes on the page\u2019s Lettering layer. at [x, y] is the top-left in page pixels inside the panel; width is the box width (default about 40% of the panel); tail_to [x, y] points a speech or thought balloon at the speaker. Captions go at a panel\u2019s top-left, balloons above the speaker, read left to right and top to bottom. One call per caption or balloon, so each can be undone alone. Letter after the panel art.',
      object({ panel: Type.String({ pattern: '^P[0-9]{1,2}$' }), kind: Type.Union(['caption','speech','thought','shout'].map(k => Type.Literal(k))),
        text: Type.String({ minLength: 1, maxLength: 400 }), at: point, width: Type.Optional(Type.Number({ minimum: 60, maximum: 8192 })),
        tail_to: Type.Optional(point), font: Type.Optional(Type.String({ maxLength: 120 })), size: Type.Optional(Type.Number({ minimum: 8, maximum: 200 })),
        fill: Type.Optional(hex), ink: Type.Optional(hex), name: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })) }), 'letter'),
    tool('krita_capabilities', 'Checking Krita\u2019s tools',
      'What this Krita offers: blend modes, fill generators with their settings, common filters with key settings, and resource names. full: true lists every filter setting. Read-only.',
      object({ full: Type.Optional(Type.Boolean()) }), 'capabilities'),
    tool('adjust_layer', 'Refining a layer',
      'Change opacity or visibility of any unlocked layer in the painting. Use this to reduce a field’s weight or discard a failed pass. Saves painting.kra and returns its current canvas image.',
      object({ layer_id: Type.String(), opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
        visible: Type.Optional(Type.Boolean()) }), 'adjust_layer'),
    {
      name: 'view_reference', label: 'Studying a reference', executionMode: 'sequential',
      description: 'View an attached reference image or supplied construction map by its ID. Returns the image and original dimensions. Only attachments selected for this study are available.',
      parameters: object({ id: Type.String() }),
      execute: async (_id, { id }, signal) => {
        signal?.throwIfAborted();
        const reference = runtime.study.references.find(item => item.id === id);
        if (!reference) throw new Error('Unknown reference ID. Use the attachment list in the study context.');
        const image = await imageContent(runtime.study.directory, reference.path);
        return { content: [{ type: 'text', text: JSON.stringify({ id, role: reference.role, ...image.info }) }, image.content], details: { id } };
      },
    },
  ];
  shapeLimits(runtime, tools);
  tools.push(recipeTool(runtime, tools.find(t=>t.name==='paint_pass').execute));
  tools.push(contourTool(runtime, tools.find(t=>t.name==='painting_toolbox').execute));
  tools.push(...referenceTools(runtime,tools.find(t=>t.name==='paint_pass').execute,tools.find(t=>t.name==='fill_region').execute));
  // Reference first (studio.mjs fillNudge): the painter's own fill_region, alone or in a batch, may be nudged toward the
  // reference tools once a move. The reference tools' toned ground (above) keeps the plain fill.
  const fill = tools.find(t=>t.name==='fill_region'), fillRegion = fill.execute;
  fill.execute = async (...args) => { await runtime.fillNudge?.(); return fillRegion(...args); };
  // Guided trace: construction lines on the element's own guide layer (guide-tool.ts), mapped from reference pixels as above.
  tools.push(...guideTools(runtime, { execute: operation => nativeExecute(runtime, operation), mapPoint: mapReferencePoint,
    referencePixels: (id, side) => traceReferencePixels(runtime, id, side) }));
  // A flat fill anywhere in a batch is nudged before anything paints (studio.mjs fillNudge), so the batch is refused whole.
  tools.push(batchTool(tools, name => runtime.toolOffered?.(name) ?? true,
    async actions => { if (actions.some(a => a.tool === 'fill_region')) await runtime.fillNudge?.({batch:true}); return prepareBatchShapes(runtime, actions); }));
  tools.push(...assetTools(runtime), skillReadTool());
  return tools;
}

/** Element shapes on the painting (element-shapes 1.5, 1.6): paint_pass inside_shape and propose_protection shape find
 * the element's shape on the canvas the painter last saw and send the plugin a mask file in the chat folder with its
 * bounds; the prompt never reaches it. A pass's limits are checked before the canvas is read or the worker asked, and an
 * uncertain shape (raw score under LOW_SCORE) paints nothing. paint_batch finds every action's shape first, on the same
 * view, before any action paints (prepareBatchShapes); a proposed shape is still the artist's to keep or discard. */
const readyShapes = new WeakMap();           // a batch action's found shape object -> the shape it came from
function withShapeReport(result, found) {
  const report = shapeReport(found);
  return { ...result, content: [...(result.content ?? []), { type: 'text', text: JSON.stringify({ shape: report }) }],
    details: { ...result.details, shape: { ...report, ...shapeTimings(found) } } };
}
function shapeLimits(runtime, tools) {
  const pass = tools.find(t => t.name === 'paint_pass'), paintPass = pass.execute;
  pass.execute = async (id, args, signal) => {
    if (!args.inside_shape) return paintPass(id, args, signal);
    let shape = readyShapes.get(args.inside_shape);
    if (!shape) { shape = await passShape(runtime, args); signal?.throwIfAborted(); }
    const { inside_shape: _prompt, ...rest } = args;
    runtime.emit({ type: 'action', seconds: 0, message: `Painting ${args.name} inside the shape you named (score ${shapeReport(shape.found).score}).` });
    return withShapeReport(await paintPass(id, { ...rest, inside_shape: { mask_path: shape.mask_path, bounds: shape.bounds } }, signal), shape.found);
  };
  const protect = tools.find(t => t.name === 'propose_protection'), proposeArea = protect.execute;
  protect.execute = async (id, args, signal) => {
    if (!args.area === !args.shape) throw new Error('Give propose_protection an area or shape (one of them).');
    if (!args.shape) return proposeArea(id, args, signal);
    const shape = await canvasShape(runtime, args.shape);
    signal?.throwIfAborted();
    return withShapeReport(await proposeArea(id, { name: args.name, area: [{ element_shape: { mask_path: shape.mask_path, bounds: shape.bounds } }] }, signal), shape.found);
  };
}
/** Every paint_pass inside_shape of a batch: limits checked for all, then each found on the view seen before the batch;
 * one refusal refuses the batch before anything paints. Returns the actions with each prompt replaced by its shape. */
export async function prepareBatchShapes(runtime, actions) {
  const shaped = actions.map((action, index) => ({ action, label: `Action ${index + 1}: ` }))
    .filter(({ action }) => action.tool === 'paint_pass' && action.arguments?.inside_shape);
  if (!shaped.length) return actions;
  for (const { action, label } of shaped) checkPassLimits(runtime, action.arguments, label);
  const found = new Map();
  for (const { action, label } of shaped) found.set(action, await passShape(runtime, action.arguments, label));
  return actions.map(action => {
    const shape = found.get(action);
    if (!shape) return action;
    const ready = { mask_path: shape.mask_path, bounds: shape.bounds };
    readyShapes.set(ready, shape);
    return { ...action, arguments: { ...action.arguments, inside_shape: ready } };
  });
}

// Several painting actions in one model call. Model round trips, not brushwork, were
// most of a run's time (Starry Night: 62 of 76 minutes in 295 painter calls).
export const BATCH_TOOLS = ['paint_pass','paint_recipe','paint_contours','adjust_layer','painting_toolbox','select',...CRAFT_OPERATIONS,'letter'];
export const BATCH_LIMIT = 10;
// "$N" in a layer field names the layer action N of the same batch created.
const LAYER_FIELDS = ['layer_id', 'clip_to', 'source_layer_id', 'target', 'line_layer'];
export function batchReferences(args, ran, index) {
  const resolved = { ...args };
  for (const field of LAYER_FIELDS) {
    const match = typeof args[field] === 'string' && /^\$(\d+)$/.exec(args[field]);
    if (!match) continue;
    const source = ran.find(item => item.action === Number(match[1]));
    if (Number(match[1]) > index || !source?.layer_id)
      throw new Error(`Action ${index + 1}: ${field} "${args[field]}" must name an earlier action in this batch that created a layer.`);
    resolved[field] = source.layer_id;
  }
  return resolved;
}

/** beforePaint: a check of the whole batch after validation, before anything paints (it throws to refuse the batch);
 * it may return the actions prepared for painting (paint_pass shapes found), which then run instead. */
export function batchTool(tools, offered = /** @type {(name: string) => boolean} */ (() => true), beforePaint = /** @type {(actions: any[]) => Promise<any[] | void>} */ (async () => {})) {
  const byName = Object.fromEntries(tools.filter(t => BATCH_TOOLS.includes(t.name)).map(t => [t.name, t]));
  // The original executes, captured now: wrappers added later (pacing) apply once per batch, not per action.
  const run = Object.fromEntries(Object.entries(byName).map(([name, t]) => [name, t.execute]));
  return defineTool({
    name: 'paint_batch', label: 'Painting a batch', executionMode: 'sequential',
    description: 'Run 1-'+BATCH_LIMIT+' painting actions in order in ONE call: '+BATCH_TOOLS.join(', ')+'. Each action takes exactly the arguments of that tool. '
      +'Plan several complementary moves (for example block-in, then texture, then edge accents), send them together, then judge the single returned canvas image before the next batch. '
      +'Every action is validated before anything paints; the batch stops at the first failed action and reports what ran. '
      +'A layer made earlier in the batch can be named "$N" (N = its action number) in layer_id, clip_to, source_layer_id, target or line_layer, e.g. flats with clip_base, then a shadow with clip_to "$1".',
    parameters: Type.Object({
      summary: Type.Optional(Type.String({ maxLength: 300 })),
      actions: Type.Array(Type.Object({ tool: Type.Union(BATCH_TOOLS.map(name => Type.Literal(name))), arguments: Type.Object({}, { additionalProperties: true }) },
        { additionalProperties: false }), { minItems: 1, maxItems: BATCH_LIMIT }),
    }, { additionalProperties: false }),
    execute: async (id, { actions }, signal) => {
      // Validate the whole batch first, as a single pass is validated before painting.
      actions.forEach(({ tool, arguments: args }, index) => {
        const target = byName[tool];
        if (!target || !offered(tool)) throw new Error(`Action ${index + 1}: ${tool} is not available in this mode.`);
        if (!Value.Check(target.parameters, args)) {
          const issue = [...Value.Errors(target.parameters, args)][0];
          throw new Error(`Action ${index + 1} (${tool}) does not match its schema${issue ? ` at ${issue.instancePath || '/'}: ${issue.message}` : ''}. Nothing was painted.`);
        }
      });
      const prepared = /** @type {any[]} */ ((await beforePaint(actions)) ?? actions);
      const prefix = batchPrefix(id);
      const ran = [];
      let last;
      for (const [index, { tool, arguments: given }] of prepared.entries()) {
        signal?.throwIfAborted();
        try {
          const args = batchReferences(given, ran, index);
          last = await run[tool](`${prefix}-${index}`, args, signal);
          const details = last.details ?? {};
          ran.push({ action: index + 1, tool, status: details.status ?? 'ok', ...(details.layer_id ? { layer_id: details.layer_id } : {}),
            ...(details.visual_check ? { visual_check: details.visual_check } : {}) });
        } catch (error) {
          // Uncertain outcomes keep their existing recovery: rethrow so the run pauses or recovers as for a single action.
          if (!ran.length || error.code === 'outcome_unknown' || error.code === 'partial_change' || error.code === 'checkpoint_failed') throw error;
          ran.push({ action: index + 1, tool, status: 'failed', error: String(error.message ?? error).slice(0, 400) });
          break;
        }
      }
      const image = [...(last?.content ?? [])].reverse().find(part => part.type === 'image');
      const summary = { status: ran.every(r => r.status !== 'failed') ? 'ok' : 'stopped', actions: ran,
        ...(ran.length < actions.length ? { not_run: actions.length - ran.length } : {}),
        canvas: last?.details ? JSON.parse(modelResultText(last.details, { compactLayers: true })) : undefined };
      return { content: [{ type: 'text', text: JSON.stringify(summary) }, ...(image ? [image] : [])], details: { ...last?.details, batch: ran } };
    },
  });
}

/** Operation ids of a paint_batch call are `${batchPrefix(id)}-${index}`. */
export const batchPrefix = id => 'batch-' + createHash('sha256').update(String(id)).digest('hex').slice(0, 16);

// Only the newest canvas images stay in what the model is sent; older tool-result
// images become a short note. The saved transcript keeps everything.
export function keepRecentImages(messages, keep=2) {
  let seen=0;
  const out=[...messages];
  for (let i=out.length-1;i>=0;i--) {
    const m=out[i];
    if (m?.role!=='toolResult' || !Array.isArray(m.content) || !m.content.some(p=>p.type==='image')) continue;
    if (seen<keep) { seen+=m.content.filter(p=>p.type==='image').length; continue; }
    out[i]={...m,content:m.content.map(p=>p.type==='image'?{type:'text',text:'[Earlier canvas image omitted; a newer canvas image follows.]'}:p)};
  }
  return out;
}
