// Loop guards: the shipped Pi extension that adds hints to tool results. A fake `pi` for the rules, and a real Pi
// session (scripted model over local HTTP) for loading with discovery off. Writes only a temporary folder, removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import loopGuards from '../extensions/loop-guards.ts';
import { PaintingRuntime } from '../src/runtime.mjs';

function guards() {
  const handlers = {}, channels = {};
  loopGuards({ on: (name, handler) => { handlers[name] = handler; }, events: { on: (channel, handler) => { channels[channel] = handler; } } });
  let revision = 0;
  const result = (toolName, input = {}, details = {}, extra = {}) => {
    const event = { type: 'tool_result', toolCallId: 'id', toolName, input, isError: false,
      content: [{ type: 'text', text: '{"status":"ok"}' }], details: { width: 1000, height: 1000, ...details }, ...extra };
    const changed = handlers.tool_result(event, {});
    const text = changed?.content?.slice(1).map(c => c.text).join(' ');
    return text ? JSON.parse(text).craft_hint : null;
  };
  const paint = (toolName, input) => result(toolName, input, { revision: 'r' + ++revision });
  const look = (details = {}) => result('observe_canvas', {}, { revision: 'r' + revision, ...details });
  return { result, paint, look, settings: data => channels['krita:guards'](data), bump: () => ++revision };
}
const small = { name: 'Accent', strokes: [{ start: [10, 10], segments: [[12, 12, 14, 14, 20, 20]] }] };
const big = { name: 'Coat mass', strokes: [{ start: [50, 100], segments: [[200, 150, 400, 500, 700, 900]] }] };

test('a plain stroke pass over a large share of the canvas gets the mass hint', () => {
  const g = guards();
  assert.match(g.paint('paint_pass', big), /"Coat mass" covered about \d+% of the canvas with plain strokes/);
  assert.equal(g.paint('paint_pass', { ...big, name: 'Fur', clip_to: '$1', blend_mode: 'overlay' }), null, 'clipped texture is the craft');
  assert.match(g.paint('paint_recipe', { name: 'Sky scumble', region: [0, 0, 800, 400] }), /32% of the canvas/);
});

test('a streak of plain stroke calls gets a reminder; a craft call resets it', () => {
  const g = guards();
  assert.deepEqual([1, 2, 3].map(() => g.paint('paint_pass', small)), [null, null, null]);
  assert.match(g.paint('paint_pass', small), /last 4 painting calls were plain strokes/);
  assert.equal(g.paint('fill_region', { name: 'Sky' }), null);
  assert.deepEqual([1, 2, 3].map(() => g.paint('paint_pass', small)), [null, null, null], 'counted again from the craft call');
  assert.match(g.paint('paint_batch', { actions: [{ tool: 'paint_pass', arguments: small }] }), /last 4/, 'a batch of strokes counts once');
});

test('four looks without a change carry the nudge', () => {
  const g = guards();
  assert.deepEqual([1, 2, 3].map(() => g.look()), [null, null, null]);
  assert.match(g.look(), /You have looked 4 times without changing anything\. Select the area with a seed or split_by_color/);
  assert.match(g.look(), /looked 5 times/);
});

test('a painting call resets the look count, and so does a new canvas revision', () => {
  const g = guards();
  g.look(); g.look(); g.look();
  g.paint('fill_region', { name: 'Sky' });
  assert.deepEqual([1, 2, 3].map(() => g.look()), [null, null, null]);
  g.bump();                                         // the artist painted: the next look sees a new revision
  assert.deepEqual([1, 2, 3].map(() => g.look()), [null, null, null]);
  assert.match(g.look(), /looked 4 times/);
});

test('reference views and refused calls do not count as looks or painting', () => {
  const g = guards();
  g.look(); g.look(); g.look();
  g.result('view_reference', {}, {});
  g.result('fill_region', { name: 'Sky' }, { revision: 'r-new' }, { isError: true, content: [{ type: 'text', text: 'Refused.' }] });
  assert.match(g.look(), /looked 4 times/);
});

test('a refused call gets one fix hint', () => {
  const g = guards();
  const refused = text => g.result('paint_pass', small, {}, { isError: true, content: [{ type: 'text', text }] });
  assert.match(refused('coordinate must be between -40 and 1040'), /up to one brush size outside the canvas/);
  assert.match(refused('That layer is no longer in this painting.'), /layer_index/);
  assert.equal(refused('Unknown preset.'), null);
  const both = refused('coordinate must be between -40 and 1040; That layer is no longer in this painting.');
  assert.equal(typeof both, 'string', 'one hint, not two');
  assert.doesNotMatch(both, /layer_index/);
});

test('any other successful call resets the look count: selecting is acting', () => {
  const g = guards();
  g.look(); g.look(); g.look();
  g.result('select', { name: 'Sky', steps: [{ seed: [1, 1] }] }, {});
  assert.deepEqual([1, 2, 3].map(() => g.look()), [null, null, null]);
});

test('with native craft off the guards add nothing', () => {
  const g = guards();
  g.settings({ native_craft: false });
  assert.equal(g.paint('paint_pass', big), null);
  g.look(); g.look(); g.look();
  assert.equal(g.look(), null);
  g.settings({ native_craft: true });
  assert.match(g.paint('paint_pass', big), /covered about/);
});

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64');

async function lookFourTimes(settings) {
  const directory = await mkdtemp(join(tmpdir(), 'loop-guards-'));
  const requests = [];
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    requests.push(JSON.parse(body));
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const look = requests.length <= 4;
    const delta = look ? { role: 'assistant', tool_calls: [{ index: 0, id: 'look-' + requests.length, type: 'function',
      function: { name: 'observe_canvas', arguments: '{}' } }] } : { role: 'assistant', content: 'Done looking.' };
    for (const choice of [{ delta, finish_reason: null }, { delta: {}, finish_reason: look ? 'tool_calls' : 'stop' }])
      res.write('data: ' + JSON.stringify({ id: 'r', object: 'chat.completion.chunk', created: 1, model: 'vision-test', choices: [{ index: 0, ...choice }] }) + '\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const models = await ModelRuntime.create({ authPath: join(directory, 'auth.json'), modelsPath: null, refreshOnCreate: false });
  models.registerProvider('local-test', { api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
    models: [{ id: 'vision-test', name: 'Test', reasoning: false, input: ['text', 'image'],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 64000, maxTokens: 4096 }] });
  await models.setRuntimeApiKey('local-test', 'test-only-not-a-real-key');
  let observation;
  const bridge = { async call(operation, params) {
    if (operation === 'begin') {
      const path = join(params.output_dir, 'view.png'); await writeFile(path, png);
      observation = { status: 'ok', document_id: 'test-document', width: 768, height: 1024, revision: 'same',
        image_path: path, checkpoint: join(params.output_dir, 'checkpoint.kra'), layers: [] };
    }
    return observation;
  } };
  const runtime = new PaintingRuntime({ root: directory, config: { output: directory }, bridge, models, emit: () => {} });
  if (settings) runtime.executionSettings = settings;
  try {
    await runtime.start({ provider: 'local-test', model: 'vision-test', experiment: 'free', prompt: 'Look at the canvas.' });
    assert.equal(requests.length, 5);
    return requests.map(request => JSON.stringify(request.messages.findLast(m => m.role === 'tool')?.content ?? ''));
  } finally {
    await runtime.end?.().catch(() => {}); await runtime.releaseLock?.().catch(() => {});
    server.close(); await rm(directory, { recursive: true, force: true });
  }
}

test('the shipped extension loads with discovery off and hints on the painter’s own tools', { timeout: 20000 }, async () => {
  const toolText = await lookFourTimes();
  assert.doesNotMatch(toolText[3], /looked/, 'three looks: no nudge');
  assert.match(toolText[4], /looked 4 times without changing anything/);
});

test('a fresh session with native craft off gets no hints', { timeout: 20000 }, async () => {
  const toolText = await lookFourTimes({ native_craft: false });
  assert.doesNotMatch(toolText[4], /looked/);
});
