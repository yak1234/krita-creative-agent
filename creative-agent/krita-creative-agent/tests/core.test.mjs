import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Value } from 'typebox/value';
import { containedFile, imageInfo, splitJsonLines } from '../src/files.mjs';
import { paintingTools } from '../src/tools.mjs';
import { PaintingRuntime } from '../src/runtime.mjs';
import { CRAFT_TOOLS, CRAFT_OPERATIONS } from '../src/craft.mjs';

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
  assert.equal(Value.Check(schema, { ...pass, strokes: [{ ...stroke, pressure: 1 }] }), false, 'pressure is per point, not one number');
  assert.equal(Value.Check(schema, { ...pass, strokes: [{ ...stroke, pressure: [0.2, 0.9] }] }), true, 'pen pressure at the start and each segment end');
  assert.equal(Value.Check(schema, { ...pass, strokes: [{ ...stroke, pressure: [0.2, 1.5] }] }), false);
  const pen = { tilt: [[0, 0], [45, -20]], rotation: [-90, 180], speed: [0, 1], time_ms: [0, 250] };
  assert.equal(Value.Check(schema, { ...pass, strokes: [{ ...stroke, ...pen }] }), true, 'tilt, rotation, speed and time per point, as pressure');
  for (const [field, value] of [['tilt', [[0, 0], [61, 0]]], ['tilt', [0, 45]], ['tilt', [[0, 0], [0]]], ['rotation', [0, 181]],
    ['speed', [0, 1.2]], ['time_ms', [0, -1]], ['speed', 0.5]]) {
    assert.equal(Value.Check(schema, { ...pass, strokes: [{ ...stroke, [field]: value }] }), false, `${field} ${JSON.stringify(value)}`);
  }
  const props = schema.properties.strokes.items.properties;
  for (const field of ['tilt', 'rotation', 'speed', 'time_ms']) assert.ok(props[field].description.length < 260, `${field} is described briefly`);
  assert.equal(Value.Check(schema, { ...pass, strokes: [{ ...stroke, start: [-150, -60] }] }), true, 'an edge-to-edge stroke starts off the canvas; the plugin allows one brush size');
});

test('a selection step can be a seed, as a magic wand', () => {
  const schema = paintingTools({}).find(t => t.name === 'select').parameters;
  assert.equal(Value.Check(schema, { name: 'Sky', steps: [{ seed: [3000, 20], tolerance: 30, bounds: [0, 0, 6000, 1400] }] }), true);
  assert.equal(Value.Check(schema, { name: 'Sky', steps: [{ seed: [3000.5, 20] }] }), false, 'whole pixels');
  assert.match(schema.properties.steps.description, /seed/);
});

test('krita_action runs a vetted Krita menu command on a layer', () => {
  const tool = paintingTools({}).find(t => t.name === 'krita_action');
  assert.equal(Value.Check(tool.parameters, { action: 'mirrorNodeX', target: 'L1' }), true);
  assert.equal(Value.Check(tool.parameters, { action: 'selectopaque', target: 'L1', save_as: 'Car', selection: 'Street' }), true);
  assert.equal(Value.Check(tool.parameters, { action: 'mirrorNodeX' }), false, 'a target layer');
  assert.match(tool.description, /krita_capabilities/);
  assert.ok(CRAFT_TOOLS.includes('krita_action') && CRAFT_OPERATIONS.includes('krita_action'));
});

test('clone_layer makes a live copy of any layer, optionally offset', () => {
  const tool = paintingTools({}).find(t => t.name === 'clone_layer');
  assert.equal(Value.Check(tool.parameters, { source: 'L1', name: 'Lamp post 2', offset: [400, 0], blend_mode: 'multiply', opacity: 0.5 }), true);
  assert.equal(Value.Check(tool.parameters, { source: 'L1' }), false, 'a name');
  assert.equal(Value.Check(tool.parameters, { source: 'L1', name: 'X', offset: [400] }), false, '[dx, dy]');
  assert.match(tool.description, /follows/);
  assert.ok(CRAFT_TOOLS.includes('clone_layer') && CRAFT_OPERATIONS.includes('clone_layer'));
});

test('split_by_color finds the painting\u2019s colour regions as saved selections', () => {
  const tool = paintingTools({}).find(t => t.name === 'split_by_color');
  assert.equal(Value.Check(tool.parameters, { source: 'visible', colors: 8, region: [0, 0, 6000, 1400], min_area: 5000 }), true);
  assert.equal(Value.Check(tool.parameters, { source: 'L1', as_layers: true, name_prefix: 'Street' }), true);
  assert.equal(Value.Check(tool.parameters, { source: 'visible', colors: 30 }), false, '2-24 colours');
  assert.match(tool.description, /not objects/);
  assert.ok(CRAFT_TOOLS.includes('split_by_color'));
});

test('apply_filter describes colour to alpha', () => {
  const { description } = paintingTools({}).find(t => t.name === 'apply_filter');
  assert.match(description, /colortoalpha/);
  assert.match(description, /targetcolor/);
  assert.match(description, /threshold/);
  assert.match(description, /clone_layer/, 'the route for the artist\u2019s sketch');
});

test('krita_action is offered only when this Krita has vetted actions', async () => {
  const { StudioRuntime } = await import('../src/studio.mjs');
  const offered = (count, settings = {}) => StudioRuntime.prototype.toolOffered.call({ executionSettings: settings, kritaActions: count, goal: null }, 'krita_action');
  assert.equal(offered(0), false, 'an unaudited Krita: the tool would always refuse');
  assert.equal(offered(13), true);
  assert.equal(offered(13, { native_craft: false }), false);
  const runtime = { emit() {}, listModels: () => [], listProviders: () => [] };
  PaintingRuntime.prototype.acceptBridgeHealth.call(runtime, { protocol_version: 2, krita_actions: 5, capabilities: {} });
  assert.equal(runtime.kritaActions, 5, 'the count comes from Krita\u2019s health check');
});

test('step timings stay out of what the model reads', async () => {
  const { resultContent } = await import('../src/tools.mjs');
  const { content } = await resultContent({}, { status: 'ok', layer_id: 'L1', timings_ms: { apply: 350000, total: 414000 } });
  assert.doesNotMatch(content[0].text, /timings_ms/);
});

test('the action audit keeps only commands that opened no dialog and were undone', async () => {
  const { vetted, CANDIDATES } = await import('../scripts/audit-krita-actions.mjs');
  const kept = vetted([{ id: 'mirrorNodeX', status: 'ok', changed: true, undone: true },
    { id: 'mirrorNodeY', status: 'dialog', changed: false, undone: true },
    { id: 'clear', status: 'ok', changed: true, undone: false },
    { id: 'selectopaque', status: 'missing', changed: false, undone: false },
    { id: 'rotateLayer180', status: 'ok', changed: false, undone: true }]);
  assert.deepEqual(kept.map(e => e.id), ['mirrorNodeX']);
  assert.deepEqual(Object.keys(kept[0]).sort(), ['id', 'kind', 'label', 'needs']);
  assert.ok(!CANDIDATES.some(c => /crop|trim|resize|scale/i.test(c.id)), 'nothing that changes the canvas size');
});

test('the action audit talks to the Krita whose panel config KRITA_CREATIVE_CONFIG names, and lists it under its key', async () => {
  const { auditBridgeConfig, auditTable } = await import('../scripts/audit-krita-actions.mjs');
  const folder = await mkdtemp(join(tmpdir(), 'audit-config-'));
  try {
    const config = join(folder, 'creative-agent-config.json');
    await writeFile(config, JSON.stringify({ bridge_url: 'http://127.0.0.1:5679' }));
    assert.deepEqual(auditBridgeConfig({ KRITA_CREATIVE_CONFIG: config }), { bridge_url: 'http://127.0.0.1:5679' });
    assert.deepEqual(auditBridgeConfig({ KRITA_CREATIVE_CONFIG: join(folder, 'missing.json') }), {});
    const table = auditTable({ '5.3.3 (git 858d352)': [{ id: 'mirrorNodeX' }] },
      { version: 'KritaAgent 6.1.0-prealpha', krita_version: '6.1.0-prealpha (git 6ad1cf6)' }, [{ id: 'clear' }]);
    assert.deepEqual(Object.keys(table), ['5.3.3 (git 858d352)', 'KritaAgent 6.1.0-prealpha'], 'stock’s entry is kept');
    assert.deepEqual(table['KritaAgent 6.1.0-prealpha'], [{ id: 'clear' }]);
  } finally { await rm(folder, { recursive: true, force: true }); }
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

test('select tells the painter it reports straight edges through open paint', () => {
  const select = paintingTools({}).find(t => t.name === 'select');
  assert.match(select.description, /open_edges: straight lines where it cuts through open paint; extend or feather it before painting through it/);
});
