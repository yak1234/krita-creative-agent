// Paint only here in a chat (studio.mjs hooks; the module is tested in paint-only-here.test.mjs): an area a message brings
// is the painter's context and survives resume; clear ends it; the flat-fill nudge stays quiet; ask_for_selection stops an
// Agent move with the question card. A local model server and a fake bridge, as studio.test.mjs.
import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { StudioRuntime } from '../src/studio.mjs';
import { encodePlane } from '../src/shapes/png.ts';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64');
const call = (name, args) => ({ tool_calls: [{ index: 0, id: 'call-' + Math.random().toString(36).slice(2), type: 'function', function: { name, arguments: JSON.stringify(args) } }] });

async function harness(respond) {
  const output = await mkdtemp(join(tmpdir(), 'paint-only-studio-'));
  const requests = [], calls = [], events = [];
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
    if (operation === 'context') return { document_id: 'doc', active_document_id: 'doc', name: 'Untitled', filename: '', width: 768, height: 1024, modified: true, revision: 'revision-0' };
    if (['begin', 'peek'].includes(operation)) {
      const path = join(params.output_dir, 'view.png'); await writeFile(path, png);
      observation = { status: 'ok', document_id: 'doc', name: 'Untitled', filename: '', modified: true, width: 768, height: 1024, image_path: path, layers: [], revision: 'revision-0', content_id: 'content-0', captured_at: new Date().toISOString(),
        ...(operation === 'begin' ? { checkpoint: params.painting_path ?? join(params.output_dir, 'painting.kra') } : {}) };
      if (operation === 'begin') await writeFile(observation.checkpoint, 'test painting');
    }
    return operation === 'end' ? { status: 'ok' } : observation;
  } };
  const capabilities = { async initialize() {}, status() { return { status: 'verified', route_verified: true, images_supported: true, tools_supported: true }; }, async verify() { return { route_verified: true, cached: true }; }, async invalidate() {} };
  const runtime = new StudioRuntime({ root: output, config: { output }, models, bridge, capabilities, tracing: recordingTracing(), emit: e => events.push(e) });
  return { runtime, requests, calls, events, output,
    async close() { if (runtime.busy) runtime.stop(); await runtime.writeQueue; await runtime.end().catch(() => {}); runtime.dispose(); server.closeAllConnections(); await new Promise(r => server.close(r)); await rm(output, { recursive: true, force: true }); } };
}
async function agentChat(respond) {
  const painted = [];
  const h = await harness((req, n) => {
    if (!req.tools.some(t => t.function.name === 'paint_batch')) return { content: 'Hello.' };
    painted.push(req);
    return respond(req, painted.length);
  });
  const goal = join(h.output, 'final_goal.png'); await writeFile(goal, png);
  await h.runtime.start({ provider: 'local-test', model: 'vision-test', chat_mode: 'ask', prompt: 'Hello', mode: 'copy', references: [{ path: goal, purpose: 'general' }] });
  await h.runtime.setExecutionSettings({ move_size: 'quick' }); await h.runtime.setMode('agent');
  return { h, painted };
}
async function skyMask(h) {
  const path = join(h.output, 'panel-mask.png'), data = new Uint8Array(768 * 300).fill(255);
  await writeFile(path, encodePlane({ width: 768, height: 300, data }));
  return { action: 'set', mask_path: path, bounds: [0, 0, 768, 300], canvas: [768, 1024], name: 'the sky' };
}
const flatFill = { name: 'Sky', area: [{ shape: 'rectangle', bounds: [0, 0, 768, 300] }], color: '#506080' };

test('an area a message brings is the painter\'s context, quiets the fill nudge, survives resume and ends with clear', { timeout: 30000 }, async () => {
  const { h, painted } = await agentChat((req, n) => n === 1 ? call('fill_region', flatFill) : { content: 'Done.' });
  try {
    await h.runtime.prompt('Paint the sky', { paint_only_here: await skyMask(h) });
    const sent = JSON.stringify(painted[0].messages);
    assert.match(sent, /paint_only_here/); assert.match(sent, /Painting only inside your selection: the sky/);
    assert.match(sent, /0,0,768,300|0, 0, 768, 300/);
    assert.ok(painted[0].tools.some(t => t.function.name === 'ask_for_selection'), 'offered in an Agent move');
    assert.match(JSON.stringify(painted[0].messages[0]), /call ask_for_selection instead of guessing/);
    assert.equal(h.calls.filter(c => c.operation === 'fill_region').length, 1, 'the first fill ran: no nudge toward a whole transfer');
    assert.ok(h.events.some(e => e.type === 'action' && e.message === 'Painting only inside your selection: the sky'));
    assert.equal(h.events.filter(e => e.type === 'goal').at(-1).goal.paint_only_here.name, 'the sky', 'the panel hears it with the goal');
    const id = h.runtime.study.id;
    await h.runtime.end(); await h.runtime.resume(id);
    assert.equal(h.runtime.goal.paint_only_here.name, 'the sky', 'the area survives resume');
    await h.runtime.setPaintOnlyHere({ action: 'clear' });
    assert.equal(h.runtime.goal.paint_only_here, null);
    assert.equal(h.events.filter(e => e.type === 'goal').at(-1).goal.paint_only_here, null);
  } finally { await h.close(); }
});

test('ask_for_selection stops an Agent move with the question card the panel shows', { timeout: 30000 }, async () => {
  const { h, painted } = await agentChat((req, n) => n === 1 ? call('ask_for_selection', { part: 'the sky' }) : { content: 'Select the sky, please.' });
  try {
    await h.runtime.prompt('Paint the sky');
    const question = h.events.filter(e => e.type === 'question').at(-1);
    assert.deepEqual(question.select_area, { part: 'the sky', request: 'Paint the sky' }, 'no shapes model here: no proposal');
    assert.deepEqual(question.options, ['Find it for me', 'Select with Freehand', 'Use my selection', 'Paint everywhere']);
    assert.equal(h.runtime.goal.status, 'needs_input');
    assert.ok(painted.length <= 2, 'the move stopped for the answer');
    // The artist's answer brings the area with it.
    await h.runtime.prompt('Use my selection', { paint_only_here: await skyMask(h) });
    assert.equal(h.runtime.goal.paint_only_here.name, 'the sky');
    assert.equal(h.runtime.goal.question, null);
  } finally { await h.close(); }
});

test('after a kept whole underpainting the typed-stroke cap holds, while a scoped transfer is no whole one and is not capped', { timeout: 30000 }, async () => {
  const { h } = await agentChat(() => ({ content: 'Done.' }));
  try {
    const { mkdir } = await import('node:fs/promises');
    const folder = join(h.runtime.study.directory, 'reference-paintings'); await mkdir(folder, { recursive: true });
    const job = (id, extra) => writeFile(join(folder, id + '.json'), JSON.stringify({ id, recipe: { name: 'Goal', target: [0, 0, 768, 1024] }, completed: 400, total: 400, status: 'complete', scope: JSON.stringify([h.runtime.goal.revision]), ...extra }));
    await job('b'.repeat(32), { inside: { sha256: 's', mask_path: '/m.png', bounds: [0, 0, 768, 300] } });
    const canvas = { width: 768, height: 1024 };
    assert.deepEqual(await h.runtime.wholeTransfers(canvas), [], 'a transfer inside the area is not the whole picture');
    await job('c'.repeat(32), {});
    assert.equal((await h.runtime.wholeTransfers(canvas)).length, 1);
    h.runtime.currentMove = { number: 1 }; h.runtime.decisionObservation = { ...canvas };
    await h.runtime.capTypedStrokes({ tool: 'paint_from_reference', args: { reference_id: 'r', source: [0, 0, 10, 10], target: [0, 0, 768, 1024] } });
    await assert.rejects(h.runtime.capTypedStrokes({ tool: 'paint_pass', args: { strokes: Array.from({ length: 40 }, () => ({ start: [1, 1], size: 4 })) } }), /./,
      'typed strokes stay capped inside the area too');
    h.runtime.currentMove = null;
  } finally { await h.close(); }
});

// Find it for me (find-it.ts) through the studio: the panel's find_it command peeks the painting, locates the part with the
// decision model, finds it with the shapes model (fakes here) and answers found_area; Autopilot adopts a found outline.
function fakeFinder(h, { ready = true } = {}) {
  const shaped = [];
  h.runtime.shapes = { async study() { return { ms: 1, load_ms: 0, peak_mb: 1, provider: 'cpu', studied: true, attempt: 1 }; },
    async shape(_id, prompt) {
      shaped.push(prompt);
      const mask_path = join(h.output, `fake-mask-${shaped.length}.png`);
      await writeFile(mask_path, encodePlane({ width: 48, height: 16, data: new Uint8Array(48 * 16).fill(255) }));
      return { bounds: [0, 0, 48, 16], score: 0.98, mask_path, model: 'fake', revision: 'r', ms: 3, peak_mb: 1, provider: 'cpu', cached: false };
    },
    async forget() {}, async close() {}, async ready() { return ready; }, answer() { return false; }, stop() {} };
  h.runtime.lunaClient = { connected: true, async decide(request) {
    const names = Object.keys(request.questions);
    return { answers: Object.fromEntries(names.map((name, i) => [name, { type: 'noul', noul: i < 12 ? 0.9 : 0.05 }])), model: 'fake-luna' };
  } };
  const call0 = h.runtime.bridge.call.bind(h.runtime.bridge);
  h.runtime.bridge.call = async (operation, params, ...rest) => {
    if (operation === 'trace_reference') return { sha256: params.sha256, width: 48, height: 64, rgba_base64: Buffer.alloc(48 * 64 * 4).toString('base64') };
    if (operation === 'paint_only_here') { h.calls.push({ operation, params }); return { status: 'ok', bounds: params.bounds }; }
    return call0(operation, params, ...rest);
  };
  return shaped;
}

test('find_it: the outline of a named part on the painting comes back as found_area with its timing, then at once from the cache', { timeout: 30000 }, async () => {
  const { h } = await agentChat(() => ({ content: 'Done.' }));
  try {
    const shaped = fakeFinder(h);
    const found = await h.runtime.findIt({ request_id: 'r1', part: 'the sky' });
    const event = h.events.filter(e => e.type === 'found_area').at(-1);
    assert.equal(event.request_id, 'r1'); assert.equal(event.error, undefined);
    assert.equal(event.mask_path, found.mask_path);
    assert.ok(event.mask_path.startsWith(join(h.runtime.study.directory, '.shapes', 'found-')));
    assert.deepEqual(event.bounds, [0, 0, 768, 256], 'the view\u2019s top quarter at canvas size');
    assert.match(event.message, /^Found the sky in \d+\.\d s \(locating \d+\.\d s, shapes model \d+\.\d s\): 25% of the canvas\.$/);
    assert.equal(shaped.length, 12, 'one prompt a confident cell');
    const peek = h.calls.filter(c => c.operation === 'peek').at(-1);
    assert.equal(peek.params.guides, false, 'the painting without guide lines');
    await h.runtime.findIt({ request_id: 'r2', part: 'The sky' });
    assert.match(h.events.filter(e => e.type === 'found_area').at(-1).message, /again at once/);
    assert.equal(shaped.length, 12, 'no model for the same painting');
    await h.runtime.findIt({ request_id: 'r3', points: [[100, 100, 1]] });
    assert.match(h.events.filter(e => e.type === 'found_area').at(-1).error, /Say what to find/, 'by name only: no canvas click');
    assert.equal(shaped.length, 12);
    h.runtime.lunaClient = { connected: false, decide: async () => ({ fallback: 'not_connected' }) };
    await h.runtime.findIt({ request_id: 'r4', part: 'the moon' });
    assert.match(h.events.filter(e => e.type === 'found_area').at(-1).error, /decision model did not answer where the moon is\. Click it on the canvas instead/);
  } finally { await h.close(); }
});

test('a proposal is found only when it asks the artist nothing; Autopilot adopts it, protected on the painting through the bridge', { timeout: 30000 }, async () => {
  const { h } = await agentChat(() => ({ content: 'Done.' }));
  try {
    fakeFinder(h, { ready: false });
    assert.equal(await h.runtime.proposeArea('the sky'), null, 'the model is not allowed yet: no question from the host');
    h.runtime.shapes.ready = async () => true;
    const proposal = await h.runtime.proposeArea('the sky');
    assert.deepEqual(proposal.bounds, [0, 0, 768, 256]);
    const area = await h.runtime.adoptFoundArea(proposal, 'the sky', 'step-key');
    assert.equal(h.runtime.goal.paint_only_here.name, 'the sky'); assert.equal(h.runtime.goal.paint_only_here.auto, 'step-key');
    assert.match(area.mask_path, /\/\.shapes\/paint-only-[0-9a-f]{24}\.png$/);
    const sent = h.calls.filter(c => c.operation === 'paint_only_here').at(-1);
    assert.deepEqual([sent.params.action, sent.params.mask_path, sent.params.name], ['set', area.mask_path, 'the sky']);
    assert.equal(h.events.filter(e => e.type === 'goal').at(-1).goal.paint_only_here.name, 'the sky', 'the panel shows the chip');
  } finally { await h.close(); }
});

test('find_it is refused without a chat or while a move paints', { timeout: 30000 }, async () => {
  const { h } = await agentChat(() => ({ content: 'Done.' }));
  try {
    h.runtime.busy = true; h.runtime.goal.status = 'active';
    await h.runtime.findIt({ request_id: 'b', part: 'the sky' });
    assert.match(h.events.filter(e => e.type === 'found_area').at(-1).error, /Wait until the painting stops/);
    h.runtime.busy = false; h.runtime.goal.status = 'move_ready';
    const goal = h.runtime.goal; h.runtime.goal = null;
    await h.runtime.findIt({ request_id: 'c', part: 'the sky' });
    assert.match(h.events.filter(e => e.type === 'found_area').at(-1).error, /Start a chat first/);
    h.runtime.goal = goal;
  } finally { await h.close(); }
});

test('an area Autopilot found is its own: it ends with its step, the run, Stop or a mode switch; the artist\'s area stays', { timeout: 30000 }, async () => {
  const { h } = await agentChat(() => ({ content: 'Done.' }));
  try {
    fakeFinder(h);
    const proposal = await h.runtime.proposeArea('the sky');
    const cleared = () => h.calls.filter(c => c.operation === 'paint_only_here' && c.params.action === 'clear').length;
    await h.runtime.adoptFoundArea(proposal, 'the sky');
    assert.equal(h.runtime.goal.paint_only_here.auto, 'run', 'tagged even without a plan step');
    await h.runtime.setMode('autopilot'); await h.runtime.setMode('agent');
    assert.equal(h.runtime.goal.paint_only_here, null, 'a mode switch ends it'); assert.equal(cleared(), 1);
    assert.match(h.events.filter(e => e.type === 'action').at(-1).message, /^Painting everywhere again: Autopilot is off/);
    await h.runtime.adoptFoundArea(proposal, 'the sky', 'step-a');
    h.runtime.mode = 'autopilot'; h.runtime.goal.brief = { steps: [{ title: 'Sky' }] }; h.runtime.planSteps.keyAt = () => 'step-b';
    await h.runtime.autopilotElementArea();
    assert.equal(h.runtime.goal.paint_only_here, null, 'its step is over'); assert.equal(cleared(), 2);
    await h.runtime.adoptFoundArea(proposal, 'the sky', 'step-b');
    h.runtime.stop(); await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(h.runtime.goal.paint_only_here, null, 'Stop ends it'); assert.equal(cleared(), 3);
    h.runtime.mode = 'agent';
    await h.runtime.setPaintOnlyHere(await skyMask(h));
    assert.equal(await h.runtime.clearAutoArea('x'), false, 'the artist\'s own area is never cleared by Autopilot');
    assert.equal(h.runtime.goal.paint_only_here.name, 'the sky');
  } finally { await h.close(); }
});

test('a bridge failure leaves no area and no file: Autopilot paints without an area and says why', { timeout: 30000 }, async () => {
  const { h } = await agentChat(() => ({ content: 'Done.' }));
  try {
    fakeFinder(h);
    const proposal = await h.runtime.proposeArea('the sky');
    const call1 = h.runtime.bridge.call;
    h.runtime.bridge.call = async (operation, ...rest) => { if (operation === 'paint_only_here') throw new Error('Open the painting first.'); return call1(operation, ...rest); };
    await assert.rejects(h.runtime.adoptFoundArea(proposal, 'the sky'), /could not be protected on the painting: Open the painting first/);
    assert.equal(h.runtime.goal.paint_only_here ?? null, null);
    const { readdir } = await import('node:fs/promises');
    assert.deepEqual((await readdir(join(h.runtime.study.directory, '.shapes'))).filter(n => n.startsWith('paint-only-')), [], 'its mask copy is removed');
    const { askForArea } = await import('../src/paint-only-here.ts');
    const { selectionHostFor } = await import('../src/tools.mjs');
    h.runtime.mode = 'autopilot';
    const outcome = await askForArea(selectionHostFor(h.runtime), 'the sky');
    assert.equal(outcome.asked, false); assert.equal(outcome.adopted, undefined);
    assert.match(outcome.reply, /without an area/);
    assert.match(h.events.filter(e => e.type === 'action').at(-1).message, /painting the sky without an area \(The found area could not be protected/);
    h.runtime.mode = 'agent';
  } finally { await h.close(); }
});
