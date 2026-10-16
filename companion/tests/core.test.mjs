import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Value } from 'typebox/value';
import { containedFile, imageInfo, splitJsonLines } from '../src/files.mjs';
import { paintingTools } from '../src/tools.mjs';
import { PaintingRuntime } from '../src/runtime.mjs';

test('JSON protocol preserves Unicode separators inside a message', () => {
  const text = '{"text":"one\u2028two"}\n{"type":"stop"}\npartial';
  const result = splitJsonLines(text);
  assert.equal(result.lines.length, 2);
  assert.equal(JSON.parse(result.lines[0]).text, 'one\u2028two');
  assert.equal(result.rest, 'partial');
});

test('image output cannot escape a study through a symlink', async () => {
  const root = await mkdtemp(join(tmpdir(), 'creative-path-'));
  try {
    await mkdir(join(root, 'study'));
    await writeFile(join(root, 'private.png'), 'private');
    await symlink(join(root, 'private.png'), join(root, 'study', 'image.png'));
    await assert.rejects(containedFile(join(root, 'study'), join(root, 'study', 'image.png')), /outside/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('painting schemas reject misspelled fields and oversized batches', () => {
  const tools = paintingTools({});
  assert.ok(tools.every(tool => tool.executionMode === 'sequential'));
  const schema = tools.find(t => t.name === 'paint_pass').parameters;
  const stroke = { start: [10, 20], segments: [[20,20,30,20,40,20]], size: 20, opacity: 1, flow: 1, color: '#abc123' };
  const pass = { name: 'Study', preset: 'b) Basic-1', strokes: [stroke] };
  assert.equal(Value.Check(schema, pass), true);
  assert.equal(Value.Check(schema, {...pass,strokes:Array(100).fill(stroke)}),true);
  assert.equal(Value.Check(schema, { ...pass, brush: 'Basic' }), false);
  assert.equal(Value.Check(schema, { ...pass, strokes: Array(257).fill(stroke) }), false);
  assert.equal(Value.Check(schema, { ...pass, strokes: [{ ...stroke, pressure: 1 }] }), false);
});

test('a second companion cannot acquire a live owner’s lock', async () => {
  const output = await mkdtemp(join(tmpdir(), 'creative-lock-'));
  const a = new PaintingRuntime({ config: { output } });
  const b = new PaintingRuntime({ config: { output } });
  try {
    await a.acquireLock();
    await assert.rejects(b.acquireLock(), /already running/);
    await a.releaseLock();
    await b.acquireLock();
  } finally { await b.releaseLock(); await rm(output, { recursive: true, force: true }); }
});

test('provider credentials are redacted from reported errors', () => {
  const runtime = new PaintingRuntime({});
  runtime.secrets.push('test-credential-value');
  assert.equal(runtime.redact('Failed test-credential-value'), 'Failed [redacted]');
});

test('a silent model is stopped and its error remains visible', async () => {
  const events = [];
  const runtime = new PaintingRuntime({config: {model_idle_timeout_ms: 50}, emit: e => events.push(e)});
  let finish;
  let aborted = 0;
  runtime.busy = true;
  runtime.session = { prompt: () => new Promise(resolve => { finish = resolve; }), agent: {
    clearAllQueues() {}, abort() { aborted++; finish(); },
  }};
  const run = runtime.runPrompt('Inspect');
  runtime.checkModelWait(Date.now() + 51);
  await run;
  assert.equal(aborted, 1);
  assert.equal(events.at(-1).phase, 'error');
  assert.match(events.at(-1).message, /stopped responding/);
});

test('native painting is excluded from the model silence timeout', () => {
  const runtime = new PaintingRuntime({config: {model_idle_timeout_ms: 50}, emit() {}});
  runtime.busy = true; runtime.activity = 'painting'; runtime.lastModelActivityAt = 0;
  runtime.session = {agent: {abort() { throw new Error('must not interrupt native painting'); }}};
  runtime.checkModelWait(5000);
  assert.equal(runtime.cancelRequested, false);
});

test('provider errors are not overwritten with a ready message', async () => {
  const events = [];
  const runtime = new PaintingRuntime({config: {}, emit: e => events.push(e)});
  runtime.session = {prompt: async () => runtime.onEvent({type: 'message_end', message: {
    role: 'assistant', stopReason: 'error', errorMessage: 'Provider unavailable',
  }})};
  await runtime.runPrompt('Inspect');
  assert.equal(events.at(-1).phase, 'error');
  assert.equal(events.at(-1).message, 'Provider unavailable');
});
