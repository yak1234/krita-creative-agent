import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { StudioRuntime } from '../src/studio.mjs';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ9kAAAAASUVORK5CYII=', 'base64');
const brief = {
  title: 'Two characters by the studio window', objective: 'A quiet seated portrait with consistent character identities.',
  requirements: ['Mara keeps her crimson coat and remains seated on the left.', 'Ivo keeps green eyes and looks toward Mara.'],
  characters: [
    { name: 'Mara', requirements: ['Curly black hair.', 'Crimson coat.', 'Seated left, looking toward Ivo.'] },
    { name: 'Ivo', requirements: ['Green eyes.', 'Blue wool scarf.', 'Standing right, looking toward Mara.'] },
  ],
  freedom: ['Choose the window light.'],
  steps: [{ title: 'Calibrate material', done_when: 'A granular test stroke is visible.', stop_after: true, max_operations: 1 }],
  completion: ['The likeness and clothing requirements remain intact.'],
};
const summary = 'A portrait was discussed. Planning can continue. Specific character details were omitted from this test summary.';
const latestText = request => {
  const content = request.messages.filter(message => message.role === 'user').at(-1)?.content;
  return typeof content === 'string' ? content : (content ?? []).filter(item => item.type === 'text').map(item => item.text).join('\n');
};
function assertDurableContext(request) {
  const text = latestText(request);
  for (const requirement of brief.requirements) assert.ok(text.includes(requirement), 'Latest request includes locked requirement: ' + requirement);
  for (const character of brief.characters) {
    assert.ok(text.includes(character.name));
    for (const requirement of character.requirements) assert.ok(text.includes(requirement), 'Latest request includes character detail: ' + requirement);
  }
}

test('actual Pi compaction may omit character facts while durable rules survive model change and a fresh runtime restart', { timeout: 30000 }, async () => {
  const output = await mkdtemp(join(tmpdir(), 'creative-compaction-'));
  const requests = [], native = [], events = [], sdkEvents = [];
  let toolSequence = 0;
  const server = createServer(async (incoming, response) => {
    let body = ''; for await (const chunk of incoming) body += chunk;
    const request = JSON.parse(body); requests.push(request);
    const names = (request.tools ?? []).map(tool => tool.function.name);
    let delta;
    if (!names.length) delta = { content: summary };
    else if (names.includes('propose_plan')) {
      // The replacement model forgets all character details in its proposal.
      // The product must preserve them from its durable, user-edited records.
      const proposal = { ...brief, title: 'A clearer plan', requirements: [], characters: [] };
      delta = { tool_calls: [{ index: 0, id: 'proposal-' + (++toolSequence), type: 'function',
        function: { name: 'propose_plan', arguments: JSON.stringify(proposal) } }] };
    } else delta = { content: 'We can review the intended painting while leaving the canvas unchanged.' };
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const choice of [{ delta: { role: 'assistant', ...delta }, finish_reason: null },
      { delta: {}, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }])
      response.write('data: ' + JSON.stringify({ id: 'reply-' + requests.length, object: 'chat.completion.chunk', created: 1,
        model: request.model, choices: [{ index: 0, ...choice }] }) + '\n\n');
    response.end('data: [DONE]\n\n');
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const models = await ModelRuntime.create({ authPath: join(output, 'test-auth.json'), modelsPath: null, refreshOnCreate: false });
  models.registerProvider('local-compaction-test', { api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
    models: ['before-compaction', 'after-compaction'].map(id => ({ id, name: id, reasoning: false, input: ['text', 'image'],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 64000, maxTokens: 4096 })) });
  await models.setRuntimeApiKey('local-compaction-test', 'test-only-public-loopback');
  const bridge = { async call(operation, params) {
    native.push(operation);
    if (operation === 'context') return { document_id: 'open-canvas', active_document_id: 'open-canvas', name: 'Unsaved test canvas', width: 768, height: 1024, modified: true };
    if (operation === 'peek') {
      const path = join(params.output_dir, 'canvas.png'); await writeFile(path, png);
      return { status: 'ok', document_id: 'open-canvas', name: 'Unsaved test canvas', filename: '', modified: true,
        width: 768, height: 1024, image_path: path, layers: [], revision: 'unchanged', content_id: 'unchanged-image', captured_at: Date.now() };
    }
    throw new Error('Read-only compaction test attempted a native mutation: ' + operation);
  } };
  const makeRuntime = () => new StudioRuntime({ root: output, config: { output }, models, bridge, tracing: recordingTracing(), emit: event => events.push(event) });
  let runtime = makeRuntime();
  try {
    await runtime.start({ provider: 'local-compaction-test', model: 'before-compaction', chat_mode: 'ask', prompt: 'Discuss an initial portrait idea.' });
    const originalSession = runtime.session;
    originalSession.subscribe(event => sdkEvents.push(event));
    originalSession.settingsManager.applyOverrides({ compaction: { enabled: false, keepRecentTokens: 50, reserveTokens: 512 } });
    const originalUserEntry = originalSession.sessionManager.getBranch().find(entry => entry.type === 'message' && entry.message.role === 'user');
    await runtime.editPlan(brief);
    await runtime.prompt('Review the character constraints. ' + 'Earlier composition observations. '.repeat(80));
    await runtime.prompt('Keep the two people and discuss the light.');
    assertDurableContext(requests.at(-1));
    const requestCount = requests.length;
    const compacted = await originalSession.compact('Create a short progress summary.');
    assert.ok(requests.length > requestCount, 'The real SDK requested a model-generated compaction summary.');
    assert.ok(compacted.summary.includes(summary));
    assert.ok(!compacted.summary.includes('Mara') && !compacted.summary.includes('crimson'), 'The summary deliberately lacks the protected facts.');
    assert.ok(sdkEvents.some(event => event.type === 'compaction_start' && event.reason === 'manual'));
    assert.ok(sdkEvents.some(event => event.type === 'compaction_end' && event.result && !event.aborted));
    const activeEntries = originalSession.sessionManager.buildContextEntries();
    assert.ok(activeEntries.some(entry => entry.type === 'compaction'), 'An actual SDK compaction entry is active.');
    assert.ok(!activeEntries.some(entry => entry.id === originalUserEntry.id), 'Earlier messages were actually removed from the active context.');
    assert.deepEqual(runtime.goal.locked_requirements, brief.requirements);
    assert.deepEqual(runtime.goal.character_records, brief.characters);
    await runtime.prompt('What must remain consistent after this conversation was shortened?');
    assertDurableContext(requests.at(-1));
    await runtime.setModel('local-compaction-test', 'after-compaction');
    assert.equal(runtime.session, originalSession, 'Changing models preserves the real SDK session.');
    await runtime.prompt('Review those same requirements with the replacement model.');
    assert.equal(requests.at(-1).model, 'after-compaction'); assertDurableContext(requests.at(-1));
    const id = runtime.study.id, file = runtime.session.sessionFile;
    await runtime.end();
    // The chat log lives in the records database (storage-layout phase B), not a JSONL file.
    await assert.rejects(readFile(file, 'utf8'), { code: 'ENOENT' });
    const persisted = runtime.store.sessions.load(runtime.store.sessions.locate(file));
    assert.ok(persisted.some(entry => entry.type === 'compaction'), 'The SDK persisted compaction in its actual session log.');
    runtime.dispose();
    runtime = makeRuntime();
    const beforeResume = requests.length;
    await runtime.resume(id);
    assert.notEqual(runtime.session, originalSession, 'Restart opens a new SDK session object from disk.');
    assert.equal(requests.length, beforeResume, 'Restore does not make a model request.');
    assert.equal(runtime.study.model, 'after-compaction');
    assert.deepEqual(runtime.goal.locked_requirements, brief.requirements);
    assert.deepEqual(runtime.goal.character_records, brief.characters);
    assert.ok(runtime.session.sessionManager.buildContextEntries().some(entry => entry.type === 'compaction'));
    await runtime.prompt('Describe the preserved character choices after restart.');
    assertDurableContext(requests.at(-1));
    await runtime.setMode('plan'); await runtime.prompt('Make the plan clearer while preserving all character details.');
    assert.deepEqual(runtime.goal.brief.requirements, brief.requirements);
    assert.deepEqual(runtime.goal.brief.characters, brief.characters);
    assert.ok(native.every(operation => ['context', 'peek'].includes(operation)), 'Compaction, switching and restore never save or paint.');
  } finally {
    if (runtime.busy) runtime.stop();
    await runtime.writeQueue; await runtime.end().catch(() => {});
    runtime.dispose();
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    await rm(output, { recursive: true, force: true });
  }
});
