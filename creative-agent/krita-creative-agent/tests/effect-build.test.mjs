// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A custom effect build (effects/build.ts, openspec custom-effects goals 5-6): candidates from a worker, each previewed on
// the canvas view (effect_preview), chosen blind by Luna (or by their change when Luna cannot), a card the artist answers;
// the last resort is one AI texture. The module runs with a fake host (real files in a temp folder, a fake plugin that
// tints the view per block); the studio test at the end runs it in a chat (a local model server as the worker, a fake
// bridge and Luna) and checks that nothing waits for the card. Every test removes its folder.
import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { effectBuilder, workerBrief } from '../src/effects/build.ts';
import { effectTools } from '../src/effects/effect-tool.ts';
import { DEFAULT_POLICY } from '../src/effects/policy.ts';
import { loadEffects } from '../src/effects/library.ts';
import { parseRecipe } from '../src/effects/recipe.ts';
import { encodeRgba } from '../src/shapes/png.ts';
import { decodeRgba } from '../src/png-rgba.ts';
import { panelCommand } from '../src/test-commands.ts';

const W = 240, H = 160;
function picture(w, h, lift = 0) {
  const data = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++)
    data.set([Math.min(255, 40 + Math.round(100 * x / w) + lift), Math.min(255, 50 + Math.round(60 * y / h) + lift), Math.min(255, 90 + lift), 255], (y * w + x) * 4);
  return { width: w, height: h, data };
}
const VIEW = encodeRgba(picture(W, H));
/** How much each block lifts the preview (the fake plugin): particles most, so they change the canvas most. */
const LIFT = { particles: 80, wash: 30, noise: 10, texture: 50, caps: 20, rays: 40 };
const recipe = (cue, block, extra = '') => `name: rain\ncue: ${cue}\nlesson: ${cue} - the candidate's own lesson.\n${extra}blocks:\n  - { block: ${block}, opacity: 0.6 }\n`;
const RAIN_A = recipe('rain streaks falling', 'particles');
const RAIN_B = recipe('rain as a grey wash', 'wash');
const RAIN_C = recipe('rain as a drizzle haze', 'noise');
const BAD = recipe('rain with lightning', 'lightning');

async function setup({ written = () => [RAIN_A, BAD, RAIN_C], fixed = () => [RAIN_B], luna = null, ai = false, auto = null, own = true, painted = () => 500, retryStarts = true } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'effect-build-'));
  const study = { id: 'chat-1', directory: join(dir, 'chat') };
  await mkdir(study.directory, { recursive: true });
  const viewPath = join(study.directory, 'view.png');
  await writeFile(viewPath, VIEW);
  const folder = join(dir, 'data', 'effects');
  const calls = { write: [], preview: [], luna: [], generate: [], found: [] }, events = [], discarded = [], retried = [];
  let now = 1_000_000;
  const host = {
    study, now: () => now, policy: () => ({ ...DEFAULT_POLICY }),
    observe: async () => ({ image_path: viewPath, width: 6000, height: 4000 }),
    decode: async data => decodeRgba(data),
    write: async request => { calls.write.push(request); return request.fix ? fixed(request) : written(request); },
    preview: async params => {
      calls.preview.push(params);
      const base = decodeRgba(await readFile(params.image_path)), lift = params.blocks.reduce((sum, b) => sum + (LIFT[b.block] ?? 0), 0);
      const out = new Uint8Array(base.data);
      for (let i = 0; i < out.length; i += 4) for (let c = 0; c < 3; c++) out[i + c] = Math.min(255, out[i + c] + lift);
      await writeFile(params.out_path, encodeRgba({ width: base.width, height: base.height, data: out }));
      return { status: 'ok', report: { blocks: params.blocks.map(b => ({ block: b.block, painted: painted(b) })) } };
    },
    findPart: async name => { calls.found.push(name); return ['faces', 'hair', 'the street'].includes(name) ? { mask_path: join(study.directory, '.shapes', name.replace(/\W/g, '') + '.png'), bounds: [0, 0, 10, 10] } : null; },
    luna: async () => luna && { decide: async request => { calls.luna.push(request); return luna(request); } },
    allowance: () => { if (!ai) throw new Error('AI images are off for this chat (allowance 0).'); },
    generate: async request => { calls.generate.push(request); return { data: encodeRgba(picture(64, 64, 120)), model: 'test-image' }; },
    ownFolder: () => own ? folder : '',
    autoKeepSeconds: () => auto,
    emit: event => events.push(event),
    discarded: effect => discarded.push(effect),
    retry: (effect, request) => { retried.push({ effect, request }); return retryStarts; },
  };
  const builder = effectBuilder(host);
  return { host, builder, calls, events, discarded, retried, folder, study, advance: ms => { now += ms; },
    cards: () => events.filter(e => e.type === 'effect_build'), said: () => events.filter(e => e.type === 'action').map(e => e.message),
    close: () => rm(dir, { recursive: true, force: true }) };
}
const choosing = letter => request => ({ answers: { [Object.keys(request.questions)[0]]: { type: 'choice', choice: letter, confidence: 0.8 } },
  model: 'luna', elapsed_ms: 1, usage: { input_tokens: 1, output_tokens: 1, cost: 0 } });

test('three candidates, an invalid one retried once, Luna chooses blind', async () => {
  const h = await setup({ luna: choosing('B') });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    assert.equal(h.calls.write.length, 2, 'the candidates, then one retry');
    assert.equal(h.calls.write[0].count, 3);
    assert.equal(h.calls.write[0].name, 'rain');
    assert.equal(h.calls.write[1].fix.length, 1, 'only the invalid one is retried');
    assert.match(h.calls.write[1].fix[0].error, /blocks\[0\]\.block/, 'with the field named');
    assert.equal(h.calls.write[1].fix[0].yaml, BAD.trim(), 'the refused text as written');
    assert.equal(h.calls.preview.length, 3, 'three previews: two first, the fixed one after');
    for (const p of h.calls.preview) {
      assert.ok(p.image_path.startsWith(h.study.directory) && p.out_path.startsWith(h.study.directory), 'files in the chat folder');
      assert.deepEqual(p.canvas, [6000, 4000]);
      assert.equal(p.keep_clear.length, 2, 'faces and hair kept clear');
    }
    const small = decodeRgba(await readFile(h.calls.preview[0].image_path));
    assert.ok(Math.max(small.width, small.height) <= DEFAULT_POLICY.preview_side, 'the canvas view at most preview_side');
    assert.equal(h.calls.found.filter(n => n === 'faces').length, 1, 'Find it once a part, a build');
    // Luna: the request and three pictures labelled A, B, C; never a recipe.
    assert.equal(h.calls.luna.length, 1, 'one Luna choice');
    const [asked] = h.calls.luna, texts = asked.parts.filter(p => typeof p === 'string'), images = asked.parts.filter(p => p && typeof p === 'object');
    assert.equal(images.length, 3);
    assert.deepEqual(texts.filter(t => /^[ABC]:$/.test(t)), ['A:', 'B:', 'C:']);
    assert.ok(texts.some(t => t.includes('Add rain over the street')), 'the request');
    for (const t of [...texts, JSON.stringify(asked.questions)]) assert.doesNotMatch(t, /block|particles|wash|noise|opacity|lesson|cue:/, 'no recipe text');
    assert.equal(record.chosen, 'B');
    assert.equal(record.state, 'ready');
    assert.deepEqual(record.candidates, [RAIN_A, RAIN_B, RAIN_C].map(t => t.trim()), 'the survivors, the fixed one in its place');
    assert.equal(record.recipe.blocks[0].block, 'wash', 'B: the fixed candidate');
  } finally { await h.close(); }
});

test('an invalid candidate is retried only once, then dropped; Luna off chooses by the change and says so', async () => {
  const h = await setup({ fixed: () => [BAD], painted: b => b.block === 'noise' ? 0 : 500 });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    assert.equal(h.calls.write.length, 2, 'one retry, never two');
    assert.equal(h.calls.write[1].fix.length, 2, 'the bad recipe and the one that painted nothing');
    assert.match(h.calls.write[1].fix.find(f => f.yaml === RAIN_C.trim()).error, /painted nothing/);
    assert.deepEqual(record.candidates, [RAIN_A.trim()], 'one survivor');
    assert.equal(record.chosen, 'A');
    assert.match(h.cards()[0].message, /Decision checks are off/);
  } finally { await h.close(); }
});

test('the card shows the canvas and the chosen effect', async () => {
  const h = await setup({ luna: () => ({ fallback: 'timeout', elapsed_ms: 4000 }), written: () => [RAIN_B, RAIN_A, RAIN_C], auto: 30 });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    assert.equal(record.chosen, 'B', 'Luna could not answer: the most change within reason (particles)');
    const [card] = h.cards();
    assert.equal(card.id, record.id);
    assert.equal(card.title, 'Custom effect');
    assert.deepEqual(card.options, ['Keep', 'Try again', 'Discard']);
    assert.deepEqual(card.actions, ['keep', 'retry', 'discard']);
    assert.equal(card.auto_keep_seconds, 30);
    assert.match(card.message, /Luna could not answer/);
    assert.match(card.message, /B of 3/);
    const compare = decodeRgba(await readFile(card.image_path));
    assert.ok(card.image_path.startsWith(h.study.directory));
    const canvas = decodeRgba(await readFile(h.calls.preview[0].image_path));
    const w = Math.round((compare.width - 8) / 2);
    const at = (img, x, y) => [...img.data.slice((y * img.width + x) * 4, (y * img.width + x) * 4 + 3)];
    const y = Math.floor(compare.height / 2), x = Math.floor(w / 2), sx = Math.floor(x * canvas.width / w), sy = Math.floor(y * canvas.height / compare.height);
    const left = at(compare, x, y), right = at(compare, w + 8 + x, y), base = at(canvas, sx, sy);
    for (let c = 0; c < 3; c++) {
      assert.ok(Math.abs(left[c] - base[c]) <= 3, 'the canvas on the left');
      assert.ok(Math.abs(right[c] - Math.min(255, base[c] + LIFT.particles)) <= 3, 'the chosen effect on the right');
    }
  } finally { await h.close(); }
  for (const [auto, seconds] of [[10, 20], [null, null]]) {
    const g = await setup({ auto: auto === null ? null : Math.max(auto, DEFAULT_POLICY.auto_keep_min_seconds) });
    try { await g.builder.start('rain', 'rain'); assert.equal(g.cards()[0].auto_keep_seconds, seconds); } finally { await g.close(); }
  }
});

test('a build runs with the host and chat it started in; stopped by its chat, it shows no card and says nothing', async () => {
  // The run's own host (the studio binds it to the chat the build started in) is used throughout, not the builder's.
  const h = await setup({ luna: choosing('A') });
  try {
    const run = new AbortController(), shown = [];
    const own = { ...h.host, emit: event => shown.push(event), write: async request => { h.calls.write.push(request); run.abort(); return [RAIN_A]; } };
    const record = await h.builder.start('rain', 'Add rain over the street', { host: own, signal: run.signal });
    assert.equal(record, null, 'stopped: nothing was built');
    assert.equal(h.calls.preview.length, 0, 'nothing previewed after the stop');
    assert.deepEqual(shown.filter(e => e.type === 'effect_build'), [], 'no card');
    assert.deepEqual(shown.filter(e => e.type === 'action').map(e => e.message), ['Building a new effect: rain. Painting carries on.'], 'no failure message for a chat that ended');
    assert.deepEqual(h.events, [], 'the builder\'s own host heard nothing');
  } finally { await h.close(); }
  // A card from another chat is not answered in this one.
  const g = await setup({ luna: choosing('A') });
  try {
    const record = await g.builder.start('rain', 'Add rain over the street');
    g.host.study = { id: 'chat-2', directory: g.study.directory + '-2' };
    await g.builder.answer({ id: record.id, action: 'keep' });
    assert.match(g.said().at(-1), /no longer open/);
    assert.equal(record.state, 'ready');
    assert.equal(existsSync(join(g.folder, 'rain.yaml')), false);
  } finally { await g.close(); }
});

test('Keep and Remove change only the library', async () => {
  const h = await setup({ luna: choosing('A') });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    const native = h.calls.preview.length + h.calls.generate.length;
    await h.builder.answer({ id: record.id, action: 'keep', auto: true });
    assert.equal(h.calls.preview.length + h.calls.generate.length, native, 'Keep calls nothing native');
    const { effects } = await loadEffects({ bundled: join(h.folder, 'none'), own: h.folder });
    const kept = effects.get('rain');
    assert.ok(kept, 'usable at once: the library reads it');
    assert.equal(kept.cue, 'rain streaks falling');
    assert.equal(kept.lesson, "rain streaks falling - the candidate's own lesson.");
    assert.match(kept.evidence, /^chat chat-1, \d{4}-\d{2}-\d{2}, chosen A of 3$/);
    assert.equal(kept.auto_kept, true, 'pressed by Auto-approve');
    assert.equal(record.state, 'kept');
    const after = h.cards().at(-1);
    assert.deepEqual(after.actions, ['remove']);
    assert.deepEqual(after.options, ['Remove effect']);
    assert.equal(after.auto_keep_seconds, null);
    await h.builder.answer({ id: record.id, action: 'keep' });
    assert.match(h.said().at(-1), /no longer open/, 'Keep twice: refused');
    await h.builder.answer({ id: record.id, action: 'remove' });
    assert.equal(existsSync(join(h.folder, 'rain.yaml')), false, 'removed from the library');
    assert.equal(record.state, 'removed');
    assert.equal(h.calls.preview.length + h.calls.generate.length, native, 'Remove calls nothing native');
    assert.deepEqual(h.discarded, []);
  } finally { await h.close(); }
  // Remove says so when nothing was removed: the effect was gone already, or there is no folder for the artist's effects.
  const r = await setup({ luna: choosing('A') });
  try {
    const record = await r.builder.start('rain', 'Add rain over the street');
    await r.builder.answer({ id: record.id, action: 'keep' });
    await rm(join(r.folder, 'rain.yaml'));
    await r.builder.answer({ id: record.id, action: 'remove' });
    assert.match(r.said().at(-1), /“rain” was not in your effects.*nothing was removed/);
    assert.notEqual(record.state, 'removed');
    r.host.ownFolder = () => '';
    await r.builder.answer({ id: record.id, action: 'remove' });
    assert.match(r.said().at(-1), /no folder for your effects.*nothing was removed/);
    assert.doesNotMatch(r.said().join('\n'), /Removed “rain”/);
  } finally { await r.close(); }
  // Discard: the chat's failures hear it; Try again: a new build of the same effect.
  const g = await setup({ luna: choosing('A') });
  try {
    const one = await g.builder.start('rain', 'Add rain');
    await g.builder.answer({ id: one.id, action: 'retry' });
    assert.deepEqual(g.retried, [{ effect: 'rain', request: 'Add rain' }]);
    assert.equal(one.state, 'discarded');
    const two = await g.builder.start('rain', 'Add rain');
    await g.builder.answer({ id: two.id, action: 'discard' });
    assert.deepEqual(g.discarded, ['rain']);
    await g.builder.answer({ id: two.id, action: 'remove' });
    assert.match(g.said().at(-1), /no longer open/);
    assert.equal(existsSync(g.folder), false, 'nothing was written');
  } finally { await g.close(); }
});

test('with no candidate left and AI images allowed, one texture recipe', async () => {
  const h = await setup({ written: () => [BAD, BAD], fixed: () => [BAD, BAD], ai: true, luna: choosing('A') });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    assert.equal(h.calls.generate.length, 1, 'one AI texture');
    const { prompt } = h.calls.generate[0];
    assert.match(prompt, /Add rain over the street/);
    assert.match(prompt, /the street/, 'the area');
    assert.match(prompt, /light/, 'the scene light');
    assert.match(prompt, /transparent/);
    assert.equal(record.recipe.blocks.length, 1);
    const [block] = record.recipe.blocks;
    assert.equal(block.block, 'texture');
    assert.equal(block.area, 'the street');
    assert.ok(block.image_path.startsWith(h.study.directory) && existsSync(block.image_path), 'the texture in the chat folder');
    assert.equal(h.calls.preview.at(-1).blocks[0].image_path, block.image_path, 'previewed like any candidate');
    const [card] = h.cards();
    assert.deepEqual(card.actions, ['keep', 'retry', 'discard']);
    assert.match(card.message, /AI texture/);
    await h.builder.answer({ id: record.id, action: 'keep' });
    const saved = parseRecipe(await readFile(join(h.folder, 'rain.yaml'), 'utf8'), 'rain.yaml');
    assert.ok(!('error' in saved));
    assert.equal(saved.recipe.blocks[0].image_path, 'rain.texture.png', 'the texture named beside the recipe');
    assert.ok(existsSync(join(h.folder, 'rain.texture.png')), 'copied into the artist\'s folder');
    // A later chat: paint_effect copies the texture into that chat's folder and paints with that copy.
    const later = join(h.study.directory, '..', 'later-chat'), effects = [];
    await mkdir(later, { recursive: true });
    const [tool] = effectTools({ emit: () => {}, async callNative() { return { width: 6000, height: 4000 }; } }, {
      effect: async (_id, params) => { effects.push(params); return { content: [], details: { report: { blocks: params.blocks.map(b => ({ block: b.block, painted: 10 })) } } }; },
      findPart: async name => ({ mask_path: join(later, '.shapes', name.replace(/\W/g, '') + '.png'), bounds: [0, 0, 10, 10] }),
      library: () => loadEffects({ bundled: join(h.folder, 'none'), own: h.folder }),
      textureInto: async source => { const target = join(later, 'effect-textures', 'copy.png'); await mkdir(join(later, 'effect-textures'), { recursive: true }); await writeFile(target, await readFile(source)); return target; } });
    await tool.execute('m1', { effect: 'rain' });
    const painted = effects[0].blocks[0].image_path;
    assert.ok(painted.startsWith(later) && existsSync(painted), 'the native effect gets a texture in the later chat\'s folder');
    // Remove takes the texture too.
    await h.builder.answer({ id: record.id, action: 'remove' });
    assert.equal(existsSync(join(h.folder, 'rain.texture.png')), false);
    assert.equal(existsSync(join(h.folder, 'rain.yaml')), false);
  } finally { await h.close(); }
});

test('Try again while another build runs keeps the card', async () => {
  const h = await setup({ luna: choosing('A'), retryStarts: false });
  try {
    const record = await h.builder.start('rain', 'Add rain');
    await h.builder.answer({ id: record.id, action: 'retry' });
    assert.equal(h.retried.length, 1);
    assert.equal(record.state, 'ready', 'not started: the card and its Keep stay');
    await h.builder.answer({ id: record.id, action: 'keep' });
    assert.equal(record.state, 'kept');
  } finally { await h.close(); }
});

test('a worker candidate that names a texture image is refused', async () => {
  const named = recipe('rain as an image', 'texture', '').replace('{ block: texture, opacity: 0.6 }', '{ block: texture, area: the street, image_path: /etc/passwd }');
  const h = await setup({ written: () => [named, RAIN_A], fixed: () => [named] });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    assert.match(h.calls.write[1].fix[0].error, /image_path/);
    assert.deepEqual(record.candidates, [RAIN_A.trim()]);
    assert.ok(h.calls.preview.every(p => p.blocks.every(b => b.block !== 'texture')), 'never previewed');
  } finally { await h.close(); }
});

test('with AI images off, the card says how to allow one', async () => {
  const h = await setup({ written: () => [BAD], fixed: () => [BAD] });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    assert.equal(h.calls.generate.length, 0);
    assert.equal(record.recipe, null);
    assert.equal(record.chosen, null);
    const [card] = h.cards();
    assert.match(card.message, /No effect was found/);
    assert.match(card.message, /AI images/);
    assert.match(card.message, /limits/);
    assert.deepEqual(card.actions, ['retry', 'discard'], 'nothing to keep');
    assert.equal(card.auto_keep_seconds, null);
  } finally { await h.close(); }
});

test('over 4 minutes the build ends and says so', async () => {
  let h;
  h = await setup({ written: () => { h.advance(5 * 60_000); return [RAIN_A, RAIN_B]; }, luna: choosing('A') });
  try {
    const record = await h.builder.start('rain', 'Add rain over the street');
    assert.equal(record, null);
    assert.equal(h.cards().length, 0, 'no card');
    assert.equal(h.calls.preview.length, 0, 'nothing more is rendered');
    assert.equal(h.calls.luna.length, 0);
    assert.match(h.said().at(-1), /4 minutes/);
    assert.match(h.said().at(-1), /\/new-effect rain/);
  } finally { await h.close(); }
});

test('the worker brief: the request quoted as data, the skill and the examples, YAML only', () => {
  const brief = workerBrief({ effect: 'rain', name: 'rain', request: 'Add rain "now"', view_path: '/x.png', count: 3 }, 'SKILL TEXT', [{ name: 'snow.yaml', text: 'name: snow' }]);
  assert.match(brief, /3 different/);
  assert.match(brief, /"Add rain \\"now\\""/);
  assert.match(brief, /SKILL TEXT/);
  assert.match(brief, /name: snow/);
  assert.match(brief, /submit_effect_candidates/);
  const fix = workerBrief({ effect: 'rain', name: 'rain', request: 'r', view_path: '/x.png', count: 1, fix: [{ yaml: 'name: x', error: 'blocks[0].block: bad' }] }, 'S', []);
  assert.match(fix, /blocks\[0\]\.block: bad/);
  assert.match(fix, /name: x/);
});

test('effect_build_answer presses the custom effect card buttons the card shows', () => {
  const view = extra => ({ testFolder: '/t', planSteps: [], question: null, closeupQuestion: null, foundAreas: [], folderElements: [], ...extra });
  const card = { id: 'b1', options: ['Keep', 'Try again', 'Discard'], actions: ['keep', 'retry', 'discard'], text: '' };
  assert.throws(() => panelCommand('effect_build_answer', { action: 'keep' }, view()), /no custom effect card/);
  assert.deepEqual(panelCommand('effect_build_answer', { action: 'keep' }, view({ effectBuild: card })).command, { type: 'effect_build', id: 'b1', action: 'keep' });
  assert.throws(() => panelCommand('effect_build_answer', { action: 'remove' }, view({ effectBuild: card })), /action is keep or retry or discard/);
});

// ----- in a chat ------------------------------------------------------------------------------------------------------

const call = (name, args) => ({ tool_calls: [{ index: 0, id: 'call-' + Math.random().toString(36).slice(2), type: 'function', function: { name, arguments: JSON.stringify(args) } }] });
async function until(condition, what, ms = 15000) {
  const deadline = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error('Timed out waiting for ' + what);
    await new Promise(r => setTimeout(r, 5));
  }
}

test('nothing waits for the card: a move runs while it is open, and Keep then adds the effect', { timeout: 60000 }, async () => {
  const { StudioRuntime } = await import('../src/studio.mjs');
  const { effectFolders } = await import('../src/tools.mjs');
  const output = await mkdtemp(join(tmpdir(), 'effect-build-studio-'));
  const events = [], workerRequests = [], lunaAsked = [], previews = [];
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const request = JSON.parse(body);
    let delta = { content: 'Hello.' };
    if (request.tools?.some(t => t.function.name === 'submit_effect_candidates')) {
      workerRequests.push(request);
      const submitted = request.messages.some(m => m.role === 'tool');
      delta = submitted ? { content: 'Submitted.' } : call('submit_effect_candidates', { candidates: [RAIN_A, RAIN_B] });
    } else if (request.tools?.some(t => t.function.name === 'paint_batch')) {
      const start = request.messages.findLastIndex(m => m.role === 'user' && JSON.stringify(m.content).includes('Artist:'));
      const called = request.messages.slice(start + 1).flatMap(m => m.tool_calls ?? []).length;
      delta = !called ? call('fill_region', { name: 'Sky', area: [{ shape: 'rectangle', bounds: [0, 0, 200, 100] }], color: '#506080' })
        : called === 1 ? call('finish_move', { summary: 'Painted the sky' }) : { content: 'Done.' };
    }
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const choice of [{ delta: { role: 'assistant', ...delta }, finish_reason: null }, { delta: {}, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }])
      res.write('data: ' + JSON.stringify({ id: 'reply', object: 'chat.completion.chunk', created: 1, model: 'vision-test', choices: [{ index: 0, ...choice }] }) + '\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const models = await ModelRuntime.create({ authPath: join(output, 'auth.json'), modelsPath: null, refreshOnCreate: false });
  models.registerProvider('local-test', { api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1`, models: [{ id: 'vision-test', name: 'Test', reasoning: false, input: ['text', 'image'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 4096 }] });
  await models.setRuntimeApiKey('local-test', 'test-only');
  let observation;
  const bridge = { async call(operation, params) {
    if (operation === 'context') return { document_id: 'doc', active_document_id: 'doc', name: 'Untitled', filename: '', width: 800, height: 600, modified: true, revision: 'revision-0' };
    if (operation === 'list_brushes') return { brushes: [{ name: 'Test brush' }] };
    if (operation === 'effect_preview') {
      previews.push(params);
      await writeFile(params.out_path, encodeRgba(picture(W, H, 60)));
      return { status: 'ok', report: { blocks: params.blocks.map(b => ({ block: b.block, painted: 900 })) }, out_path: params.out_path };
    }
    if (['begin', 'peek'].includes(operation)) {
      const path = join(params.output_dir, 'view.png'); await writeFile(path, VIEW);
      observation = { status: 'ok', document_id: 'doc', name: 'Untitled', filename: '', modified: true, width: 800, height: 600, image_path: path, layers: [], revision: 'revision-0', content_id: 'content-0', captured_at: new Date().toISOString(),
        ...(operation === 'begin' ? { checkpoint: params.painting_path ?? join(params.output_dir, 'painting.kra') } : {}) };
      if (operation === 'begin') await writeFile(observation.checkpoint, 'test painting');
    }
    return operation === 'end' ? { status: 'ok' } : observation;
  } };
  const capabilities = { async initialize() {}, status() { return { status: 'verified', route_verified: true, images_supported: true, tools_supported: true }; }, async verify() { return { route_verified: true, cached: true }; }, async invalidate() {} };
  const runtime = new StudioRuntime({ defaultPlanner: null, sharpenModel: { download: async () => { throw new Error('No model downloads in tests.'); }, service: { upscale: async () => { throw new Error('No sharpening in tests.'); } } },
    root: output, config: { output, data_dir: join(output, 'data') }, models, bridge, capabilities, tracing: recordingTracing(), emit: e => events.push(e) });
  try {
    const goal = join(output, 'final_goal.png'); await writeFile(goal, VIEW);
    await runtime.start({ provider: 'local-test', model: 'vision-test', chat_mode: 'ask', prompt: 'Hello', mode: 'copy', references: [{ path: goal, purpose: 'general' }] });
    await runtime.setExecutionSettings({ routing: 'evaluate', reference_first: false, custom_effects: true, auto_approve: 30 });
    await runtime.setMode('agent');
    runtime.proposeArea = async () => null;                     // Find it finds nothing here
    runtime.lunaClient = { connected: true, async decide(request) {
      if (request.purpose !== 'effect-choice') return { fallback: 'not_connected', elapsed_ms: 0 };
      lunaAsked.push(request);
      return choosing('B')(request);
    } };
    await runtime.prompt('/new-effect rain');
    await until(() => events.some(e => e.type === 'effect_build'), 'the card');
    const card = events.find(e => e.type === 'effect_build');
    assert.equal(workerRequests.length >= 1, true, 'a worker session wrote the candidates');
    const tools = workerRequests[0].tools.map(t => t.function.name);
    assert.deepEqual(tools, ['submit_effect_candidates'], 'the worker has one tool');
    assert.match(JSON.stringify(workerRequests[0].messages), /Block API|particles/, 'it was given the skill');
    assert.equal(previews.length, 2);
    assert.ok(previews.every(p => p.out_path.startsWith(runtime.study.directory)));
    assert.equal(lunaAsked.length, 1);
    assert.deepEqual(card.actions, ['keep', 'retry', 'discard']);
    assert.equal(card.auto_keep_seconds, 30);
    await until(() => runtime.effectLog().failures.building === null, 'the build to end');
    // The card is open: a move paints and ends anyway.
    const moves = runtime.goal.moves?.length ?? 0;
    await runtime.prompt('Paint the sky bluer');
    assert.equal(runtime.goal.moves.length, moves + 1, 'the move ran with the card open');
    assert.equal(runtime.goal.moves.at(-1).status, 'ready');
    assert.equal(runtime.effectBuild.record(card.id).state, 'ready', 'the card still waits');
    // Keep: the library, nothing native.
    const own = effectFolders(runtime).own;
    await runtime.effectBuild.answer({ id: card.id, action: 'keep' });
    assert.ok(existsSync(join(own, 'rain.yaml')));
    assert.ok((await loadEffects(effectFolders(runtime))).effects.has('rain'));
    assert.equal(previews.length, 2, 'Keep renders nothing');
  } finally {
    if (runtime.busy) runtime.stop(); await runtime.writeQueue; await runtime.end().catch(() => {}); runtime.dispose();
    server.closeAllConnections(); await new Promise(r => server.close(r)); await rm(output, { recursive: true, force: true });
  }
});
