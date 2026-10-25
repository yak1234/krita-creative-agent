// @ts-check
// Image assets for the painter: generate or edit an image, prepare it in the Python sandbox (PNG under
// 5 MB, optional cut-out), and attach it as a reference the painter then repaints with
// paint_from_reference. Assets are never pasted into the painting.
// Backends (execution setting `assets`), chosen on New Moscow tests (2026-10-16):
// - codex (default): the ChatGPT Codex backend's image_generation tool through the artist's Codex
//   sign-in, included in their ChatGPT plan. Edits kept the framing best (city SSIM 0.88) and
//   cut-outs come back truly transparent. The request follows pi-codex-image-gen (Apache-2.0).
// - openrouter: Seedream painted the most painterly new images but reframes edits; Muse kept an
//   edit's framing (SSIM 0.69); FLUX 3 Klein is the cheap draft. 1-2 cents an image.
import { defineTool } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { randomUUID } from 'node:crypto';
import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { basename, join, resolve, sep } from 'node:path';
import { existsSync, readdirSync } from 'node:fs';
import { imageContent, imageInfo } from './files.mjs';
import { runPython } from './python-sandbox.mjs';
import { SKILLS_DIR } from './skills.mjs';

export const ASSET_MODELS = Object.freeze({
  generate: { model: 'bytedance-seed/seedream-5-0-flash', endpoint: 'chat' },
  edit: { model: 'meta/muse-image', endpoint: 'images' },
  draft: { model: 'black-forest-labs/flux-3-image-klein', endpoint: 'images' },
});
export const ASSET_BACKENDS = ['codex', 'openrouter'];
const CODEX_URL = 'https://chatgpt.com/backend-api/codex/responses';
// The Codex chat model only calls the image tool; the backend picks the image model.
export const CODEX_MODEL = 'gpt-6-astra';
const CODEX_QUALITY = { generate: 'medium', draft: 'low', edit: 'medium' };
// Assets per conversation: Codex assets come out of the ChatGPT plan, OpenRouter ones cost money.
export const ASSET_LIMIT = 12;
export const CODEX_ASSET_LIMIT = 40;
const OPENROUTER = 'https://openrouter.ai/api/v1/';
const ASPECTS = ['1:1', '4:3', '3:4', '3:2', '2:3', '16:9', '9:16', '21:9'];
// A flat mid-grey: distinct from white snow and dark foliage, and no "paper" texture for the cut-out to leave behind.
const TRANSPARENT_BACKGROUND = ' Show the subject alone, whole and centred, isolated on a transparent background: no ground, no shadow, no frame and nothing else.';
const PLAIN_BACKGROUND = ' Show the subject alone, whole and centred, on a perfectly flat, untextured, uniform mid-grey (#808080) background: no paper or canvas texture, no vignette, no shadow, no ground, no frame and nothing else.';
// Luna checks every asset before the painter sees it, like the pass checks in visual-checks.mjs.
// A cut-out that left background behind was painted as white haze around a live tree (2026-10-16).
export const ASSET_CHECK_THRESHOLD = 0.7;
const noul = (instructions, yes, no) => ({ type: 'noul', instructions, criteria: { true: yes, false: no } });
export const ASSET_QUESTIONS = Object.freeze({
  leftover_background: noul('Transparent areas of ASSET are shown as a grey checkerboard. Around the subject, are there pale specks, haze, smoke-like wisps or patches left over from a removed background?',
    'There are leftover background specks, haze or patches around the subject.', 'The subject sits cleanly on the checkerboard with nothing left around it.'),
  cut_off: noul('Is the subject of ASSET cut off at an edge of the image or missing a part (a tree without its top or trunk, a figure without its feet)?',
    'The subject is cut off or incomplete.', 'The whole subject is inside the image.'),
  extra_content: noul('Besides the one requested subject, does ASSET contain anything else: ground, a floor or shadow patch, a frame, text, or a second object?',
    'There is extra content besides the subject.', 'Only the subject is there.'),
  edit_drift: noul('AFTER is BEFORE with one area repainted as requested. Outside that area, did anything move, change shape or disappear (buildings, a tree, figures, lights)?',
    'Something outside the requested area moved or changed.', 'Everything outside the requested area is where it was.'),
});
const CHECKS = { cutout: ['leftover_background', 'cut_off', 'extra_content'], generate: ['cut_off'], edit: ['edit_drift'] };
const ADVICE = {
  leftover_background: 'leftover background around the subject: run_skill_script cutout.py with tolerance 90, or regenerate',
  cut_off: 'the subject is cut off: regenerate with "the whole subject, with space around it"',
  extra_content: 'extra content besides the subject: regenerate naming only the subject',
  edit_drift: 'the edit moved content outside the requested area: use a smaller edit_region or say what must stay',
};

/** {probabilities, findings} for one asset, or {fallback} when Luna is unavailable. */
export async function assetCheck({ client, asset, before, kind, signal }) {
  const ids = CHECKS[kind];
  const parts = kind === 'edit' ? ['BEFORE (the image that was edited):', before, 'AFTER (the edited image):', asset] : ['ASSET (an image made to be painted into a painting):', asset];
  const reply = await client.decide({ signal, purpose: 'check-asset', parts, questions: Object.fromEntries(ids.map(id => [id, ASSET_QUESTIONS[id]])) });
  if (reply.fallback) return { fallback: reply.fallback };
  const probabilities = {};
  for (const id of ids) {
    const p = reply.answers?.[id]?.type === 'noul' ? reply.answers[id].noul : null;
    if (!Number.isFinite(p) || p < 0 || p > 1) return { fallback: 'service_or_response_error' };
    probabilities[id] = p;
  }
  return { probabilities, findings: ids.filter(id => probabilities[id] >= ASSET_CHECK_THRESHOLD), cost: reply.usage?.cost ?? null };
}

const rect = Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4 });
/** @template {import('typebox').TProperties} T @param {T} properties */
const object = properties => Type.Object(properties, { additionalProperties: false });

const dataUrl = (data, mimeType) => 'data:' + mimeType + ';base64,' + data.toString('base64');
const gcd = (a, b) => b ? gcd(b, a % b) : a;

// The artist sets how many AI images a chat may use (goal.limits.ai_images, null = no limit); no chat means none.
// Checked before any image model is called, so a refusal costs nothing. Only the allowance grants permission.
export function assertAiImageAllowed(goal) {
  const allowance = goal?.limits && 'ai_images' in goal.limits ? goal.limits.ai_images : 0;
  if (allowance === null || (goal?.ai_images_used ?? 0) < allowance) return;
  throw new Error((allowance === 0 ? 'AI images are off for this chat (allowance 0).' : `This chat's AI image allowance (${allowance}) is used up.`) +
    ' Paint this by hand. The artist can raise AI images for this chat in the panel.');
}

// The asset size for one canvas target: exactly the target's aspect ratio (paint_from_reference
// requires it to 1e-6), as large as fits in 2560 px, never larger than the target itself.
export function fitSize(/** @type {number[]} */ [, , width, height], maxSide = 2560) {
  const g = gcd(width, height), unit = [width / g, height / g];
  const m = Math.min(g, Math.floor(maxSide / Math.max(...unit)));
  if (m < 1) throw new Error('fit_to ' + width + 'x' + height + ' has no exact smaller size; round the target to multiples of 8.');
  return [unit[0] * m, unit[1] * m];
}
// Transfer steps for a source size: the defaults [6,2.5,1.2], scaled up so the coarse and fine passes
// stay under the generator's 200,000-sample cap (a 1248x1664 source failed with the defaults live).
export function transferSteps(width, height) {
  const f = Math.max(1, Math.sqrt(width * height * (1 / 36 + 1 / 6.25) / 170000));
  return [6, 2.5, 1.2].map(s => Math.round(s * f * 10) / 10);
}

// One image from OpenRouter: the chat endpoint for models that answer in chat, /images for the rest.
// Codex image sizes: a portrait, landscape or square frame for the requested aspect; edits keep their input's.
export function codexSize(aspect) {
  if (!aspect) return 'auto';
  const [w, h] = aspect.split(':').map(Number);
  return w > h * 1.1 ? '1536x1024' : h > w * 1.1 ? '1024x1536' : '1024x1024';
}

// One image from the ChatGPT Codex backend: a Responses call whose only job is to call the built-in
// image_generation tool; the image arrives as base64 in the image_generation_call output item.
export async function requestCodexImage({ prompt, inputs = [], size = 'auto', transparent = false, quality = 'medium', token, fetchImpl = globalThis.fetch, signal }) {
  if (!token) throw new Error('Image assets use your ChatGPT (Codex) sign-in: sign in with Codex in the Creative Agent panel, or choose OpenRouter under Image assets in its settings.');
  let account;
  try { account = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString())['https://api.openai.com/auth']?.chatgpt_account_id; } catch {}
  if (!account) throw new Error('The Codex sign-in has no ChatGPT account. Sign in with Codex again in the Creative Agent panel.');
  const body = { model: CODEX_MODEL, store: false, stream: true,
    instructions: 'You are generating bitmap image assets. For this request, call the image_generation tool exactly once. Do not answer with only text unless image generation is unavailable.',
    input: [{ role: 'user', content: [{ type: 'input_text', text: prompt }, ...inputs.map(({ data, mimeType }) => ({ type: 'input_image', image_url: dataUrl(data, mimeType) }))] }],
    tools: [{ type: 'image_generation', output_format: 'png', size, quality, ...(transparent ? { background: 'transparent' } : {}) }],
    tool_choice: 'auto', parallel_tool_calls: false, text: { verbosity: 'low' } };
  const response = await fetchImpl(CODEX_URL, { method: 'POST', redirect: 'error', signal, body: JSON.stringify(body), headers: {
    Authorization: 'Bearer ' + token, 'chatgpt-account-id': account, originator: 'pi', 'OpenAI-Beta': 'responses=experimental',
    accept: 'text/event-stream', 'content-type': 'application/json' } });
  const text = await response.text();
  // Never echo tokens back in an error.
  if (!response.ok) throw new Error('The Codex image request failed (' + response.status + '): ' + text.slice(0, 240).replace(/eyJ[\w.-]+/g, '[redacted]'));
  let image, failure;
  for (const line of text.split('\n')) {
    if (!line.startsWith('data:')) continue;
    let event; try { event = JSON.parse(line.slice(5)); } catch { continue; }
    if (event.type === 'response.output_item.done' && event.item?.type === 'image_generation_call' && event.item.result) image = event.item;
    if (event.type === 'response.failed' || event.type === 'error') failure = event.response?.error?.message ?? event.error?.message ?? event.message;
  }
  if (!image) throw new Error('Codex returned no image' + (failure ? ': ' + String(failure).slice(0, 240) : '.'));
  return { data: Buffer.from(image.result, 'base64'), cost: 0, model: 'codex/' + CODEX_MODEL + ' image_generation', included_in_plan: true };
}

export async function requestImage({ choice, prompt, inputs = [], aspect, key, fetchImpl = globalThis.fetch, signal }) {
  if (!key) throw new Error('Image assets need an OpenRouter connection: connect OpenRouter in the Creative Agent settings.');
  const headers = { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' };
  const images = inputs.map(({ data, mimeType }) => ({ type: 'image_url', image_url: { url: dataUrl(data, mimeType) } }));
  const body = choice.endpoint === 'chat'
    ? { model: choice.model, modalities: ['image'], usage: { include: true }, ...(aspect ? { image_config: { aspect_ratio: aspect } } : {}),
        messages: [{ role: 'user', content: [{ type: 'text', text: prompt }, ...images] }] }
    : { model: choice.model, prompt, n: 1, aspect_ratio: aspect ?? 'auto', ...(images.length ? { input_references: images } : {}) };
  const response = await fetchImpl(OPENROUTER + (choice.endpoint === 'chat' ? 'chat/completions' : 'images'), { method: 'POST', headers, body: JSON.stringify(body), signal });
  const reply = await response.json().catch(() => ({}));
  if (!response.ok || reply.error) throw new Error('The image model refused: ' + String(reply.error?.message ?? response.status).slice(0, 300));
  const url = choice.endpoint === 'chat' ? reply.choices?.[0]?.message?.images?.[0]?.image_url?.url : (reply.data?.[0]?.b64_json ? 'data:image/png;base64,' + reply.data[0].b64_json : reply.data?.[0]?.url);
  if (!url) throw new Error('The image model returned no image.');
  const data = url.startsWith('data:') ? Buffer.from(url.slice(url.indexOf(',') + 1), 'base64') : Buffer.from(await (await fetchImpl(url, { signal })).arrayBuffer());
  return { data, cost: reply.usage?.cost ?? null, model: choice.model };
}

/** The image backend the `assets` setting names: codex (the default) or openrouter. */
export const assetBackend = runtime => ASSET_BACKENDS.includes(runtime.executionSettings?.assets) ? runtime.executionSettings.assets : 'codex';

/** One image from the backend the `assets` setting names, for make_asset and a canvas reference (canvas-reference.ts).
 * An edit keeps its input's framing on OpenRouter; on Codex `size` follows `aspect` (an edit of a canvas passes the
 * canvas's proportions, so a wide canvas comes back wide). */
export async function requestAssetImage(runtime, /** @type {{mode: 'generate'|'draft'|'edit', prompt: string, inputs?: {data: Buffer, mimeType: string}[], aspect?: string, transparent?: boolean, fetchImpl?: typeof fetch, signal?: AbortSignal}} */ { mode, prompt, inputs = [], aspect, transparent = false, fetchImpl, signal }) {
  return assetBackend(runtime) === 'codex'
    ? requestCodexImage({ prompt, inputs, size: codexSize(aspect), transparent, quality: CODEX_QUALITY[mode], token: await runtime.codexKey?.(), fetchImpl, signal })
    : requestImage({ choice: ASSET_MODELS[mode], prompt, inputs, aspect: mode === 'edit' ? undefined : aspect, key: await runtime.imageKey?.(), fetchImpl, signal });
}

// Assets and the sandbox's work files live in <study>/assets; Python can write there and nowhere else.
async function assetsFolder(runtime) {
  const folder = join(runtime.study.directory, 'assets');
  await mkdir(folder, { recursive: true });
  return folder;
}
function referenceFile(runtime, id) {
  const ref = runtime.study.references.find(r => r.id === id);
  if (!ref) throw new Error('Unknown reference_id ' + id + '. Use an id from the attachment list or a make_asset result.');
  return ref;
}
// A reference's file inside the assets folder (copied in when it lives elsewhere in the study).
async function intoAssets(runtime, folder, id) {
  const ref = referenceFile(runtime, id);
  const inside = resolve(ref.path).startsWith(folder + sep);
  if (inside) return basename(ref.path);
  const name = 'input-' + basename(ref.path);
  if (!existsSync(join(folder, name))) await copyFile(ref.path, join(folder, name));
  return name;
}

function skillScript(skill, script) {
  if (!/^[a-z0-9-]+$/.test(skill) || !/^[a-z0-9_]+\.py$/.test(script)) throw new Error('Name a bundled skill and one of its scripts, such as image-asset and cutout.py.');
  const folder = join(SKILLS_DIR, skill, 'scripts');
  if (!existsSync(join(folder, script))) {
    const available = existsSync(folder) ? readdirSync(folder).filter(f => f.endsWith('.py') && !f.startsWith('_')).join(', ') : 'none';
    throw new Error('No script ' + script + ' in skill ' + skill + '. Available: ' + available + '.');
  }
  return { folder, file: join(folder, script) };
}

async function prepare(runtime, folder, raw, { cutout, tolerance, fit, anchor, signal } = /** @type {{cutout?: boolean, tolerance?: number, fit?: number[] | null, anchor?: string, signal?: AbortSignal}} */ ({})) {
  const id = 'asset-' + randomUUID().slice(0, 8);
  const { folder: scripts, file } = skillScript('image-asset', 'prepare.py');
  const { result } = await runPython({ work: folder, mounts: [{ root: scripts, at: '/skill' }], signal, code: await readFile(file, 'utf8'),
    args: { input: raw, output: id + '.png', preview: id + '-preview.jpg', cutout: !!cutout, ...(tolerance ? { tolerance } : {}), ...(fit ? { fit, anchor: anchor ?? 'bottom' } : {}) } });
  return { id, file: join(folder, id + '.png'), preview: join(folder, id + '-preview.jpg'), result };
}

// Luna's verdict on a prepared asset: Off skips it, Evaluate records it in the background without
// delaying the painter, Guide waits for it so make_asset can act on it.
async function checked(runtime, prepared, kind, before, signal) {
  const mode = runtime.lunaMode?.() ?? 'off';
  if (mode === 'off' || !runtime.luna) return null;
  const run = async () => {
    let result;
    try {
      const asset = (await imageContent(runtime.study.directory, prepared.preview)).content;
      result = await assetCheck({ client: await runtime.luna(), asset, before: before && { type: 'image', data: before.data.toString('base64'), mimeType: before.mimeType }, kind, signal });
    } catch { result = { fallback: 'service_or_response_error' }; }
    runtime.diagnostics?.record?.({ type: 'asset_check', mode, asset: prepared.id, kind, ...(result.fallback ? { status: 'fallback', reason: result.fallback } : { status: 'ok', probabilities: result.probabilities, findings: result.findings, cost: result.cost }) });
    return result;
  };
  if (mode === 'evaluate') { run().catch(() => {}); return null; }
  return run();
}

// The ceiling on stored assets per conversation (any source), apart from the artist's AI image allowance.
function assertAssetRoom(runtime) {
  const limit = runtime.executionSettings?.assets === 'openrouter' ? ASSET_LIMIT : CODEX_ASSET_LIMIT;
  // Element images from the project folder are the artist's, not made assets: they take no room.
  if (runtime.study.references.filter(r => r.role === 'asset' && r.source !== 'folder').length >= limit) throw new Error('This conversation already has ' + limit + ' assets. Reuse one of them.');
}

/** An image file as a reference asset of the chat (make_asset's, a script's, a canvas reference's). */
export async function attachAsset(runtime, { id, file, name, notes, source }) {
  assertAssetRoom(runtime);
  const info = imageInfo(await readFile(file));
  const reference = { id, path: file, source_path: file, role: 'asset', purpose: 'material', name: String(name).slice(0, 200), notes: String(notes ?? '').slice(0, 2000), source, ...info };
  runtime.study.references.push(reference);
  await runtime.persist?.(); runtime.publish?.();
  runtime.emit?.({ type: 'action', message: 'Asset ready: ' + reference.name, seconds: 0 });
  return reference;
}

async function answer(runtime, reference, preview, extra, target) {
  const image = await imageContent(runtime.study.directory, preview);
  const steps = transferSteps(reference.width, reference.height);
  const ready = target ? { reference_id: reference.id, source: [0, 0, reference.width, reference.height], target, steps } : null;
  const text = JSON.stringify({ reference_id: reference.id, name: reference.name, width: reference.width, height: reference.height, ...extra,
    ...(ready ? { paint_from_reference: ready } : { steps }),
    next: 'Look at the preview first: transparent areas show as a grey checkerboard, so leftover background shows as pale specks or haze around the subject (fix it with run_skill_script cutout.py, tolerance 70). ' +
      (ready ? 'Then call paint_from_reference with exactly the paint_from_reference arguments above (add name and preset).'
        : 'Then call paint_from_reference with reference_id ' + reference.id + ', source [0,0,' + reference.width + ',' + reference.height + '], steps ' + JSON.stringify(steps) +
          ' and a canvas target with exactly the same aspect ratio (or make the asset with fit_to the target).') });
  return { content: [{ type: /** @type {const} */ ('text'), text }, image.content], details: { reference_id: reference.id, ...extra } };
}

export function assetTools(runtime, { fetchImpl } = /** @type {{fetchImpl?: typeof fetch}} */ ({})) {
  const makeAsset = defineTool({
    name: 'make_asset', label: 'Making an image asset', executionMode: 'sequential',
    description: 'Generate or edit an image with an image model and attach it as a reference (an asset) for paint_from_reference. Never pastes into the painting. ' +
      'mode generate: a new image from the prompt (painterly, best quality). mode draft: the same, cheaper and smaller, for trying an idea. ' +
      'mode edit: change an existing image and keep its framing: edit_region [x,y,w,h] crops the current canvas, or edit_reference_id uses an attached image. ' +
      'style_reference_id adds an image whose style to follow. cutout: true makes the subject\'s plain background transparent and crops to it (objects such as a tree or a figure); ' +
      'leave it false for backgrounds such as a sky. fit_to [x,y,w,h] sizes the asset for that canvas target and returns ready paint_from_reference arguments. Workflow in skill image-asset.',
    parameters: object({
      name: Type.String({ minLength: 1, maxLength: 80, description: 'Short asset name, e.g. "Christmas tree"' }),
      prompt: Type.String({ minLength: 10, maxLength: 2000, description: 'What to paint, in the painting\'s style and lighting. For edit: what to change and what to keep.' }),
      mode: Type.Union([Type.Literal('generate'), Type.Literal('draft'), Type.Literal('edit')]),
      aspect_ratio: Type.Optional(Type.Union(ASPECTS.map(a => Type.Literal(a)), { description: 'Ignored for edit, which keeps the input\'s framing' })),
      cutout: Type.Optional(Type.Boolean()),
      edit_region: Type.Optional(rect), edit_reference_id: Type.Optional(Type.String()), style_reference_id: Type.Optional(Type.String()),
      fit_to: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4, description: 'Canvas target [x,y,w,h] to size the asset for: it comes back at exactly that aspect ratio with ready paint_from_reference arguments' })),
      anchor: Type.Optional(Type.Union([Type.Literal('bottom'), Type.Literal('center'), Type.Literal('fill')], { description: 'With fit_to: bottom stands a subject on the target\'s bottom edge (default), center centres it, fill crops to cover (backgrounds)' })),
    }),
    execute: async (callId, params, signal) => {
      signal?.throwIfAborted();
      assertAiImageAllowed(runtime.goal);
      assertAssetRoom(runtime);   // before generating: a refused image is never paid for
      const folder = await assetsFolder(runtime);
      const inputs = [];
      if (params.mode === 'edit') {
        if (!params.edit_region === !params.edit_reference_id) throw new Error('For mode edit give exactly one of edit_region (a canvas crop) or edit_reference_id.');
        if (params.edit_region) {
          const observed = await runtime.callNative('observe', { region: params.edit_region }, callId);
          inputs.push(await readImage(resolve(runtime.study.directory, observed.image_path)));
        } else inputs.push(await readImage(referenceFile(runtime, params.edit_reference_id).path));
      } else if (params.edit_region || params.edit_reference_id) throw new Error('edit_region and edit_reference_id are for mode edit.');
      if (params.style_reference_id) inputs.push(await readImage(referenceFile(runtime, params.style_reference_id).path));
      const backend = assetBackend(runtime);
      const prompt = params.prompt + (params.cutout ? (backend === 'codex' ? TRANSPARENT_BACKGROUND : PLAIN_BACKGROUND) : '') +
        (params.mode === 'edit' && inputs.length > 1 ? ' Edit the first image; the second image is only a style reference.' : '');
      runtime.emit?.({ type: 'status', phase: 'asset', message: 'Making asset: ' + params.name });
      const aspect = params.mode === 'edit' ? undefined : params.aspect_ratio;
      const image = await requestAssetImage(runtime, { mode: params.mode, prompt, inputs, aspect, transparent: !!params.cutout, fetchImpl, signal });
      const raw = 'raw-' + randomUUID().slice(0, 8) + '.img';
      await writeFile(join(folder, raw), image.data);
      const fit = params.fit_to ? fitSize(params.fit_to) : null;
      const options = { cutout: params.cutout, fit, anchor: params.anchor ?? (params.cutout ? 'bottom' : 'fill'), signal };
      let prepared = await prepare(runtime, folder, raw, options);
      const kind = params.mode === 'edit' ? 'edit' : params.cutout ? 'cutout' : 'generate';
      let verdict = await checked(runtime, prepared, kind, inputs[0], signal);
      // Guide: leftover background is fixed here, with stronger cut-outs, before the painter sees the asset.
      for (const tolerance of [70, 90]) {
        if (!verdict?.findings?.includes('leftover_background')) break;
        prepared = await prepare(runtime, folder, raw, { ...options, tolerance });
        verdict = await checked(runtime, prepared, kind, inputs[0], signal);
        if (verdict) verdict.retried_tolerance = tolerance;
      }
      // The image exists (and may have cost money), so it counts; attach saves the chat with the new count.
      if (runtime.goal) runtime.goal.ai_images_used = (runtime.goal.ai_images_used ?? 0) + 1;
      const reference = await attachAsset(runtime, { id: prepared.id, file: prepared.file, name: params.name, notes: params.prompt, source: { mode: params.mode, model: image.model } });
      const note = verdict && !verdict.fallback ? { asset_check: { findings: verdict.findings.map(id => ADVICE[id]),
        probabilities: Object.fromEntries(Object.entries(verdict.probabilities).map(([k, v]) => [k, Math.round(v * 100) / 100])),
        ...(verdict.retried_tolerance ? { cutout_retried_at_tolerance: verdict.retried_tolerance } : {}) } } : {};
      return answer(runtime, reference, prepared.preview, { model: image.model, cost_usd: image.cost, transparent_share: prepared.result.transparent_share, ...note }, params.fit_to);
    },
  });
  const runSkillScript = defineTool({
    name: 'run_skill_script', label: 'Running a skill script', executionMode: 'sequential',
    description: 'Run one of a bundled skill\'s Python scripts (listed in its SKILL.md) on attached images, in a sandbox that can only see this conversation\'s assets. ' +
      'inputs maps a script argument to a reference_id (the file is passed in); args are the other arguments; region_inputs maps an argument to a canvas region [x,y,w,h] to pass a crop of the painting. ' +
      'Images the script writes become new assets you can paint with paint_from_reference.',
    parameters: object({
      skill: Type.String({ minLength: 1, maxLength: 64 }), script: Type.String({ minLength: 4, maxLength: 64 }),
      inputs: Type.Optional(Type.Record(Type.String({ maxLength: 40 }), Type.String({ maxLength: 80 }))),
      region_inputs: Type.Optional(Type.Record(Type.String({ maxLength: 40 }), rect)),
      args: Type.Optional(Type.Record(Type.String({ maxLength: 40 }), Type.Union([Type.String({ maxLength: 400 }), Type.Number(), Type.Boolean()]))),
      name: Type.Optional(Type.String({ maxLength: 80, description: 'Name for the new asset' })),
    }),
    execute: async (callId, params, signal) => {
      signal?.throwIfAborted();
      const { folder: scripts, file } = skillScript(params.skill, params.script);
      const folder = await assetsFolder(runtime);
      const args = { ...(params.args ?? {}) };
      for (const [key, id] of Object.entries(params.inputs ?? {})) args[key] = await intoAssets(runtime, folder, id);
      for (const [key, region] of Object.entries(params.region_inputs ?? {})) {
        const observed = await runtime.callNative('observe', { region }, callId);
        const name = 'canvas-' + randomUUID().slice(0, 8) + '.png';
        await copyFile(resolve(runtime.study.directory, observed.image_path), join(folder, name));
        args[key] = name;
      }
      const output = 'asset-' + randomUUID().slice(0, 8);
      args.output ??= output + '.png';
      runtime.emit?.({ type: 'status', phase: 'asset', message: 'Running ' + params.skill + '/' + params.script });
      const { result } = await runPython({ work: folder, mounts: [{ root: scripts, at: '/skill' }], args, signal, code: await readFile(file, 'utf8') });
      const made = [];
      for (const item of result?.outputs ?? []) {
        const path = String(item.path ?? '');
        if (!path.startsWith('/work/') || path.includes('..')) continue;
        const local = join(folder, path.slice(6));
        if (!existsSync(local)) continue;
        const id = basename(local).replace(/\.png$/, '').startsWith('asset-') ? basename(local).replace(/\.png$/, '') : 'asset-' + randomUUID().slice(0, 8);
        made.push(await attachAsset(runtime, { id, file: local, name: params.name ?? (params.script.replace(/\.py$/, '') + ' result'), notes: item.notes, source: { skill: params.skill, script: params.script } }));
      }
      if (!made.length) return { content: [{ type: 'text', text: JSON.stringify({ result }) }], details: { result } };
      // A preview for the model to see the result (transparency on a checkerboard).
      const previewName = made[0].id + '-preview.jpg';
      await runPython({ work: folder, mounts: [{ root: skillScript('image-asset', 'prepare.py').folder, at: '/skill' }], signal,
        code: 'import asset_ops as ops\nops.preview(ops.load_rgba("/work/" + ARGS["input"]), "/work/" + ARGS["preview"])\nRESULT = 1',
        args: { input: basename(made[0].path), preview: previewName } });
      return answer(runtime, made[0], join(folder, previewName), { outputs: made.map(r => r.id), result: { ...result, outputs: undefined } });
    },
  });
  return [makeAsset, runSkillScript];
}

/** Any image the sandbox's Pillow reads (JPEG, WebP, a palette PNG) as an RGBA PNG: for a canvas reference's picture from
 * an image model that is not a plain PNG. The work files go from the chat's assets folder afterwards. */
export async function pngFromImage(runtime, data, signal) {
  const folder = await assetsFolder(runtime), stem = 'convert-' + randomUUID().slice(0, 8);
  await writeFile(join(folder, stem + '.img'), data);
  try {
    await runPython({ work: folder, signal, args: { input: stem + '.img', output: stem + '.png' },
      code: 'from PIL import Image\nImage.open("/work/" + ARGS["input"]).convert("RGBA").save("/work/" + ARGS["output"])\nRESULT = 1' });
    return await readFile(join(folder, stem + '.png'));
  } finally { await Promise.all([stem + '.img', stem + '.png'].map(name => rm(join(folder, name), { force: true }))); }
}

async function readImage(path) {
  const data = await readFile(path);
  return { data, mimeType: imageInfo(data).mimeType };
}
