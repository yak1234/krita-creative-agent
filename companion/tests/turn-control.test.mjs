import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Type } from 'typebox';
import { createAgentSession, defineTool, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } from '@earendil-works/pi-coding-agent';
import { stopAfterTurn } from '../src/turn-control.mjs';

// A model that never finishes on its own: every reply asks for another tool call. Only the turn
// limit can end the run, so the request count shows exactly where it stopped.
test('stopAfterTurn ends a real Pi run after exactly the limit, counting turns on turn_end', { timeout: 20000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'creative-turns-'));
  let requests = 0;
  const server = createServer(async (req, res) => {
    for await (const _ of req) { /* drain the request */ }
    requests++;
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const delta = { role: 'assistant', tool_calls: [{ index: 0, id: 'call-' + requests, type: 'function', function: { name: 'tick', arguments: '{}' } }] };
    for (const choice of [{ delta, finish_reason: null }, { delta: {}, finish_reason: 'tool_calls' }])
      res.write('data: ' + JSON.stringify({ id: 'r' + requests, object: 'chat.completion.chunk', created: 1, model: 'loop-test', choices: [{ index: 0, ...choice }] }) + '\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let session;
  try {
    const models = await ModelRuntime.create({ authPath: join(directory, 'auth.json'), modelsPath: null, refreshOnCreate: false });
    models.registerProvider('loop-test', { api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
      models: [{ id: 'loop-test', name: 'Loop', reasoning: false, input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 64000, maxTokens: 4096 }] });
    await models.setRuntimeApiKey('loop-test', 'test-only-not-a-real-key');
    const settings = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false }, packages: [], extensions: [], skills: [] });
    const loader = new DefaultResourceLoader({ cwd: directory, agentDir: join(directory, 'agent'), settingsManager: settings,
      noExtensions: true, noSkills: true, noContextFiles: true, noPromptTemplates: true, noThemes: true, systemPromptOverride: () => 'Call tick.' });
    await loader.reload();
    const tick = defineTool({ name: 'tick', label: 'Tick', description: 'Does nothing.', parameters: Type.Object({}),
      execute: async () => ({ content: [{ type: 'text', text: 'ok' }], details: {} }) });
    ({ session } = await createAgentSession({ cwd: directory, agentDir: join(directory, 'agent'), modelRuntime: models,
      model: models.getModel('loop-test', 'loop-test'), thinkingLevel: 'off', settingsManager: settings, resourceLoader: loader,
      sessionManager: SessionManager.inMemory(directory), customTools: [tick], tools: ['tick'] }));
    let turns = 0;
    const seen = [];
    session.subscribe(event => { if (event.type === 'turn_end') turns++; });
    stopAfterTurn(session.agent, () => turns, done => { seen.push(done); return done >= 3; });
    await session.prompt('Start.', { expandPromptTemplates: false });
    assert.equal(requests, 3, 'a limit of 3 turns makes 3 model requests, not 4');
    assert.equal(turns, 3);
    assert.deepEqual(seen, [1, 2, 3], 'each check counts the turn just finished');
  } finally {
    session?.dispose();
    await new Promise(resolve => server.close(resolve));
    await rm(directory, { recursive: true, force: true });
  }
});
