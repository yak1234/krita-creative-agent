// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Older tool results reach the model as one line (eyes-and-history 5): compaction is rarer, the session keeps them whole.
import test from 'node:test';
import assert from 'node:assert/strict';
import { trimOldToolResults, KEEP_TURNS, LOOKUP_TOOLS } from '../src/history-trim.ts';

const turn = (i, name = 'observe_canvas', text = JSON.stringify({ status: 'ok', revision: 'r' + i, layers: Array.from({ length: 40 }, (_, k) => ({ id: 'l' + k, name: 'Layer ' + k })) })) => [
  { role: 'assistant', content: [{ type: 'toolCall', id: 'c' + i, name, arguments: {} }] },
  { role: 'toolResult', toolCallId: 'c' + i, toolName: name, isError: false, timestamp: i, content: [{ type: 'text', text }, { type: 'image', data: 'A', mimeType: 'image/png' }] },
];

test('older observe results and long results become one line; the last turns, short results and images stay', () => {
  const messages = [{ role: 'user', content: 'Paint the towers.' }, ...turn(1), ...turn(2, 'set_layer', JSON.stringify({ status: 'ok', layer_id: 'a' })),
    ...turn(3, 'paint_pass', JSON.stringify({ status: 'ok', note: 'n'.repeat(3000) })), ...Array.from({ length: KEEP_TURNS }, (_, i) => turn(10 + i)).flat()];
  const out = trimOldToolResults(messages);
  assert.equal(out.length, messages.length);
  const text = m => m.content.find(p => p.type === 'text').text;
  assert.match(text(out[2]), /^\[Older observe_canvas result shortened: status ok, revision r1, 40 layers\. Observe again for the current canvas\.\]$/);
  assert.equal(out[2].content[1].type, 'image', 'images are keepRecentImages’ job');
  assert.equal(text(out[4]), JSON.stringify({ status: 'ok', layer_id: 'a' }), 'a short result stays as it is');
  assert.match(text(out[6]), /^\[Older paint_pass result shortened: status ok\./);
  for (const m of out.slice(-2 * KEEP_TURNS)) if (m.role === 'toolResult') assert.ok(text(m).startsWith('{'), 'the last turns stay whole');
  assert.ok(text(messages[2]).startsWith('{'), 'the session’s own messages are not changed');
  const error = trimOldToolResults([...turn(1, 'paint_pass', JSON.stringify({ status: 'failed', error: 'Brush not found: '.repeat(200) })), ...Array.from({ length: KEEP_TURNS }, (_, i) => turn(10 + i)).flat()]);
  assert.match(text(error[1]), /status failed, error: Brush not found/);
  assert.ok(text(error[1]).length < 300);
  assert.deepEqual(trimOldToolResults(turn(1)), turn(1), 'nothing older than the last turns: unchanged');
});

test('lookups stay whole (brush names, the toolbox manual, capabilities, skills); a paint result keeps its layer and job ids', () => {
  const later = Array.from({ length: KEEP_TURNS }, (_, i) => turn(10 + i)).flat();
  const text = m => m.content.find(p => p.type === 'text').text;
  for (const name of ['list_brushes', 'painting_tool_help', 'krita_capabilities', 'read']) {
    assert.ok(LOOKUP_TOOLS.includes(name), name);
    const long = JSON.stringify({ status: 'ok', brushes: 'b'.repeat(5000) });
    assert.equal(text(trimOldToolResults([...turn(1, name, long), ...later])[1]), long, name + ' is a lookup: kept');
  }
  const painted = trimOldToolResults([...turn(1, 'paint_pass', JSON.stringify({ status: 'ok', layer_id: 'L7', job_id: 'J2', note: 'n'.repeat(3000) })), ...later]);
  assert.match(text(painted[1]), /layer_id L7, job_id J2/);
});
