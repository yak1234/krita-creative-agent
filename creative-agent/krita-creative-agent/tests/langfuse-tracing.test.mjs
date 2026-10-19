import test from 'node:test';
import assert from 'node:assert/strict';
import { LangfuseTracing, LangfuseConnectionError, chatMessage, connectLangfuse, langfuseCredentials, maskSecrets, parseDotEnv } from '../src/langfuse-tracing.mjs';
import { fakeLangfuse, recordingTracing } from './fake-langfuse.mjs';
import { LunaClient } from '../src/luna-decisions.ts';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function fakeSession() {
  const listeners = new Set();
  return { sessionId: 'pi-1', agent: { state: { systemPrompt: 'You paint.' } },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }, fire(e) { for (const l of listeners) l(e); } };
}

test('one agent run becomes an agent trace with a generation per model call and sibling tools', () => {
  const fake = fakeLangfuse(), session = fakeSession();
  const tracer = new LangfuseTracing({ ...fake, release: 'build-1' });
  tracer.watchSession(session, { traceName: 'painter', generationName: 'choose-next-action',
    describe: () => ({ traceName: 'paint-goal', sessionId: 'study-1', tags: ['painter'], ids: { study_id: 'study-1', goal_revision: 3 }, metadata: { objective: 'Moonlit canal' } }) });
  const usage = { input: 100, output: 20, cacheRead: 5, cacheWrite: 0, reasoning: 7, totalTokens: 125, cost: { input: .1, output: .2, cacheRead: 0, cacheWrite: 0, total: .3 } };
  session.fire({ type: 'agent_start' });
  session.fire({ type: 'message_end', message: { role: 'user', content: [{ type: 'text', text: 'Paint the canal' }, { type: 'image', data: 'AAAA', mimeType: 'image/png' }] } });
  session.fire({ type: 'turn_start' });
  session.fire({ type: 'message_start', message: { role: 'assistant' } });
  session.fire({ type: 'message_end', message: { role: 'assistant', model: 'm', provider: 'openrouter', stopReason: 'toolUse', usage,
    content: [{ type: 'thinking', thinking: 'Block in the sky first.' }, { type: 'toolCall', id: 'c1', name: 'paint_pass', arguments: { layer: 'sky' } }] } });
  session.fire({ type: 'tool_execution_start', toolCallId: 'c1', toolName: 'paint_pass', args: { layer: 'sky' } });
  session.fire({ type: 'tool_execution_end', toolCallId: 'c1', toolName: 'paint_pass', isError: false, result: { content: [{ type: 'text', text: 'painted' }] } });
  session.fire({ type: 'message_end', message: { role: 'toolResult', toolCallId: 'c1', toolName: 'paint_pass', content: [{ type: 'text', text: 'painted' }] } });
  session.fire({ type: 'turn_start' });
  session.fire({ type: 'message_end', message: { role: 'assistant', model: 'm', provider: 'openrouter', stopReason: 'stop', usage, content: [{ type: 'text', text: 'Sky blocked in.' }] } });
  session.fire({ type: 'agent_end' });

  const [root, first, tool, second] = fake.observations;
  assert.equal(root.name, 'paint-goal'); assert.equal(root.options.asType, 'agent');
  assert.equal(root.trace.sessionId, 'study-1'); assert.deepEqual(root.trace.metadata, { study_id: 'study-1', goal_revision: '3' });
  assert.equal(root.attributes.metadata.system_prompt, 'You paint.');
  assert.equal(root.attributes.input[1].image_url.url, 'data:image/png;base64,AAAA');
  assert.equal(root.attributes.output, 'Sky blocked in.'); assert.ok(root.ended);
  assert.equal(first.name, 'choose-next-action'); assert.equal(first.options.asType, 'generation'); assert.equal(first.parent, root);
  assert.equal(first.attributes.output.thinking, 'Block in the sky first.');
  assert.equal(first.attributes.output.tool_calls[0].function.arguments, '{"layer":"sky"}');
  assert.deepEqual(first.attributes.usageDetails, { input: 100, output: 20, cache_read_input_tokens: 5, cache_creation_input_tokens: 0, reasoning_tokens: 7 });
  assert.equal(first.attributes.costDetails.total, .3); assert.ok(first.attributes.completionStartTime instanceof Date);
  assert.ok(first.options.startTime <= first.attributes.completionStartTime); assert.equal(first.trace.sessionId, 'study-1');
  assert.equal(tool.name, 'paint_pass'); assert.equal(tool.options.asType, 'tool'); assert.equal(tool.parent, root);
  assert.deepEqual(tool.attributes.output, ['painted']); assert.ok(tool.ended);
  // The second call's input is what the model newly saw: its own call and the tool result.
  assert.deepEqual(second.attributes.input.map(m => m.role), ['assistant', 'tool']);
  assert.equal(fake.observations.length, 4);
});

test('an unfinished run is closed when the session is untraced, and errors are marked', () => {
  const fake = fakeLangfuse(), session = fakeSession();
  const untrace = new LangfuseTracing({ ...fake }).watchSession(session, { traceName: 'reviewer', generationName: 'judge-canvas' });
  session.fire({ type: 'agent_start' });
  session.fire({ type: 'message_end', message: { role: 'assistant', model: 'm', stopReason: 'error', errorMessage: 'rate limited', content: [] } });
  session.fire({ type: 'tool_execution_start', toolCallId: 't', toolName: 'submit_review', args: {} });
  untrace();
  assert.equal(fake.observations[1].attributes.level, 'ERROR');
  assert.equal(fake.observations[2].attributes.level, 'WARNING');
  assert.ok(fake.observations.every(o => o.ended));
  session.fire({ type: 'agent_start' });
  assert.equal(fake.observations.length, 3);
});

test('tracing failures never reach the painter', () => {
  const session = fakeSession();
  new LangfuseTracing({ tracing: { startObservation: () => { throw new Error('exporter down'); } }, propagateAttributes: (_t, fn) => fn() })
    .watchSession(session, { traceName: 'painter', generationName: 'g' });
  assert.doesNotThrow(() => session.fire({ type: 'agent_start' }));
});

test('secrets are masked and credentials come from env, then the Keychain', async t => {
  assert.equal(maskSecrets('key ' + 'sk-or-v1-' + 'abcdef123456' + ' and custom-secret-value', ['custom-secret-value']), 'key [redacted] and [redacted]');
  assert.deepEqual(maskSecrets({ a: 1 }), { a: 1 });
  // A pair comes whole from one source: a public key here and a secret there is not a pair.
  const keychain = async k => ({ LANGFUSE_PUBLIC_KEY: 'pk-keychain', LANGFUSE_SECRET_KEY: 'sk-keychain' })[k] ?? null;
  assert.equal(await langfuseCredentials({}, async () => null), null);
  assert.equal((await langfuseCredentials({ LANGFUSE_PUBLIC_KEY: 'pk-env' }, keychain)).LANGFUSE_PUBLIC_KEY, 'pk-keychain');
  const fromEnv = await langfuseCredentials({ LANGFUSE_PUBLIC_KEY: 'pk-env', LANGFUSE_SECRET_KEY: 'sk-env', LANGFUSE_HOST: 'https://x' }, keychain);
  assert.deepEqual(fromEnv, { LANGFUSE_PUBLIC_KEY: 'pk-env', LANGFUSE_SECRET_KEY: 'sk-env', LANGFUSE_BASE_URL: 'https://x', source: 'environment' });
  // The project's .env wins over a stale shell environment.
  const dir = await mkdtemp(join(tmpdir(), 'lf-env-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(join(dir, '.env'), 'LANGFUSE_SECRET_KEY="sk-file"\nexport LANGFUSE_PUBLIC_KEY=\'pk-file\'\r\nLANGFUSE_BASE_URL=https://cloud.langfuse.com # EU\n');
  const fromFile = await langfuseCredentials({ LANGFUSE_PUBLIC_KEY: 'pk-env', LANGFUSE_SECRET_KEY: 'sk-env' }, keychain, join(dir, '.env'));
  assert.deepEqual(fromFile, { LANGFUSE_PUBLIC_KEY: 'pk-file', LANGFUSE_SECRET_KEY: 'sk-file', LANGFUSE_BASE_URL: 'https://cloud.langfuse.com', source: '.env' });
  assert.equal((await langfuseCredentials({}, async () => null, join(dir, 'missing.env'))), null);
  // Mandatory: no opt-out, and missing or rejected credentials stop the chat with a clear reason.
  await assert.rejects(connectLangfuse({ env: { CREATIVE_AGENT_TRACING: 'off' }, keychain: async () => null }), LangfuseConnectionError);
});

test('chat messages use the OpenAI shape Langfuse renders', () => {
  assert.deepEqual(chatMessage({ role: 'user', content: 'hi' }), { role: 'user', content: 'hi' });
  assert.deepEqual(chatMessage({ role: 'toolResult', toolCallId: 'c', toolName: 'observe', content: [{ type: 'image', data: 'B', mimeType: 'image/jpeg' }] }),
    { role: 'tool', tool_call_id: 'c', name: 'observe', content: [{ type: 'image_url', image_url: { url: 'data:image/jpeg;base64,B' } }] });
});

test('Luna decisions are traced as generations named by purpose', async () => {
  const calls = [];
  const tracing = { observeGeneration: async (name, info, call, finish) => { const r = await call(); calls.push({ name, info, update: finish(r) }); return r; } };
  const fetch = async () => new Response(JSON.stringify({ answers: { q: { type: 'boolean', value: true } }, usage: { input_tokens: 9, output_tokens: 1, cost: .001 } }));
  const client = new LunaClient({ apiKey: 'k', fetch, tracing, context: () => ({ sessionId: 'study-1', tags: ['luna'] }) });
  const result = await client.decide({ parts: ['canvas'], questions: { q: { type: 'boolean' } }, purpose: 'route-request' });
  assert.equal(result.answers.q.value, true);
  assert.equal(calls[0].name, 'decision-route-request'); assert.equal(calls[0].info.sessionId, 'study-1');
  assert.deepEqual(calls[0].update.usageDetails, { input: 9, output: 1 }); assert.equal(calls[0].update.costDetails.total, .001);
  const offline = new LunaClient({ apiKey: null, tracing });
  assert.equal((await offline.decide({ questions: {} })).fallback, 'not_connected'); assert.equal(calls.length, 1);
});

test('.env parsing matches the shell for quoted, exported and commented values', () => {
  assert.deepEqual(parseDotEnv('A="x y" # c\nexport B=\'q\'\nC=plain # comment\n# skip\nD=a#b\nE=\n'),
    { A: 'x y', B: 'q', C: 'plain', D: 'a#b', E: '' });
});

test('decision records have stable ids, bounded text state and leak-free review rows', async () => {
  const { decisionId, boundedState, reviewCheckDecision, hardGraphicDecision } = await import('../src/decision-records.mjs');
  assert.equal(decisionId('chat', 'review-check', 2, 'check-1'), 'chat:review-check:2:check-1');
  assert.throws(() => decisionId('chat', 'nonsense'));
  assert.ok(JSON.stringify(boundedState({ objective: 'x'.repeat(5000), recent_operations: Array(50).fill({ kind: 'paint' }) })).length <= 1600);
  const d = reviewCheckDecision({ chatId: 'c', reviewIndex: 0, review: { revision: 2, at: '2026-10-09T00:00:00Z' }, check: { id: 'check-0', met: false, evidence: 'The fence is missing.' }, statement: 'A fence crosses the field.', imageDataUrl: 'data:image/png;base64,AA' });
  assert.deepEqual(d.answers.met.noul, 0); assert.equal(d.images.length, 1);
  assert.ok(!JSON.stringify(d.state).includes('fence is missing'), 'evidence stays out of the state');
  const h = hardGraphicDecision({ chatId: 'c', observationId: 'o1', probability: .82, images: ['data:a', 'data:b'] });
  assert.equal(h.decision_id, 'c:pass-failures:o1:hard_graphic'); assert.equal(h.answered_by, 'luna');
});

test('a decision is one event trace whose id derives from the decision id; verdicts score that trace', async () => {
  const tracing = recordingTracing();
  tracing.tracing.createTraceId = async seed => 'trace-for-' + seed;
  const decision = { decision_id: 'c:pass-keep:p1', kind: 'pass-keep', state: {}, questions: { keep: { type: 'noul' } }, images: [], answers: null, answered_by: null };
  const traceId = await tracing.recordDecision(decision, { sessionId: 'c' });
  const [event] = tracing.recorded.observations;
  assert.equal(traceId, 'trace-for-c:pass-keep:p1'); assert.equal(event.name, 'decide-pass-keep'); assert.equal(event.options.asType, 'event');
  assert.equal(event.options.parentSpanContext.traceId, traceId); assert.equal(event.trace.sessionId, 'c');
  await tracing.scoreDecision('c:pass-keep:p1', { value: false, comment: 'Reject pass' });
  assert.deepEqual(tracing.recorded.scores.map(s => [s.traceId, s.name, s.value]), [[traceId, 'artist-verdict', 0]]);
});
