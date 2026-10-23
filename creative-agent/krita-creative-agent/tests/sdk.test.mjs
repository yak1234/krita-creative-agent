import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { PaintingRuntime } from '../src/runtime.mjs';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64');

test('real Pi SDK runs a tool loop, forwards images and exposes only painting tools', { timeout: 20000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'creative-sdk-'));
  const requests = [];
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const request = JSON.parse(body); requests.push(request);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const tool = requests.length === 1;
    const delta = tool ? { role: 'assistant', tool_calls: [{ index: 0, id: 'test-observe', type: 'function',
      function: { name: 'observe_canvas', arguments: '{}' } }] } : { role: 'assistant', content: 'I inspected the canvas image.' };
    for (const choice of [{ delta, finish_reason: null }, { delta: {}, finish_reason: tool ? 'tool_calls' : 'stop' }])
      res.write('data: ' + JSON.stringify({ id: 'test-response', object: 'chat.completion.chunk', created: 1, model: 'vision-test', choices: [{ index: 0, ...choice }] }) + '\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const models = await ModelRuntime.create({ authPath: join(directory, 'auth.json'), modelsPath: null, refreshOnCreate: false });
  models.registerProvider('local-test', { api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
    models: [{ id: 'vision-test', name: 'Test', reasoning: false, input: ['text','image'],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 64000, maxTokens: 4096 }] });
  await models.setRuntimeApiKey('local-test', 'test-only-not-a-real-key');
  let observation;
  const bridge = {
    async call(operation, params) {
      if (operation === 'begin') {
        const path = join(params.output_dir, 'view.png'); await writeFile(path, png);
        observation = { status: 'ok', document_id: 'test-document', width: 768, height: 1024,
          image_path: path, checkpoint: join(params.output_dir, 'checkpoint.kra'), layers: [] };
      }
      return observation;
    },
  };
  const events = [];
  const runtime = new PaintingRuntime({ root: directory, config: { output: directory }, bridge, models, emit: e => events.push(e) });
  try {
    await runtime.start({ provider: 'local-test', model: 'vision-test', experiment: 'free', prompt: 'Inspect the canvas.' });
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[0].tools.map(t => t.function.name).sort(), ['adjust_layer','apply_filter','bucket_fill','clone_layer','colorize_flats','composition_guides','continue_reference_painting','create_layer','draw_guide','enclose_and_fill','fill_region','finish_guide','krita_action','krita_capabilities','krita_gradient','letter','list_brushes','list_reference_paintings','make_asset','observe_canvas','paint_accents','paint_batch','paint_contours','paint_from_reference','paint_pass','paint_recipe','paint_reference_edges','paint_reference_surface','painting_tool_help','painting_toolbox','propose_protection','read','run_skill_script','sample_canvas_colors','select','set_layer','smart_patch','split_by_color','transform_layer','view_reference']);
    assert.ok(requests[1].messages.some(m => m.role === 'user' && Array.isArray(m.content) && m.content.some(c => c.type === 'image_url')));
    const system = requests[0].messages.find(m => m.role === 'system')?.content;
    assert.match(typeof system === 'string' ? system : JSON.stringify(system), /<name>image-asset<\/name>/, 'Pi lists the bundled skills while the skill-only read tool is active');
    assert.ok(requests[1].messages.some(m => m.role === 'tool' && m.tool_call_id === 'test-observe'));
    assert.ok(events.some(e => e.type === 'text' && e.text.includes('inspected')));
    assert.equal(runtime.session.agent.toolExecution, 'sequential');
    assert.ok(runtime.session.sessionFile.startsWith(directory));
    assert.equal(runtime.busy, false);
    const statuses = events.filter(e => e.type === 'status');
    assert.ok(statuses.some(e => e.phase === 'waiting'));
    assert.equal(statuses.at(-1).phase, 'idle');
    const id = runtime.study.id;
    await runtime.end();
    await runtime.resume(id);
    assert.equal(requests.length, 2, 'restoring chat does not send a model request');
    assert.equal(runtime.study.id, id);
    assert.ok(events.some(e => e.type === 'history' && e.messages.some(m => m.text.includes('Inspect the canvas.'))));
  } finally {
    await runtime.end().catch(() => {});
    await new Promise(resolve => server.close(resolve));
    await rm(directory, { recursive: true, force: true });
  }
});
