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
    assert.deepEqual(question.select_area, { part: 'the sky' });
    assert.deepEqual(question.options, ['Select with Freehand', 'Use my selection', 'Paint everywhere']);
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
