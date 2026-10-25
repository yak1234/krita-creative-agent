// /canvas-reference in a chat (studio.mjs hooks; the module is tested in canvas-reference.test.mjs): the command never
// reaches the painter, the card waits, Use as the target sets the difference area on the painting and a move paints toward
// the reference there; Discard paints nothing; a plan's Add step can wait for a preview. A local model server, a fake bridge
// and a fake Codex image backend (no network), as paint-only-here-studio.test.mjs.
import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { StudioRuntime } from '../src/studio.mjs';
import { encodeRgba } from '../src/shapes/png.ts';
import { decodeRgba } from '../src/png-rgba.ts';
import { goalView } from '../src/goal-edit.ts';

const call = (name, args) => ({ tool_calls: [{ index: 0, id: 'call-' + Math.random().toString(36).slice(2), type: 'function', function: { name, arguments: JSON.stringify(args) } }] });
function picture(w, h, patch) {
  const data = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4, white = patch && x >= patch[0] && y >= patch[1] && x < patch[0] + patch[2] && y < patch[1] + patch[3];
    data.set(white ? [250, 250, 250, 255] : [40 + Math.round(120 * x / w), 60 + Math.round(80 * y / h), 120, 255], i);
  }
  return encodeRgba({ width: w, height: h, data });
}
const VIEW = picture(200, 150), EDITED = picture(200, 150, [100, 40, 40, 30]);
const claims = Buffer.from(JSON.stringify({ 'https://api.openai.com/auth': { chatgpt_account_id: 'acct-1' } })).toString('base64url');

async function harness(respond) {
  const output = await mkdtemp(join(tmpdir(), 'canvas-reference-studio-'));
  const requests = [], calls = [], events = [], images = [];
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const request = JSON.parse(body); requests.push(request);
    const delta = await respond(request, requests.length);
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
    calls.push({ operation, params });
    if (operation === 'context') return { document_id: 'doc', active_document_id: 'doc', name: 'Untitled', filename: '', width: 800, height: 600, modified: true, revision: 'revision-0' };
    if (['begin', 'peek'].includes(operation)) {
      const path = join(params.output_dir, 'view.png'); await writeFile(path, VIEW);
      observation = { status: 'ok', document_id: 'doc', name: 'Untitled', filename: '', modified: true, width: 800, height: 600, image_path: path, layers: [], revision: 'revision-0', content_id: 'content-0', captured_at: new Date().toISOString(),
        ...(operation === 'begin' ? { checkpoint: params.painting_path ?? join(params.output_dir, 'painting.kra') } : {}) };
      if (operation === 'begin') await writeFile(observation.checkpoint, 'test painting');
    }
    if (operation === 'paint_only_here') return { status: 'ok' };
    return operation === 'end' ? { status: 'ok' } : observation;
  } };
  const capabilities = { async initialize() {}, status() { return { status: 'verified', route_verified: true, images_supported: true, tools_supported: true }; }, async verify() { return { route_verified: true, cached: true }; }, async invalidate() {} };
  const runtime = new StudioRuntime({ defaultPlanner: null, root: output, config: { output }, models, bridge, capabilities, tracing: recordingTracing(), emit: e => events.push(e) });
  // The image backend: Codex, faked. It answers the canvas with the edited picture.
  runtime.codexKey = async () => 'eyJhbGciOiJub25lIn0.' + claims + '.sig';
  runtime.imageFetch = async (url, options) => {
    images.push({ url, body: JSON.parse(options.body) });
    const sse = 'data: ' + JSON.stringify({ type: 'response.output_item.done', item: { type: 'image_generation_call', result: EDITED.toString('base64') } }) + '\n';
    return { ok: true, status: 200, text: async () => sse };
  };
  return { runtime, requests, calls, events, images, output,
    async close() { if (runtime.busy) runtime.stop(); await runtime.writeQueue; await runtime.end().catch(() => {}); runtime.dispose(); server.closeAllConnections(); await new Promise(r => server.close(r)); await rm(output, { recursive: true, force: true }); } };
}
async function agentChat(respond) {
  const painted = [];
  const h = await harness(req => {
    if (!req.tools.some(t => t.function.name === 'paint_batch')) return { content: 'Hello.' };
    painted.push(req);
    return respond(req, painted.length);
  });
  const goal = join(h.output, 'final_goal.png'); await writeFile(goal, VIEW);
  await h.runtime.start({ provider: 'local-test', model: 'vision-test', chat_mode: 'ask', prompt: 'Hello', mode: 'copy', references: [{ path: goal, purpose: 'general' }] });
  await h.runtime.setExecutionSettings({ move_size: 'quick' }); await h.runtime.setMode('agent');
  await h.runtime.setLimits({ minutes: 0, passes: 0, ai_images: 3 });
  return { h, painted };
}
const cards = h => h.events.filter(e => e.type === 'canvas_reference');

test('/canvas-reference makes the card and paints nothing; Use as the target paints toward it inside the difference area', { timeout: 60000 }, async () => {
  const { h, painted } = await agentChat((req, n) => n === 1 ? call('finish_move', { summary: 'Painted the ghosts.' }) : { content: 'Done.' });
  try {
    await h.runtime.prompt('/canvas-reference add more ghosts and ghost-like lighting');
    assert.equal(painted.length, 0, 'the painter never read the command');
    assert.equal(h.images.length, 1, 'one picture from the image backend');
    assert.equal(h.images[0].url, 'https://chatgpt.com/backend-api/codex/responses', 'Codex by default');
    assert.match(h.images[0].body.input[0].content[0].text, /add more ghosts and ghost-like lighting.*Keep everything else exactly/s);
    assert.match(h.images[0].body.input[0].content[1].image_url, /^data:image\/png;base64,/, 'the canvas goes with it');
    assert.equal(h.runtime.goal.ai_images_used, 1);
    assert.ok(h.runtime.goal.messages.some(m => m.role === 'user' && m.text === '/canvas-reference add more ghosts and ghost-like lighting'), 'the transcript keeps what was typed');
    const [card] = cards(h);
    assert.deepEqual(card.options, ['Use as the target', 'Use as the new goal', 'Try again', 'Discard'], 'the chat has a goal picture');
    assert.equal(card.auto_approve, false); assert.match(card.message, /ChatGPT/);
    assert.ok(!h.calls.some(c => c.operation === 'paint_only_here'), 'nothing set on the painting yet');

    await h.runtime.canvasReference.answer({ id: card.id, action: 'use' });
    const set = h.calls.find(c => c.operation === 'paint_only_here' && c.params.action === 'set');
    assert.ok(set, 'the difference area is protected on the painting');
    const [x, y, w] = set.params.bounds;
    assert.ok(x <= 400 && y <= 160 && w < 300, 'the change, at canvas size: ' + set.params.bounds);
    const asset = h.runtime.study.references.find(r => r.role === 'asset' && r.source?.canvas_reference === card.id);
    assert.ok(asset, 'the reference is a reference asset of the chat');
    assert.equal(asset.width / asset.height, 800 / 600);
    assert.equal(painted.length >= 1, true, 'a move painted');
    const sent = JSON.stringify(painted[0].messages);
    assert.match(sent, /CANVAS REFERENCE: the artist approved/); assert.match(sent, new RegExp(asset.id)); assert.match(sent, /target \[0,0,800,600\]/);
    assert.match(sent, /Painting only inside your selection/, 'the area is the painter\'s context');
    assert.equal(h.runtime.goal.paint_only_here.canvas_reference, card.id);
    assert.equal(h.runtime.goal.moves.at(-1).kind, 'canvas_reference');
    assert.equal(h.runtime.goal.moves.at(-1).canvas_reference, card.id, 'the move knows its reference: only it is measured against it');
    await h.runtime.prompt('Kept. Continue my request with the next move.', { chat_mode: 'agent', move_kind: 'continue' });
    assert.equal(h.runtime.goal.moves.at(-1).canvas_reference, card.id, 'a Keep that continues it paints toward the same reference');
    // The next message ends the area: it belonged to that move.
    await h.runtime.prompt('/canvas-reference more snow');
    assert.equal(h.runtime.goal.paint_only_here, null);
    assert.ok(h.calls.some(c => c.operation === 'paint_only_here' && c.params.action === 'clear'));
  } finally { await h.close(); }
});

test('Discard paints nothing and drops the picture', { timeout: 60000 }, async () => {
  const { h, painted } = await agentChat(() => ({ content: 'Done.' }));
  try {
    await h.runtime.prompt('/canvas-reference more snow and crisp effects in the sky');
    const [card] = cards(h);
    assert.match(card.message, /The sky was not found/, 'no shapes model here: the whole canvas is compared');
    await h.runtime.canvasReference.answer({ id: card.id, action: 'discard' });
    assert.equal(painted.length, 0); assert.ok(!existsSync(card.image_path));
    assert.ok(!h.calls.some(c => c.operation === 'paint_only_here'));
  } finally { await h.close(); }
});

test('with AI images off the command says so and sends nothing', { timeout: 60000 }, async () => {
  const { h } = await agentChat(() => ({ content: 'Done.' }));
  try {
    await h.runtime.setLimits({ minutes: 0, passes: 0, ai_images: 0 });
    await assert.rejects(h.runtime.prompt('/canvas-reference more snow'), /AI images are off/);
    assert.equal(h.images.length, 0);
  } finally { await h.close(); }
});

test('Preview additions: a plan\'s Add step waits for a canvas reference, then paints toward it inside its area', { timeout: 60000 }, async () => {
  const { h, painted } = await agentChat((req, n) => n === 1 ? call('finish_move', { summary: 'Painted the snow.' }) : { content: 'Done.' });
  try {
    await h.runtime.setExecutionSettings({ move_size: 'quick', preview_additions: true });
    const goal = h.runtime.goal;
    goal.single_plan = { request: 'add snow on the roofs', additions: ['snow on the roofs'], parts: [] };
    goal.brief = { title: 'Snow', objective: 'o', requirements: [], freedom: [], completion: ['c'],
      steps: [{ title: 'Add: snow on the roofs', done_when: 'Snow lies on every roof.', scope: 'the whole picture', kind: 'addition' }] };
    goal.revision = (goal.revision ?? 0) + 1; goal.approved_revision = goal.revision; goal.current_step = 0; goal.status = 'ready';
    await h.runtime.prompt('', { start_plan: true });
    assert.equal(painted.length, 0, 'the step waits for the card');
    const [card] = cards(h);
    assert.match(h.images[0].body.input[0].content[0].text, /add snow on the roofs/);
    assert.match(card.message, /plan step waits/);
    await h.runtime.canvasReference.answer({ id: card.id, action: 'use' });
    assert.ok(painted.length >= 1, 'the step painted');
    const sent = JSON.stringify(painted[0].messages);
    assert.match(sent, /PLAN MOVE/); assert.match(sent, /CANVAS REFERENCE: the artist approved/);
    assert.ok(h.calls.some(c => c.operation === 'paint_only_here' && c.params.action === 'set'));
  } finally { await h.close(); }
});

test('Preview additions: Discard paints the Add step without a reference; the step is previewed once', { timeout: 60000 }, async () => {
  const { h, painted } = await agentChat((req, n) => n === 1 ? call('finish_move', { summary: 'Painted the snow.' }) : { content: 'Done.' });
  try {
    await h.runtime.setExecutionSettings({ move_size: 'quick', preview_additions: true });
    const goal = h.runtime.goal;
    goal.single_plan = { request: 'add snow on the roofs', additions: ['snow on the roofs'], parts: [] };
    goal.brief = { title: 'Snow', objective: 'o', requirements: [], freedom: [], completion: ['c'],
      steps: [{ title: 'Add: snow on the roofs', done_when: 'Snow lies on every roof.', scope: 'the whole picture', kind: 'addition' }] };
    goal.revision = (goal.revision ?? 0) + 1; goal.approved_revision = goal.revision; goal.current_step = 0; goal.status = 'ready';
    await h.runtime.prompt('', { start_plan: true });
    await h.runtime.canvasReference.answer({ id: cards(h)[0].id, action: 'discard' });
    assert.ok(painted.length >= 1, 'the step painted without the reference');
    assert.doesNotMatch(JSON.stringify(painted[0].messages), /CANVAS REFERENCE: the artist approved/);
    assert.ok(!h.calls.some(c => c.operation === 'paint_only_here'));
    assert.equal(h.images.length, 1, 'previewed once');
  } finally { await h.close(); }
});

test('Use as the new goal pastes the change into the goal picture, paints toward it, and /original-goal goes back', { timeout: 60000 }, async () => {
  const { h, painted } = await agentChat((req, n) => n === 1 ? call('finish_move', { summary: 'Painted the ghosts.' }) : { content: 'Done.' });
  try {
    const goal = h.runtime.study.references.find(r => r.purpose === 'general'), started = goal.path;
    await h.runtime.prompt('/canvas-reference add more ghosts and ghost-like lighting');
    const [card] = cards(h);
    await h.runtime.canvasReference.answer({ id: card.id, action: 'goal' });
    assert.notEqual(goal.path, started); assert.match(goal.path, /goal-edits/);
    assert.equal(goal.id, h.runtime.study.references.find(r => r.purpose === 'general').id, 'the same goal, its picture changed');
    const before = decodeRgba(await readFile(started)), after = decodeRgba(await readFile(goal.path));
    assert.deepEqual([after.width, after.height], [200, 150], 'the goal\'s own size');
    const px = (img, x, y) => [...img.data.subarray((y * img.width + x) * 4, (y * img.width + x) * 4 + 3)];
    // The change, white on the reference at [100, 40, 40, 30] of 200 x 150, lands at the same place on the goal.
    assert.deepEqual(px(after, 120, 55), [250, 250, 250], 'inside the change: the reference');
    assert.deepEqual(px(after, 20, 120), px(before, 20, 120), 'far from it: the goal untouched');
    assert.ok(painted.length >= 1, 'the move paints toward it, as Use does');
    assert.ok(h.events.some(e => e.type === 'action' && /goal picture now includes this change/.test(e.message)));
    const moved = painted.length;
    await h.runtime.prompt('/original-goal');
    assert.equal(goal.path, started, 'back to the picture the chat started from');
    assert.ok(h.events.some(e => e.type === 'action' && /original goal picture again/.test(e.message)));
    await h.runtime.prompt('/original-goal');
    assert.ok(h.events.some(e => e.type === 'action' && /never changed/.test(e.message)));
    assert.equal(painted.length, moved, '/original-goal never reaches the painter');
  } finally { await h.close(); }
});

test('a sharpened goal: the edit goes into both pictures, the painter is shown it, Sharpen is told, and /original-goal restores the sharpening', { timeout: 60000 }, async () => {
  const { h } = await agentChat((req, n) => n === 1 ? call('finish_move', { summary: 'Painted the ghosts.' }) : { content: 'Done.' });
  try {
    const goal = h.runtime.study.references.find(r => r.purpose === 'general');
    // As goal-sharpen.ts use() leaves it: the reference is the bigger picture, the one it was is remembered.
    const big = join(h.output, 'sharpened.png'); await writeFile(big, picture(400, 300));
    const sharpened = { from: { path: goal.path, width: 200, height: 150, sha256: 'a'.repeat(64) }, model: 'm', revision: 'r', scale: 2, full: big, at: 't' };
    Object.assign(goal, { path: big, width: 400, height: 300, sharpened });
    let told = 0; const changed = h.runtime.goalSharpen.goalChanged; h.runtime.goalSharpen.goalChanged = () => { told++; changed(); };
    await h.runtime.prompt('/canvas-reference add more ghosts and ghost-like lighting');
    await h.runtime.canvasReference.answer({ id: cards(h)[0].id, action: 'goal' });
    const px = (img, x, y) => [...img.data.subarray((y * img.width + x) * 4, (y * img.width + x) * 4 + 3)];
    const edited = decodeRgba(await readFile(goal.path)), view = decodeRgba(await readFile(goal.view_path));
    assert.deepEqual([edited.width, edited.height, view.width, view.height], [400, 300, 200, 150]);
    assert.deepEqual(px(edited, 240, 110), [250, 250, 250], 'the change in the sharpened picture');
    assert.deepEqual(px(view, 120, 55), [250, 250, 250], 'and in the picture the painter is shown');
    assert.equal(goalView(goal), goal.view_path);
    assert.equal(goal.sharpened, sharpened, 'transfers begun before sharpening still map');
    assert.equal(told, 1, 'Sharpen is told: nothing for the old picture lands on the new one');
    await h.runtime.prompt('/original-goal');
    assert.deepEqual([goal.path, goal.width, goal.sharpened, goal.view_path], [big, 400, sharpened, undefined]);
    assert.equal(told, 2);
  } finally { await h.close(); }
});
