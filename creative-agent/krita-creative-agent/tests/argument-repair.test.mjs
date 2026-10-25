// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Argument repair (src/argument-repair.ts, extensions/argument-repair.ts): tool-call arguments the host puts right before
// validation. The cases are the shapes the artist's chats of 2026-10-23/24 had refused (about 70 calls). Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Type } from 'typebox';
import { Value } from 'typebox/value';
import { repairJsonText, repairArguments, repairBatchActions, withArgumentRepair } from '../src/argument-repair.ts';
import argumentRepair from '../extensions/argument-repair.ts';
import { batchTool } from '../src/tools.mjs';

test('malformed JSON: a missing or stray brace is put right where the parser stopped', () => {
  // An action's own closing brace left out (deepseek, sorted keys): "Expected double-quoted property name".
  const missing = '{"actions": [{"arguments": {"name": "A", "seed": 1, "tool": "paint_recipe"}, {"arguments": {"name": "B"}, "tool": "paint_pass"}], "summary": "s"}';
  const fixed = repairJsonText(missing);
  assert.deepEqual(fixed.actions.map(a => a.arguments.name), ['A', 'B']);
  assert.equal(fixed.summary, 's');
  // Extra closers at the end: "Unexpected non-whitespace character after JSON".
  assert.deepEqual(repairJsonText('{"actions": [{"tool": "paint_pass", "arguments": {}}]}}'), { actions: [{ tool: 'paint_pass', arguments: {} }] });
  // A list closed by "}" (object left open): "Expected ',' or '}' after property value".
  assert.deepEqual(repairJsonText('{"actions": [{"tool": "x", "arguments": {"n": 1}], "summary": "s"}'), { actions: [{ tool: 'x', arguments: { n: 1 } }], summary: 's' });
  // A list left open before the next key: "Expected ',' or ']' after array element".
  assert.deepEqual(repairJsonText('{"strokes": [{"segments": [[1, 2, 3, 4, 5, 6], "size": 5}]}'), { strokes: [{ segments: [[1, 2, 3, 4, 5, 6]], size: 5 }] });
  // Cut short: what is open is closed; inside the actions list the cut-off last action is dropped, and said.
  assert.deepEqual(repairJsonText('{"a": 1, "b": "tex'), { a: 1, b: 'tex' });
  const notes = [];
  assert.deepEqual(repairJsonText('{"actions": [{"tool": "x", "arguments": {}}, {"tool": "y", "arguments": {"strokes": [[1, 2', 16, notes),
    { actions: [{ tool: 'x', arguments: {} }] });
  assert.match(notes.join(), /action 2 was cut off and dropped/);
  // A repair that would move a key out of the actions list changes what the call means: not repaired.
  assert.equal(repairJsonText('{"actions": [{"tool": "a", "arguments": {}}], {"tool": "b", "arguments": {}}]}'), null);
  // Valid JSON, a non-object, and text that is not JSON are not "repaired".
  assert.equal(repairJsonText('{"a": 1}'), null);
  assert.equal(repairJsonText('[1, 2'), null);
  assert.equal(repairJsonText('paint the sky'), null);
});

test('a 2- or 4-number segment is drawn as the same straight line or quadratic curve; pen lists are resampled', () => {
  const notes = [];
  const fixed = repairArguments({ name: 'paint_pass', parameters: Type.Object({ strokes: Type.Array(Type.Any()) }) },
    { strokes: [{ start: [0, 0], segments: [[30, 0], [30, 30, 60, 30]], pressure: [0.2, 0.6, 1, 0.8, 0.3], tilt: [[0, 0], [10, 10]] }] }, notes);
  const [stroke] = fixed.strokes;
  assert.deepEqual(stroke.segments, [[10, 0, 20, 0, 30, 0], [30, 20, 40, 30, 60, 30]], 'a line, then a quadratic from its end as a cubic');
  assert.deepEqual(stroke.pressure, [0.2, 1, 0.3], 'one per point: the start and each segment end');
  assert.equal(stroke.tilt.length, 2, 'one per segment is already allowed');
  assert.equal(notes.length, 2);
  const untouched = { strokes: [{ start: [0, 0], segments: [[1, 2, 3, 4, 5, 6]], pressure: [0.5, 0.5] }] };
  assert.equal(repairArguments({ name: 'paint_pass', parameters: Type.Object({ strokes: Type.Array(Type.Any()) }) }, untouched, []), untouched);
});

test('fields the tool lacks: notes are dropped, JSON strings parsed, long text shortened', () => {
  const pass = { name: 'paint_pass', parameters: Type.Object({ name: Type.String({ maxLength: 20 }), layer_opacity: Type.Optional(Type.Number()),
    area: Type.Optional(Type.Union([Type.Object({ box: Type.Array(Type.Number()) })])) }, { additionalProperties: false }) };
  const notes = [];
  const fixed = repairArguments(pass, { name: 'A long layer name for the sky band', opacity: 0.4, strokes_note: 'x', summary: 'y', area: '{"box": [1, 2, 3, 4]}', mystery: 1 }, notes);
  assert.deepEqual(fixed, { name: 'A long layer name…', opacity: 0.4, area: { box: [1, 2, 3, 4] }, mystery: 1 },
    'opacity is not read as layer_opacity (a stroke\u2019s opacity and the layer\u2019s differ); an unknown field is left for validation');
  assert.ok(fixed.name.length <= 20);
  assert.equal(notes.length, 4);
  const finish = { name: 'finish_move', parameters: Type.Object({ summary: Type.String({ minLength: 1, maxLength: 160 }) }, { additionalProperties: false }) };
  const summary = repairArguments(finish, { summary: 'Underpainting: '.repeat(20) }, []).summary;
  assert.ok(summary.length <= 160 && Value.Check(finish.parameters, { summary }));
});

test('paint_batch actions: the tool name comes out of the arguments, stray fields go in', () => {
  const notes = [];
  const fixed = repairBatchActions({ actions: [{ arguments: { name: 'A', tool: 'paint_recipe' } }, { tool: 'paint_pass', name: 'B', arguments: { tool: 'paint_pass' } }] }, notes);
  assert.deepEqual(fixed.actions, [{ tool: 'paint_recipe', arguments: { name: 'A' } }, { tool: 'paint_pass', arguments: { name: 'B' } }]);
  assert.equal(notes.length, 3);
});

const fakeTool = (name, properties) => ({ name, parameters: Type.Object(properties, { additionalProperties: false }),
  execute: async (_id, args) => ({ content: [{ type: 'text', text: JSON.stringify(args) }], details: { status: 'ok', args } }) });

test('paint_batch names the right tool for one that does not run inside it, and finds an action’s tool from its arguments', async () => {
  const recorded = [];
  const tools = [fakeTool('paint_pass', { name: Type.String(), preset: Type.String(), strokes: Type.Array(Type.Any()), layer_opacity: Type.Optional(Type.Number()) }),
    fakeTool('fill_region', { name: Type.String(), area: Type.Array(Type.Any()), gradient: Type.Optional(Type.Any()) })];
  const batch = batchTool(tools, () => true, async () => {}, notes => recorded.push(...notes));
  assert.throws(() => batch.prepareArguments({ actions: [{ tool: 'paint_accents', arguments: {} }] }),
    /Action 1: paint_accents does not run inside paint_batch\. Call paint_accents on its own[^]*Nothing was painted/);
  const prepared = batch.prepareArguments({ actions: [{ arguments: { name: 'Cloud', area: [], gradient: {} } },
    { tool: 'paint_pass', arguments: { name: 'P', preset: 'b', strokes: [], strokes_note: 'n' } }] });
  assert.equal(prepared.actions[0].tool, 'fill_region', 'the one batch tool whose schema takes these arguments');
  const result = await batch.execute('call-1', prepared);
  assert.equal(JSON.parse(result.content[0].text).status, 'ok');
  assert.ok(recorded.some(n => /tool found from its arguments/.test(n)) && recorded.some(n => /strokes_note dropped/.test(n)));
  // opacity on paint_pass is told, not guessed: a stroke's opacity and the layer's mean different things.
  const told = batch.prepareArguments({ actions: [{ tool: 'paint_pass', arguments: { name: 'P', preset: 'b', strokes: [], opacity: 0.5 } }] });
  await assert.rejects(batch.execute('call-2', told), /paint_pass has no opacity: give each stroke its opacity, or layer_opacity for the whole layer/);
});

test('every tool gets the repair before validation, and a repair is recorded', () => {
  const recorded = [];
  const finish = fakeTool('finish_move', { summary: Type.String({ maxLength: 10 }) });
  const own = { ...fakeTool('own', { n: Type.Number() }), prepareArguments: args => ({ n: Number(args.n) }) };
  withArgumentRepair([finish, own], event => recorded.push(event));
  assert.deepEqual(finish.prepareArguments({ summary: 'Bridge refined at last' }), { summary: 'Bridge…' });
  assert.deepEqual(own.prepareArguments({ n: '3' }), { n: 3 }, 'a tool’s own preparation still runs');
  assert.deepEqual(recorded, [{ type: 'argument_repair', tool: 'finish_move', repairs: ['finish_move: summary shortened from 22 to 10 characters'] }]);
});

test('the extension repairs a tool call whose JSON did not parse, records it and tells the painter once', async () => {
  const handlers = {}, recorded = [];
  argumentRepair({ record: event => recorded.push(event) })({ on: (name, handler) => { handlers[name] = handler; } });
  const raw = '{"actions": [{"tool": "paint_pass", "arguments": {"name": "Sky"}}]}}';
  const message = { role: 'assistant', content: [{ type: 'text', text: 'Painting.' },
    { type: 'toolCall', id: 'c1', name: 'paint_batch', arguments: {}, argumentsError: `Unexpected non-whitespace character after JSON at position 66\n\nReceived arguments:\n${raw}` },
    { type: 'toolCall', id: 'c2', name: 'observe_canvas', arguments: {} }] };
  const replaced = (await handlers.message_end({ type: 'message_end', message })).message;
  assert.deepEqual(replaced.content[1].arguments, { actions: [{ tool: 'paint_pass', arguments: { name: 'Sky' } }] });
  assert.equal('argumentsError' in replaced.content[1], false);
  assert.equal(replaced.content[2], message.content[2]);
  assert.deepEqual(recorded.map(e => [e.type, e.tool, e.call_id]), [['argument_repair', 'paint_batch', 'c1']]);
  const told = await handlers.tool_result({ toolCallId: 'c1', content: [{ type: 'text', text: '{}' }] });
  assert.match(told.content.at(-1).text, /host_repaired[^]*malformed JSON/);
  assert.equal(await handlers.tool_result({ toolCallId: 'c1', content: [] }), undefined, 'once');
  assert.equal(await handlers.message_end({ type: 'message_end', message: { role: 'assistant', content: [{ type: 'text', text: 'ok' }] } }), undefined);
  const hopeless = { role: 'assistant', content: [{ type: 'toolCall', id: 'c3', name: 'paint_batch', arguments: {}, argumentsError: 'Bad\n\nReceived arguments:\npaint it' }] };
  assert.equal(await handlers.message_end({ type: 'message_end', message: hopeless }), undefined, 'left for Pi to report');
});

// Review (2026-10-25): what the host reads of a call as it starts (the move's area, pendingTools) is the repaired arguments,
// read quietly (the repair is recorded once, when Pi prepares the call).
test('the studio reads a call’s repaired arguments as it starts, without recording the repair twice', async () => {
  const { StudioRuntime } = await import('../src/studio.mjs');
  const recorded = [];
  const accents = fakeTool('paint_accents', { area: Type.Optional(Type.Union([Type.Object({ box: Type.Array(Type.Number()) })])) });
  withArgumentRepair([accents], event => recorded.push(event));
  assert.deepEqual(accents.preparedArguments({ area: '{"box": [1, 2, 3, 4]}' }), { area: { box: [1, 2, 3, 4] } });
  assert.equal(recorded.length, 0, 'quiet');
  const runtime = Object.create(StudioRuntime.prototype);
  Object.assign(runtime, { mode: 'agent', currentMove: { number: 1 }, pendingTools: new Map(), argumentTools: new Map([['paint_accents', accents]]),
    setActivity() {}, countUsage() {}, emit() {}, diagnostics: null });
  runtime.onEvent({ type: 'tool_execution_start', toolCallId: 'c1', toolName: 'paint_accents', args: { area: '{"box": [10, 20, 30, 40]}' } });
  assert.deepEqual(runtime.currentMove.area, [10, 20, 30, 40]);
  assert.deepEqual(runtime.pendingTools.get('c1').args, { area: { box: [10, 20, 30, 40] } });
});

test('a batch cut short inside its last action runs without it, and the painter is told which', async () => {
  const handlers = {}, recorded = [];
  argumentRepair({ record: event => recorded.push(event) })({ on: (name, handler) => { handlers[name] = handler; } });
  const raw = '{"actions": [{"tool": "paint_pass", "arguments": {"name": "Sky"}}, {"tool": "paint_pass", "arguments": {"strokes": [[1, 2';
  const message = { role: 'assistant', content: [{ type: 'toolCall', id: 'c1', name: 'paint_batch', arguments: {}, argumentsError: `Unexpected end of JSON input\n\nReceived arguments:\n${raw}` }] };
  const replaced = (await handlers.message_end({ type: 'message_end', message })).message;
  assert.equal(replaced.content[0].arguments.actions.length, 1);
  assert.match(recorded[0].repairs.join(), /action 2 was cut off and dropped/);
  const told = await handlers.tool_result({ toolCallId: 'c1', content: [] });
  assert.match(told.content.at(-1).text, /action 2 was cut off and dropped: send it again/);
});
