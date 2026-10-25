// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The planner looks up the tools (plan-from-request goal 3): painting_tool_help without a name is a catalogue of the
// painting stages and tools, with rough times on this canvas from measured numbers; with a name, the full description and
// the skills that use the tool.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { toolCatalogue, toolHelp, roughTime, STAGE_TOOLS, toolboxIndex, toolboxHelp, HELP_LIMIT } from '../src/tool-catalogue.ts';

const tools = [
  { name: 'paint_from_reference', description: 'Transfer a reference. It paints dabs.', parameters: { type: 'object' } },
  { name: 'paint_finish', description: 'Finish the underpainting. Blends soft areas.', parameters: { type: 'object' } },
  { name: 'refine_to_goal', description: 'Refine to the goal. A host loop.', parameters: { type: 'object' } },
  { name: 'paint_accents', description: 'Crisp accents. Lights and darks.', parameters: { type: 'object' } },
  { name: 'paint_batch', description: 'Several painting actions in one call.', parameters: { type: 'object' } },
];

test('rough time: measured on the 6000 x 4500 New Moscow canvas, scaled by pixels', () => {
  assert.equal(roughTime({ seconds: [60, 120] }, { width: 6000, height: 4500 }), '1-2 min');
  assert.equal(roughTime({ seconds: [60, 120] }, { width: 3000, height: 2250 }), '15-30 s');
  assert.equal(roughTime({ seconds: [10, 20] }, { width: 100, height: 100 }), 'a few seconds');
  assert.equal(roughTime({ seconds: [270, 600] }, null), '4.5-10 min (on a 6000 x 4500 canvas)');
});

test('the catalogue: each stage’s tool, what it does, its rough time on this canvas, what it needs; the other tools in one line each', () => {
  const catalogue = toolCatalogue({ tools, canvas: { width: 6000, height: 4500 } });
  assert.deepEqual(catalogue.stages.map(s => [s.stage, s.tool]), [['underpainting', 'paint_from_reference'], ['finish', 'paint_finish'], ['refine', 'refine_to_goal'], ['accents', 'paint_accents']]);
  const finish = catalogue.stages[1];
  assert.match(finish.does, /blend/i); assert.match(finish.needs, /underpainting/i); assert.equal(finish.rough_time, '1-1.2 min');
  assert.match(catalogue.stages[2].rough_time, /min/);
  // The artist, 2026-10-25: one whole-picture refine, then each part step a short touch-up (at most one round, 3 minutes).
  assert.match(catalogue.stages[2].per_part, /touch-up[^]*3 min/); assert.match(catalogue.stages[2].does, /whole picture once[^]*touch-up/);
  assert.deepEqual(catalogue.tools, [{ name: 'paint_batch', does: 'Several painting actions in one call.' }]);
  assert.match(catalogue.how, /painting_tool_help with a name/);
  assert.ok(STAGE_TOOLS.every(s => s.measured.source), 'every time says where it was measured');
  const absent = toolCatalogue({ tools: tools.filter(t => t.name !== 'paint_accents'), canvas: null });
  assert.deepEqual(absent.stages.map(s => s.stage), ['underpainting', 'finish', 'refine'], 'only tools this painter has');
});

test('a named tool: its full description, parameters and the skills that use it; an unknown name says what exists', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'tool-catalogue-'));
  try {
    await mkdir(join(dir, 'paint-sky')); await writeFile(join(dir, 'paint-sky', 'SKILL.md'), '---\nname: paint-sky\n---\nUse paint_finish after the sky transfer.\n');
    await mkdir(join(dir, 'other')); await writeFile(join(dir, 'other', 'SKILL.md'), 'Nothing here.\n');
    const help = await toolHelp('paint_finish', { tools, canvas: { width: 6000, height: 4500 }, skillsDir: dir });
    assert.equal(help.name, 'paint_finish');
    assert.equal(help.description, 'Finish the underpainting. Blends soft areas.');
    assert.deepEqual(help.parameters, {}, 'its parameters by name (none here)');
    assert.equal(help.stage.stage, 'finish');
    assert.deepEqual(help.skills.map(s => s.name), ['paint-sky']);
    assert.match(help.skills[0].excerpt, /Use paint_finish/);
    const unknown = await toolHelp('make_coffee', { tools, canvas: null, skillsDir: dir });
    assert.match(unknown.error, /make_coffee is not a painting tool/); assert.ok(unknown.tools.includes('paint_batch'));
  } finally { await rm(dir, { recursive: true, force: true }); }
});

// Review (2026-10-24): a plan turn's lookups were 8-31k characters each (~75k a turn). Every answer stays under HELP_LIMIT.
test('the catalogue and a named lookup stay small: description, short parameters, the skills\u2019 names with a short excerpt', async () => {
  assert.equal(HELP_LIMIT, 6000);
  const long = 'A sentence about painting. '.repeat(40);
  const many = [...tools, ...Array.from({ length: 40 }, (_, i) => ({ name: 'tool_' + i, description: long, parameters: { type: 'object' } }))];
  assert.ok(JSON.stringify(toolCatalogue({ tools: many, canvas: { width: 6000, height: 4500 } })).length <= 6000);
  const dir = await mkdtemp(join(tmpdir(), 'tool-catalogue-'));
  try {
    for (let i = 0; i < 6; i++) { await mkdir(join(dir, 'skill-' + i)); await writeFile(join(dir, 'skill-' + i, 'SKILL.md'), ('Intro line.\n' + 'Use paint_accents after the finish for the lights. '.repeat(3) + '\n' + long + '\n').repeat(8)); }
    const big = { name: 'paint_accents', description: long.repeat(10), parameters: { type: 'object', properties: Object.fromEntries(Array.from({ length: 30 }, (_, i) => ['p' + i, { type: 'string', description: long }])) } };
    const help = await toolHelp('paint_accents', { tools: [...tools.filter(t => t.name !== 'paint_accents'), big], canvas: null, skillsDir: dir });
    assert.ok(JSON.stringify(help).length <= 6000, String(JSON.stringify(help).length));
    assert.equal(help.skills.length, 6);
    assert.ok(help.skills.every(s => s.name && s.excerpt && s.excerpt.length <= 300 && /paint_accents/.test(s.excerpt)));
    assert.ok('p0' in help.parameters, 'every parameter by name');
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('while painting: an index of the native toolbox, and each command by name, never a truncated stub', () => {
  const long = 'parameter text '.repeat(60);
  const native = { status: 'ok', tools: Object.fromEntries(Array.from({ length: 50 }, (_, i) => ['command_' + i, long])), capabilities: { command_1: { available: true, parameters: long } }, source_modes: { new_layer: 'No source layer' } };
  const index = toolboxIndex(native);
  assert.ok(JSON.stringify(index).length <= 6000);
  assert.equal(Object.keys(index.commands).length, 50);
  assert.match(index.how, /name/);
  const one = toolboxHelp(native, 'command_1');
  assert.equal(one.command, 'command_1'); assert.equal(one.parameters, long.trim());
  assert.equal(toolboxHelp(native, 'nothing'), null);
});
