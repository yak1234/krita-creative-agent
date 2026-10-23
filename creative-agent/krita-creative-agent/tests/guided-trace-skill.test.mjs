// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The guided-trace skill's development files: the wording for SKILL.md (DEVELOPMENT.md), the worked night-city
// underdrawing and the subject notes. The example's calls are real: each draw_guide call passes the tool's schema and
// its reference mappings are ones the tool accepts. Reads the skill folder only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { Value } from 'typebox/value';
import { paintingTools } from '../src/tools.mjs';
import { mapReferencePoint } from '../src/reference-generator.mjs';

const folder = new URL('../skills/guided-trace/', import.meta.url);
const read = name => readFileSync(new URL(name, folder), 'utf8');
const SUBJECTS = ['subject-architecture.md', 'subject-vehicles.md', 'subject-figures.md', 'subject-landscape.md'];
const words = text => text.split(/\s+/).filter(Boolean).length;

test('SKILL.md carries the move order, the checks and the pointers, in 700 words or fewer', () => {
  for (const name of ['SKILL.md', 'example-harbour-dusk.md', ...SUBJECTS]) assert.ok(existsSync(new URL(name, folder)), name);
  const skill = read('SKILL.md');
  for (const term of ['eye level', 'vanishing point', 'perspective', 'from_reference', 'lights: true', "weight: 'light'", 'replace: true',
    'never fill a guide shape flat', 'meet at the vanishing point', 'same fraction', 'say what it is', 'outlined warm',
    'a guides move', 'masses: true', 'finish_move', 'paint_from_reference', 'one element per move', 'example-harbour-dusk.md', ...SUBJECTS])
    assert.ok(skill.toLowerCase().includes(term.toLowerCase()), term);
  assert.ok(skill.indexOf('paint_from_reference') < skill.indexOf('a guides move') && skill.indexOf('a guides move') < skill.indexOf('one element per move'),
    'the underpainting first; a guides move only when asked; then one element per move');
  assert.match(skill, /only when the artist asks/i, 'guides are never the default (the artist, 2026-10-23)');
  assert.doesNotMatch(skill, /unless the artist says otherwise/i, 'the masses are not a default');
  assert.ok(words(skill) <= 700, `${words(skill)} words`);
  for (const name of SUBJECTS) {
    const text = read(name);
    assert.match(text, /common errors/i, name);
    assert.ok(words(text) <= 350, `${name} is a short note (${words(text)} words)`);
  }
});

test('the worked example is real calls in three kinds of move, on a general subject', () => {
  const text = read('example-harbour-dusk.md');
  assert.doesNotMatch(text, /moscow|kremlin|stalin/i, 'a general example, not the artist’s own scene');
  const block = /```json\n([\s\S]*?)\n```/.exec(text);
  assert.ok(block, 'one JSON block of calls');
  const example = JSON.parse(block[1]);
  const runtime = { calls: [], faulted: false, study: { directory: '/nonexistent', references: [] }, emit() {}, async callNative() { return {}; } };
  const tools = paintingTools(runtime);
  const [cw, ch] = example.canvas;
  for (const [m, move] of example.moves.entries()) {
    assert.equal(move.at(-1).tool, 'finish_move', `move ${m + 1} ends with finish_move`);
    for (const [index, { tool, args }] of move.entries()) {
      if (tool === 'finish_move') { assert.equal(index, move.length - 1); assert.ok(args.summary.length <= 160); continue; }
      const definition = tools.find(t => t.name === tool);
      assert.ok(definition, `${tool} is a painter tool`);
      assert.ok(Value.Check(definition.parameters, args), `move ${m + 1} call ${index} (${tool}) passes its schema: ${JSON.stringify([...Value.Errors(definition.parameters, args)].slice(0, 2))}`);
      for (const from of [args.from_reference, tool === 'paint_from_reference' ? args : null].filter(Boolean)) {
        const [rw, rh] = example.references[from.reference_id] ?? [];
        assert.ok(rw && rh, `${from.reference_id} is a listed reference`);
        const source = from.source ?? [0, 0, rw, rh];
        assert.ok(source[0] + source[2] <= rw && source[1] + source[3] <= rh, `move ${m + 1} call ${index}: the source fits the reference`);
        assert.doesNotThrow(() => mapReferencePoint(source, from.target), `move ${m + 1} call ${index}: source and target share an aspect`);
        assert.ok(from.target[0] + from.target[2] <= cw && from.target[1] + from.target[3] <= ch, `move ${m + 1} call ${index}: the target is on the canvas`);
      }
    }
  }
  const [colour, construction, element] = example.moves;
  assert.equal(colour[0].tool, 'paint_from_reference', 'the whole-picture underpainting first');
  assert.match(text, /asks for guides|asks for a block-in/i, 'the guides move is the artist\u2019s request, not a default');
  const guides = construction.filter(c => c.tool === 'draw_guide').map(c => c.args);
  assert.ok(construction.every(c => ['draw_guide', 'finish_move'].includes(c.tool)), 'the construction move paints nothing');
  assert.ok(guides[0].perspective?.eye_level_y !== undefined && guides[0].perspective.vanishing_points?.length, 'eye level and vanishing point first');
  const elements = guides.filter(g => g.from_reference && !g.from_reference.masses);
  assert.ok(elements.length >= 4, 'from_reference per element');
  assert.deepEqual(new Set(elements.map(g => g.from_reference.detail)), new Set(['simple', 'medium']), 'both detail levels');
  assert.ok(guides.some(g => g.from_reference?.lights) && guides.some(g => g.lines?.some(l => l.weight === 'light')), 'light shapes both ways');
  assert.equal(element[0].tool, 'draw_guide'); assert.equal(element[0].args.replace, true, 'then one element: tightened first');
  assert.ok(element.some(c => c.tool === 'finish_guide') && element.some(c => c.tool === 'paint_pass'), 'painted in own strokes, then its guide finished');
  assert.match(text, /fraction of the canvas/i, 'positions come from measuring the reference');
});

test('element shapes: one box or a few points per element, one box per member of a group, and "shape", never "mask"', () => {
  const skill = read('SKILL.md');
  assert.match(skill, /shape: \{box/, 'the skill shows from_reference shape');
  assert.match(skill, /one box or a few points per element/i);
  assert.match(skill, /one box per member/i);
  assert.match(skill, /each tower/i, 'a skyline is one box per tower, not the cluster');
  assert.match(skill, /score/i, 'a low score means prompt again');
  assert.match(skill, /inside_shape/);
  assert.match(skill, /points[^.]*fitted into `target`/, 'with points, target is the box the element is fitted into');
  assert.ok(words(skill) <= 700, `${words(skill)} words`);
  for (const name of ['SKILL.md', 'example-harbour-dusk.md', ...SUBJECTS]) assert.doesNotMatch(read(name), /\bmasks?\b/i, `${name} says shape, never mask`);
  for (const name of SUBJECTS) {
    assert.match(read(name), /shape/, `${name} names the shape prompt`);
    assert.ok(words(read(name)) <= 350, name);
  }
  assert.match(read('subject-architecture.md'), /one box per (building|tower)/i);
});

test('a project folder plan starts with the underpainting from the goal image; guides only when the artist asks', () => {
  const text = read('project-folder.md');
  assert.match(text, /1\. \*\*Underpainting from the goal image/);
  assert.match(text, /paint_from_reference/);
  assert.match(text, /only when the artist ask/i);
  assert.doesNotMatch(text, /Block-in \(step 1\)/);
});
