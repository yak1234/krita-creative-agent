// Seam check: the shipped Pi extension that has Luna confirm the plugin's seam candidates on the chat's first look,
// and tells the painter only the confirmed ones. A fake `pi`, host and Luna client; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import seamCheck, { SEAM_THRESHOLD } from '../extensions/seam-check.ts';
import { seamCheck as lunaSeams } from '../src/visual-checks.ts';
import { modelResultText } from '../src/tools.mjs';

const candidates = [
  { axis: 'h', at: 116, from: 2584, to: 3116, step: 9.2, crop: '/s/.seams/seam-0.jpg', crop_size: [768, 300] },
  { axis: 'v', at: 996, from: 0, to: 448, step: 8.9, crop: '/s/.seams/seam-1.jpg', crop_size: [300, 768] },
];

function setup({ mode = 'guide', scores = [0.98, 0.1] } = {}) {
  const handlers = {}, asked = [], recorded = [];
  const host = { mode: () => mode, confirm: async list => { asked.push(list); if (scores instanceof Error) throw scores; return scores; },
    record: entry => recorded.push(entry) };
  seamCheck(host)({ on: (name, handler) => { handlers[name] = handler; } });
  const result = (details, toolName = 'observe_canvas') =>
    handlers.tool_result({ type: 'tool_result', toolCallId: 'c1', toolName, input: {}, isError: false, content: [{ type: 'text', text: '{}' }], details }, {});
  return { result, asked, recorded };
}

test('the painter is told only the seams Luna confirms, in canvas pixels, with how to repair them', async () => {
  const s = setup();
  const changed = await s.result({ status: 'ok', seam_candidates: candidates });
  const line = JSON.parse(changed.content.at(-1).text);
  assert.deepEqual(line.baked_in_seams, [{ axis: 'horizontal', at: 116, from: 2584, to: 3116 }]);
  assert.match(line.note, /repair/i);
  assert.equal(s.asked[0].length, 2);
  assert.equal(s.recorded[0].confirmed, 1);
  assert.equal(await s.result({ status: 'ok', seam_candidates: candidates }), undefined, 'told once a chat');
  assert.equal(s.asked.length, 1, 'Luna asked once a chat');
});

test('nothing is added with Luna off, without candidates, for other tools, or when Luna cannot answer', async () => {
  assert.equal(await setup({ mode: 'off' }).result({ seam_candidates: candidates }), undefined);
  assert.equal(await setup().result({ status: 'ok' }), undefined);
  assert.equal(await setup().result({ seam_candidates: candidates }, 'paint_pass'), undefined);
  assert.equal(await setup({ scores: [null, 0.2] }).result({ seam_candidates: candidates }), undefined, 'none confirmed');
  assert.equal(await setup({ scores: new Error('offline') }).result({ seam_candidates: candidates }), undefined);
  assert.ok(SEAM_THRESHOLD >= 0.5);
});

test('Luna is asked about each close-up in its own request; a failed one is null', async () => {
  const seen = [];
  const client = { decide: async request => { seen.push(request); return seen.length === 2 ? { fallback: 'timeout', elapsed_ms: 1 }
    : { answers: { seam: { type: 'noul', noul: 0.9 } }, usage: { cost: 0.001, input_tokens: 550 }, elapsed_ms: 5 }; } };
  const scores = await lunaSeams({ client, crops: [{ image: { type: 'image', data: 'a', mimeType: 'image/jpeg' }, axis: 'h' },
    { image: { type: 'image', data: 'b', mimeType: 'image/jpeg' }, axis: 'v' }] });
  assert.deepEqual(scores, [0.9, null]);
  assert.match(seen[0].questions.seam.instructions, /horizontal line across the middle/);
  assert.match(seen[1].questions.seam.instructions, /vertical line down the middle/);
});

test('raw candidates never reach the painter', () => {
  assert.doesNotMatch(modelResultText({ status: 'ok', seam_candidates: candidates }), /seam_candidates/);
});

test('the companion registers it', async () => {
  const { seamCheckExtension } = await import('../src/extensions.mjs');
  assert.equal(seamCheckExtension({ mode: () => 'off', confirm: async () => [], record: () => {} }).name, 'seam-check');
});

test('background-save bookkeeping never reaches the painter', () => {
  const text = modelResultText({ status: 'ok', save_job: { job: 3, state: 'running' }, previous_save: { job: 2, state: 'failed', error: 'x' }, background_refused: 'busy' });
  assert.doesNotMatch(text, /save_job|previous_save|background_refused/);
});
