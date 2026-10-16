import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { inflateSync } from 'node:zlib';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { ModelCapabilities, modelRouteKey, isInteractiveModel } from '../src/model-capabilities.mjs';
import { CapabilityError } from '../src/model-capabilities.mjs';

const RGB = { '235,35,45': 'red', '25,175,70': 'green', '30,65,230': 'blue', '250,220,30': 'yellow', '15,15,15': 'black', '245,245,245': 'white' };
function readTestColors(request) {
  const image = request.messages.flatMap(message => Array.isArray(message.content) ? message.content : []).find(item => item.type === 'image_url');
  assert.ok(image?.image_url?.url.startsWith('data:image/png;base64,'), 'The capability probe must send actual PNG bytes.');
  const png = Buffer.from(image.image_url.url.split(',')[1], 'base64');
  const width = png.readUInt32BE(16), height = png.readUInt32BE(20), chunks = [];
  assert.ok(width>=512 && height>=512,'Use a visible-size fixture; tiny inputs caused false failures on the real Sol route.');
  for (let offset = 8; offset < png.length;) {
    const length = png.readUInt32BE(offset), kind = png.toString('ascii', offset + 4, offset + 8);
    if (kind === 'IDAT') chunks.push(png.subarray(offset + 8, offset + 8 + length));
    offset += length + 12;
  }
  const pixels = inflateSync(Buffer.concat(chunks));
  return [[.25,.25],[.75,.25],[.25,.75],[.75,.75]].map(([x,y]) => {
    const offset = Math.floor(y * height) * (width * 3 + 1) + 1 + Math.floor(x * width) * 3;
    return RGB[[...pixels.subarray(offset, offset + 3)].join(',')];
  });
}
async function harness(t, mode = 'success', options = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'creative-capabilities-test-'));
  const requests = [], events = [];
  let currentMode = mode, notify;
  const entered = new Promise(resolve => { notify = resolve; });
  const server = createServer(async (incoming, response) => {
    let body = ''; for await (const chunk of incoming) body += chunk;
    const request = JSON.parse(body); requests.push(request); notify();
    if (currentMode === 'timeout') return;
    if (currentMode === 'authentication') { response.writeHead(401); response.end(JSON.stringify({ error: { message: 'Unauthorized secret-test-do-not-store', type: 'authentication_error' } })); return; }
    let delta;
    const result = request.messages.filter(message => message.role === 'tool').at(-1);
    if (result) {
      const receipt = JSON.parse(typeof result.content === 'string' ? result.content : result.content[0].text).confirmation_code;
      delta = { content: currentMode === 'roundtrip' ? 'The tool response was ignored.' : 'READY ' + receipt };
    } else if (currentMode === 'no-tool') delta = { content: 'I see an image but did not invoke a tool.' };
    else {
      const colors = currentMode === 'wrong-image' ? ['red','red','red','red'] : readTestColors(request);
      delta = { tool_calls: [{ index: 0, id: 'vision-' + requests.length, type: 'function', function: {
        name: 'report_visual_readiness', arguments: JSON.stringify({ colors }) } }] };
    }
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const choice of [{ delta: { role: 'assistant', ...delta }, finish_reason: null },
      { delta: {}, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }])
      response.write('data: ' + JSON.stringify({ id: 'reply', object: 'chat.completion.chunk', created: 1, model: request.model, choices: [{ index: 0, ...choice }] }) + '\n\n');
    response.end('data: [DONE]\n\n');
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const models = await ModelRuntime.create({ authPath: join(directory, 'test-auth.json'), modelsPath: null, refreshOnCreate: false });
  models.registerProvider('capability-test', { api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1`, models: [{
    id: 'vision-model', name: 'Vision model', reasoning: false, input: ['text','image'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 64000, maxTokens: 4096 }] });
  await models.setRuntimeApiKey('capability-test', 'dummy-test-key');
  const model = models.getModel('capability-test', 'vision-model');
  const capabilities = new ModelCapabilities({ models, cacheDirectory: directory, retryDelayMs:0, onStatus: event => events.push(event), ...options });
  await capabilities.initialize();
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await rm(directory, { recursive: true, force: true }); });
  return { capabilities, models, model, directory, requests, events, entered, setMode(value) { currentMode = value; } };
}

test('actual Pi probe verifies image pixels, harmless tool result and persists a safe 24-hour route cache', { timeout: 15000 }, async t => {
  const h = await harness(t);
  assert.equal(h.capabilities.status(h.model).status, 'unverified');
  const result = await h.capabilities.verify(h.model);
  assert.equal(result.route_verified, true); assert.equal(result.images_supported, true); assert.equal(result.tools_supported, true);
  assert.equal(result.cached, false); assert.ok(result.expires_at - result.verified_at <= 86400000);
  assert.equal(h.requests.length, 2, 'Probe requires image/tool request plus returned-tool confirmation.');
  assert.deepEqual(h.requests[0].tools.map(tool => tool.function.name), ['report_visual_readiness']);
  assert.equal(h.events[0].status, 'verifying'); assert.equal(h.events.at(-1).status, 'verified');
  const raw = await readFile(join(h.directory, 'model-capabilities.json'), 'utf8');
  assert.ok(!raw.includes('dummy-test-key') && !raw.includes('http://') && !raw.includes('confirmation_code'));
  const restored = new ModelCapabilities({ models: h.models, cacheDirectory: h.directory }); await restored.initialize();
  const count = h.requests.length;
  assert.equal((await restored.verify(h.model)).cached, true); assert.equal(h.requests.length, count);
  assert.equal(restored.status(h.model).status, 'verified');
});

test('wrong image reports fail independently of accepting image payloads and tool schemas', { timeout: 15000 }, async t => {
  const h = await harness(t, 'wrong-image');
  await assert.rejects(h.capabilities.verify(h.model), { code: 'image_unverified' });
  assert.equal(h.capabilities.status(h.model).route_verified, false); assert.equal(h.requests.length, 2);
});

test('a temporary capability failure retries automatically and succeeds without artist input',async t=>{
  const h=await harness(t),probe=h.capabilities.probe.bind(h.capabilities);let attempts=0;
  h.capabilities.probe=async(...args)=>{if(++attempts===1)throw new CapabilityError('rate_limit');return probe(...args);};
  assert.equal((await h.capabilities.verify(h.model)).route_verified,true);assert.equal(attempts,2);
  assert.ok(h.events.some(e=>e.message.includes('automatically')));
});

test('missing tools and missing tool-result confirmation have distinct failures', { timeout: 15000 }, async t => {
  const h = await harness(t, 'no-tool');
  await assert.rejects(h.capabilities.verify(h.model), { code: 'tools_unverified' });
  h.setMode('roundtrip');
  await assert.rejects(h.capabilities.verify(h.model), { code: 'tool_roundtrip' });
});

test('timeouts and user cancellation abort a disposable probe without verifying the route', { timeout: 15000 }, async t => {
  const h = await harness(t, 'timeout', { timeoutMs: 80 });
  await assert.rejects(h.capabilities.verify(h.model), { code: 'timeout' });
  const controller = new AbortController();
  h.capabilities.timeoutMs = 5000;
  const running = h.capabilities.verify(h.model, { signal: controller.signal });
  setTimeout(() => controller.abort(), 40);
  await assert.rejects(running, { code: 'cancelled' });
  assert.equal(h.capabilities.status(h.model).route_verified, false);
});

test('provider errors are classified without persisting or emitting raw secrets', { timeout: 15000 }, async t => {
  const h = await harness(t, 'authentication');
  const error = await h.capabilities.verify(h.model).then(() => null, value => value);
  assert.equal(error.code, 'authentication'); assert.ok(!error.message.includes('secret-test'));
  assert.ok(!JSON.stringify(h.events).includes('secret-test'));
  assert.ok(!(await readFile(join(h.directory, 'model-capabilities.json'), 'utf8')).includes('secret-test'));
});

test('cache is keyed by route identity and configuration, expires, and can be explicitly invalidated', { timeout: 15000 }, async t => {
  const h = await harness(t);
  await h.capabilities.verify(h.model);
  const key = modelRouteKey(h.model, 2);
  assert.equal(modelRouteKey({ ...h.model, baseUrl: h.model.baseUrl + '/' }, 2), key);
  for (const model of [{ ...h.model, baseUrl: h.model.baseUrl + '/changed' }, { ...h.model, api: 'anthropic-messages' }, { ...h.model, id: 'other-model' }]) {
    assert.notEqual(modelRouteKey(model, 2), key); assert.equal(h.capabilities.status(model).status, 'unverified');
  }
  assert.notEqual(modelRouteKey(h.model, 3), key);
  const configChanged = new ModelCapabilities({ models: h.models, cacheDirectory: h.directory, configVersion: 3 }); await configChanged.initialize();
  assert.equal(configChanged.status(h.model).status, 'unverified');
  const file = join(h.directory, 'model-capabilities.json'), saved = JSON.parse(await readFile(file, 'utf8'));
  saved.entries[key].verified_at = Date.now() - 86400001; saved.entries[key].expires_at = Date.now() - 1;
  await writeFile(file, JSON.stringify(saved));
  const expired = new ModelCapabilities({ models: h.models, cacheDirectory: h.directory }); await expired.initialize();
  assert.equal(expired.status(h.model).status, 'unverified');
  await h.capabilities.invalidate(h.model); assert.equal(h.capabilities.status(h.model).status, 'unverified');
});

test('batch and declared text-only models reject before any provider request', { timeout: 15000 }, async t => {
  const h = await harness(t);
  const batch = { ...h.model, name: 'Vision model (batch)' };
  assert.equal(isInteractiveModel(batch), false);
  await assert.rejects(h.capabilities.verify(batch), { code: 'batch_only' });
  await assert.rejects(h.capabilities.verify({ ...h.model, input: ['text'] }), { code: 'unsupported_image' });
  assert.equal(h.requests.length, 0);
});
