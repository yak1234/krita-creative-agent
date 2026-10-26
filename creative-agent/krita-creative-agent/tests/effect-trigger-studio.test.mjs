// When a build starts, in a chat (studio.mjs hooks; the rules are tested in effect-failures.test.mjs): after each Agent move
// that painted an effect, a token effort by its counts or one Luna "effect met" decision, off the move's path; the second
// failure of one effect says the enable hint once (Custom effects off) or starts a build the moves never wait for (on);
// /new-effect builds at once. A local model server, a fake bridge and a fake Luna (no network), as
// paint-only-here-studio.test.mjs. Waits poll the real state with a deadline. Every test removes its folder.
import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { StudioRuntime, EFFECTS_HINT } from '../src/studio.mjs';
import { encodeRgba } from '../src/shapes/png.ts';

const call = (name, args) => ({ tool_calls: [{ index: 0, id: 'call-' + Math.random().toString(36).slice(2), type: 'function', function: { name, arguments: JSON.stringify(args) } }] });
const png = encodeRgba({ width: 64, height: 48, data: new Uint8Array(64 * 48 * 4).fill(120) });
const fill = { name: 'Rain', area: [{ shape: 'rectangle', bounds: [0, 0, 200, 100] }], color: '#506080' };
const stroke = i => ({ start: [10 + i * 5, 10], segments: [[12 + i * 5, 20, 14 + i * 5, 30, 16 + i * 5, 40]], size: 4, opacity: 0.8, flow: 0.8, color: '#ffffff' });

/** Polls `condition` until it holds, or fails the test after `ms`. */
async function until(condition, what, ms = 10000) {
  const deadline = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error('Timed out waiting for ' + what);
    await new Promise(r => setTimeout(r, 5));
  }
}

async function chat({ customEffects, met, routing = 'evaluate', respond = null }) {
  const output = await mkdtemp(join(tmpdir(), 'effect-trigger-studio-'));
  const events = [], judged = [], diagnostics = [], purposes = [];
  // The painter: each move paints once (a fill, or 12 strokes when `token` is set), then finish_move, then stops.
  const painting = { token: false };
  const painter = req => {
    const start = req.messages.findLastIndex(m => m.role === 'user' && JSON.stringify(m.content).includes('Artist:'));
    const called = req.messages.slice(start + 1).flatMap(m => m.tool_calls ?? []).map(c => c.function.name);
    const strokes = { name: 'Snow', preset: 'Test brush', strokes: Array.from({ length: 12 }, (_, i) => stroke(i)) };
    if (!called.length && painting.token === 'layer') return call('paint_batch', { actions: [{ tool: 'create_layer', arguments: { name: 'Snow', type: 'paint' } }, { tool: 'paint_pass', arguments: strokes }] });
    if (!called.length) return painting.token ? call('paint_pass', strokes) : call('fill_region', fill);
    return called.length === 1 ? call('finish_move', { summary: 'Painted the request' }) : { content: 'Done.' };
  };
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const request = JSON.parse(body);
    const delta = respond?.(request) ?? (request.tools?.some(t => t.function.name === 'paint_batch') ? painter(request) : { content: 'Hello.' });
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
    if (operation === 'context') return { document_id: 'doc', active_document_id: 'doc', name: 'Untitled', filename: '', width: 800, height: 600, modified: true, revision: 'revision-0' };
    if (operation === 'list_brushes') return { brushes: [{ name: 'Test brush' }] };
    if (['begin', 'peek'].includes(operation)) {
      const path = join(params.output_dir, 'view.png'); await writeFile(path, png);
      observation = { status: 'ok', document_id: 'doc', name: 'Untitled', filename: '', modified: true, width: 800, height: 600, image_path: path, layers: [], revision: 'revision-0', content_id: 'content-0', captured_at: new Date().toISOString(),
        ...(operation === 'begin' ? { checkpoint: params.painting_path ?? join(params.output_dir, 'painting.kra') } : {}) };
      if (operation === 'begin') await writeFile(observation.checkpoint, 'test painting');
    }
    return operation === 'end' ? { status: 'ok' } : observation;
  } };
  const capabilities = { async initialize() {}, status() { return { status: 'verified', route_verified: true, images_supported: true, tools_supported: true }; }, async verify() { return { route_verified: true, cached: true }; }, async invalidate() {} };
  const runtime = new StudioRuntime({ defaultPlanner: null, sharpenModel: { download: async () => { throw new Error('No model downloads in tests.'); }, service: { upscale: async () => { throw new Error('No sharpening in tests.'); } } },
    root: output, config: { output }, models, bridge, capabilities, tracing: recordingTracing(), emit: e => events.push(e) });
  const goal = join(output, 'final_goal.png'); await writeFile(goal, png);
  await runtime.start({ provider: 'local-test', model: 'vision-test', chat_mode: 'ask', prompt: 'Hello', mode: 'copy', references: [{ path: goal, purpose: 'general' }] });
  await runtime.setExecutionSettings({ routing, reference_first: false, custom_effects: customEffects });
  await runtime.setMode('agent');
  runtime.diagnostics = { record: e => diagnostics.push(e) };
  // Luna: only the "effect met" decision answers (the others, the request reading included, fall back as offline).
  runtime.lunaClient = { connected: true, async decide(request) {
    purposes.push(request.purpose);
    if (request.purpose !== 'effect-met') return { fallback: 'not_connected', elapsed_ms: 0 };
    judged.push(request);
    const noul = await met(judged.length);
    return noul === null ? { fallback: 'timeout', elapsed_ms: 4000 } : { answers: { met: { type: 'noul', noul } }, model: 'luna', elapsed_ms: 1, usage: { input_tokens: 1, output_tokens: 1, cost: 0 } };
  } };
  const of = type => diagnostics.filter(d => d.type === type);
  const h = { runtime, events, judged, diagnostics, painting, of, purposes,
    failures: effect => runtime.effectLog().failures.failures(effect),
    hints: () => events.filter(e => e.type === 'action' && e.message === EFFECTS_HINT).length,
    /** The build checks after the last move are over: it was judged, and every due failure started or skipped a build. */
    async settled() {
      const number = runtime.goal.moves.at(-1)?.number;
      await until(() => of('effect_judged').some(d => d.move === number), `move ${number} judged`);
      await until(() => of('effect_failed').filter(d => d.due).length === of('effect_build_started').filter(d => d.source === 'failures').length + of('effect_build_skipped').length, 'the due builds to start or be skipped');
    },
    /** A move, and the checks after it. */
    async move(text) { await runtime.prompt(text); await h.settled(); },
    async close() { if (runtime.busy) runtime.stop(); await runtime.writeQueue; await runtime.end().catch(() => {}); runtime.dispose(); server.closeAllConnections(); await new Promise(r => server.close(r)); await rm(output, { recursive: true, force: true }); } };
  return h;
}

test('off: no Luna for custom effects, and the second failure says the enable hint once', { timeout: 60000 }, async () => {
  // Decision checks on, Custom effects off: the words, redos and token efforts only.
  const h = await chat({ customEffects: false, met: () => 0.1 });
  try {
    let built = 0; h.runtime.startEffectBuild = async () => { built++; };
    h.painting.token = true;
    await h.move('Add rain over the street');
    assert.equal(h.failures('rain'), 1, 'a token effort');
    assert.equal(h.hints(), 0, 'one failure: nothing said');
    await h.move('Paint the lamp posts darker');
    await h.move('Add a downpour');
    assert.equal(h.hints(), 1, 'the second failure of rain: the hint');
    await h.move('More rain, heavier');
    assert.equal(h.hints(), 1, 'once a chat');
    assert.deepEqual(h.purposes.filter(p => /^effect-/.test(p)), [], 'no effect-asked, no effect-met');
    assert.equal(h.judged.length, 0);
    assert.equal(built, 0, 'off: never a build');
    await h.runtime.prompt('/new-effect rain');
    assert.equal(h.hints(), 2, '/new-effect off answers with the hint');
    assert.equal(built, 0);
  } finally { await h.close(); }
});

test('on, with Luna: one decision after an effect move, and its verdict decides over the stroke count', { timeout: 60000 }, async () => {
  const verdicts = [0.9, null, 0.1];
  const h = await chat({ customEffects: true, met: n => verdicts[n - 1] });
  try {
    h.runtime.startEffectBuild = async () => {};
    h.painting.token = true;                                       // 12 strokes every move
    await h.move('Add a wisp of smoke from the chimney');
    assert.equal(h.judged.length, 1, 'one Luna decision after the move');
    assert.equal(h.judged[0].questions.met.type, 'noul');
    assert.match(h.judged[0].parts[0], /a wisp of smoke/, 'with the request');
    assert.equal(h.judged[0].parts.filter(p => typeof p === 'object').length, 2, 'and the canvas before and after');
    assert.equal(h.of('effect_judged').at(-1).outcome, 'met');
    assert.equal(h.failures('smoke'), 0, 'few strokes, met: no failure');
    await h.move('Paint the lamp posts darker');
    assert.equal(h.judged.length, 1, 'a request without an effect is not judged');
    assert.ok(h.purposes.includes('effect-asked'), 'Luna was asked which effect (it fell back to the words here)');
    await h.move('Add smoke over the factory');
    assert.equal(h.of('effect_judged').at(-1).outcome, 'token_effort', 'Luna could not answer: the counts decide');
    assert.equal(h.failures('smoke'), 1);
    await h.move('Paint the sky bluer');
    await h.move('Add smoke from the train');
    assert.equal(h.of('effect_judged').at(-1).outcome, 'not_met');
    assert.deepEqual(h.of('effect_build_started').map(d => d.effect), ['smoke'], 'the second failure builds (and uses up both)');
  } finally { await h.close(); }
});

test('on: the second failure starts a build and the next move starts without waiting', { timeout: 60000 }, async () => {
  // Luna fails once (no failure), then says not met.
  const h = await chat({ customEffects: true, met: n => n === 1 ? null : 0.1 });
  try {
    const builds = [];
    h.runtime.startEffectBuild = (effect, request) => { builds.push({ effect, request }); return new Promise(() => {}); };   // never ends
    await h.move('Add rain over the street');
    assert.equal(h.failures('rain'), 0, 'a Luna failure is not a failure');
    // A move between, so these are Luna's failures, not redos.
    await h.move('Paint the lamp posts darker');
    await h.move('Add rain over the square');
    assert.equal(builds.length, 0, 'once is not enough');
    await h.move('Paint the sky bluer');
    await h.move('Add rain on the river');
    await until(() => builds.length === 1, 'the build');
    assert.deepEqual(builds, [{ effect: 'rain', request: 'Add rain on the river' }], 'the second failure builds');
    assert.equal(h.runtime.effectLog().failures.building, 'rain');
    const moves = h.runtime.goal.moves.length;
    await h.move('Add drizzle to the windows');      // the build never ends: the move must not wait for it
    assert.equal(h.runtime.goal.moves.length, moves + 1, 'the next move started and ended');
    assert.equal(builds.length, 1, 'one build at a time');
    assert.equal(h.hints(), 0, 'on: no hint');
    await h.runtime.prompt('/new-effect smoke');
    assert.ok(h.events.some(e => e.type === 'action' && /being built already \(rain\)/.test(e.message)));
    assert.equal(builds.length, 1, '/new-effect waits its turn too');
  } finally { await h.close(); }
});

test('a build belongs to its chat: ending the chat stops it, its card never reaches the next chat, and one build at a time holds across chats', { timeout: 60000 }, async () => {
  const h = await chat({ customEffects: true, met: () => 0.9 });
  try {
    const runs = [];
    h.runtime.effectBuild.start = (effect, request, run) => new Promise(resolve => runs.push({ effect, run, resolve }));   // ends when told
    const first = h.runtime.study, firstGoal = h.runtime.goal;
    await h.runtime.prompt('/new-effect rain');
    await until(() => runs.length === 1, 'the build');
    const [{ run }] = runs;
    assert.equal(run.host.study, first, 'the chat it started in');
    assert.equal(run.signal.aborted, false);
    firstGoal.limits = { ...(firstGoal.limits ?? {}), ai_images: null };      // this chat allows AI images
    await h.runtime.end();
    assert.equal(run.signal.aborted, true, 'ending the chat stops its build');
    assert.equal(run.host.study, first, 'still that chat, not the live one');
    assert.doesNotThrow(() => run.host.allowance(), 'the allowance of the chat it started in, not of no chat');
    // A new chat: the old build's card and words never reach it.
    const goal = join(h.runtime.config.output, 'goal-2.png'); await writeFile(goal, png);
    await h.runtime.start({ provider: 'local-test', model: 'vision-test', chat_mode: 'ask', prompt: 'Hello', mode: 'copy', references: [{ path: goal, purpose: 'general' }] });
    const before = h.events.length;
    run.host.emit({ type: 'effect_build', id: 'old', title: 'Custom effect', message: 'm', options: ['Keep'], actions: ['keep'] });
    run.host.emit({ type: 'action', seconds: 0, message: 'The effect build for “rain” failed.' });
    assert.deepEqual(h.events.slice(before), [], 'nothing from the old chat\'s build');
    // The old build has not ended yet: one build at a time, across chats.
    await h.runtime.prompt('/new-effect smoke');
    assert.ok(h.events.slice(before).some(e => e.type === 'action' && /being built already \(rain\)/.test(e.message)));
    assert.equal(runs.length, 1);
    runs[0].resolve(null);
    await until(() => h.of('effect_build_ended').length === 1, 'the old build to end');
    await h.runtime.prompt('/new-effect smoke');
    await until(() => runs.length === 2, 'the new chat\'s build');
    assert.equal(runs[1].run.host.study, h.runtime.study);
    runs[1].resolve(null);
  } finally { await h.close(); }
});

test('Autopilot cycles are judged as moves are: 12 strokes for falling snow is a token effort', { timeout: 60000 }, async () => {
  // The artist ruled builds run in Autopilot too (with Auto-approve): its cycles record failures by the same gates.
  const brief = { title: 'Snow', objective: 'A snowy square.', requirements: ['Snow falls over the square.'], freedom: [],
    steps: [{ title: 'Falling snow over the square', done_when: 'Snow falls everywhere.' }], completion: ['Snow is visible.'] };
  let painted = false;
  const h = await chat({ customEffects: false, met: () => 0.9, routing: 'off', respond: req => {
    const names = (req.tools ?? []).map(t => t.function.name);
    if (names.includes('propose_plan')) return call('propose_plan', brief);
    if (names.includes('submit_review')) return call('submit_review', { verdict: 'complete', summary: 'Done.', issues: [], checks: [0, 1].map(i => ({ id: 'check-' + i, met: true, evidence: 'Visible.' })) });
    if (names.includes('paint_pass') && names.includes('request_review')) {
      if (!painted) { painted = true; return call('paint_pass', { name: 'Snow', preset: 'Test brush', strokes: Array.from({ length: 12 }, (_, i) => stroke(i)) }); }
      return call('request_review', { reason: 'Painted.' });
    }
    return null;
  } });
  try {
    await h.runtime.setMode('plan'); await h.runtime.prompt('Plan falling snow over the square.');
    assert.ok(h.runtime.goal.brief, 'planned');
    await h.runtime.setMode('autopilot'); await h.runtime.prompt('', { start_plan: true });
    assert.ok(painted, 'the cycle painted');
    await until(() => h.of('effect_judged').length > 0, 'the cycle judged');
    assert.equal(h.of('effect_judged')[0].outcome, 'token_effort');
    assert.equal(h.failures('snow'), 1);
    assert.equal(h.judged.length, 0, 'Decision checks off: nothing went to Luna');
  } finally { await h.close(); }
});

test('a slow "effect met" decision does not hold the move', { timeout: 60000 }, async () => {
  let answer;
  const h = await chat({ customEffects: true, met: () => new Promise(resolve => { answer = resolve; }) });
  try {
    await h.runtime.prompt('Add rain over the street');
    await until(() => h.judged.length === 1, 'the decision to be asked');
    const idle = h.events.filter(e => e.type === 'status' && e.phase === 'idle' && /Move 1 painted/.test(e.message));
    assert.equal(idle.length, 1, 'the move ended and said so while Luna was still deciding');
    assert.equal(h.runtime.busy, false);
    assert.equal(h.of('effect_judged').length, 0, 'not judged yet');
    answer(0.1);
    await h.settled();
    assert.equal(h.failures('rain'), 1, 'judged when Luna answers');
  } finally { answer?.(0.9); await h.close(); }
});

test('a token effort counts as a failure without Luna; a substantial move does not', { timeout: 60000 }, async () => {
  const h = await chat({ customEffects: false, met: () => 0.9, routing: 'off' });
  try {
    await h.move('Add snow falling over the square');          // a fill: substantial
    assert.equal(h.failures('snow'), 0);
    assert.deepEqual(h.of('effect_judged').at(-1), { type: 'effect_judged', move: 1, outcome: 'not_judged' }, 'Decision checks off: no Luna');
    h.painting.token = true;
    await h.move('Paint the lamps darker');
    await h.move('Add snow falling on the street');            // 12 strokes and done: the live snow test
    assert.equal(h.runtime.goal.moves.at(-1).strokes, 12);
    assert.equal(h.of('effect_judged').at(-1).outcome, 'token_effort');
    assert.equal(h.failures('snow'), 1);
    assert.equal(h.judged.length, 0, 'nothing went to Luna');
    await h.move('Paint the sky bluer');
    await h.move('Snow over the rooftops please');
    assert.equal(h.failures('snow'), 2);
    assert.equal(h.hints(), 1, 'off: two token efforts say the hint');
  } finally { await h.close(); }
});

test('a new layer and 12 strokes for falling snow is a token effort (the live snow failure)', { timeout: 60000 }, async () => {
  const h = await chat({ customEffects: false, met: () => 0.9, routing: 'off' });
  try {
    h.painting.token = 'layer';                                // create_layer, then 12 dashes: a layer is not paint
    await h.move('Add falling snow over the square');
    assert.equal(h.runtime.goal.moves.at(-1).strokes, 12);
    assert.equal(h.of('effect_judged').at(-1).outcome, 'token_effort');
    assert.equal(h.failures('snow'), 1);
  } finally { await h.close(); }
});

test('after a build, it takes two new failures to build again', { timeout: 60000 }, async () => {
  const h = await chat({ customEffects: true, met: () => 0.1 });
  try {
    const builds = [];
    h.runtime.startEffectBuild = async effect => { builds.push(effect); };     // settles at once, no Discard
    for (const text of ['Add rain over the street', 'Paint the lamps darker', 'Add rain over the square']) await h.move(text);
    await until(() => h.of('effect_build_ended').length === 1, 'the build to settle');
    assert.deepEqual(builds, ['rain']);
    assert.equal(h.runtime.effectLog().failures.building, null);
    await h.move('Paint the sky bluer');
    await h.move('Add rain on the river');
    assert.equal(h.failures('rain'), 1, 'its failures were used up by the build');
    assert.deepEqual(builds, ['rain'], 'one more failure does not build again');
    await h.move('Paint the door green');
    await h.move('Add rain over the bridge');
    await until(() => builds.length === 2, 'the second build');
    assert.deepEqual(builds, ['rain', 'rain'], 'two do');
  } finally { await h.close(); }
});

test('on: a redo of an effect the painter called done counts; an Undo alone does not; a library effect is not built', { timeout: 60000 }, async () => {
  const h = await chat({ customEffects: true, met: () => 0.9 });     // Luna says met every time
  try {
    const builds = [];
    h.runtime.startEffectBuild = async (effect, request) => { builds.push({ effect, request }); };
    await h.move('Add rain over the street');
    const first = h.runtime.goal.moves.at(-1);
    assert.equal(first.finished, true);
    await h.runtime.moveAction({ action: 'undo', move: first.number });     // Undo: the move is retried, nothing counts
    await h.settled();
    assert.equal(h.failures('rain'), 0, 'an Undo alone does not count');
    assert.equal(h.runtime.goal.moves.at(-1).effect_request, 'Add rain over the street', 'the retry repaints the same request');
    await h.move('Rain again, I can barely see it');                // a redo of the retry, called done
    assert.equal(h.failures('rain'), 1);
    await h.move('Still more rain please');                         // and again
    await until(() => builds.length === 1, 'the build');
    assert.deepEqual(builds.map(b => b.effect), ['rain']);
    // A library effect (fog) failing twice is used, not built.
    for (const text of ['Add fog over the river', 'More fog, it is not there', 'Even more fog']) await h.move(text);
    assert.ok(h.failures('fog') >= 2);
    assert.deepEqual(h.of('effect_build_skipped').map(d => d.library), ['fog']);
    assert.deepEqual(builds.map(b => b.effect), ['rain'], 'fog is in the library');
    // After Discard the effect is not built again; /new-effect builds it at once.
    h.runtime.effectLog().failures.discarded('rain');
    for (const text of ['Rain once more', 'Rain, again', 'Rain, a third time']) await h.move(text);
    assert.ok(h.failures('rain') >= 2);
    assert.equal(h.of('effect_failed').filter(d => d.effect === 'rain').at(-1).due, false, 'discarded: not due');
    assert.deepEqual(builds.map(b => b.effect), ['rain'], 'discarded: not built again');
    await h.runtime.prompt('/new-effect rain');
    await until(() => builds.length === 2, '/new-effect\'s build');
    assert.deepEqual(builds.map(b => b.effect), ['rain', 'rain'], '/new-effect builds it even after Discard');
  } finally { await h.close(); }
});
