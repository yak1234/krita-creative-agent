// The underpainting move ends when the transfer finishes (crisp-accents goal 7): the rule's own module. The studio wiring
// and a replay of chat 34deca0e's shape are in studio.test.mjs. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { transferJobId, underpaintingState, underpaintingRefusal, closedNote, UNDERPAINTING_MOVE_NOTE } from '../src/underpainting-move.ts';

test('the job a transfer call paints: the call id’s hash for a new transfer, job_id for a continuation, none for other tools', () => {
  assert.equal(transferJobId('paint_from_reference', 'call-1', {}), createHash('sha256').update('call-1').digest('hex').slice(0, 32));
  assert.equal(transferJobId('continue_reference_painting', 'call-2', { job_id: 'a'.repeat(32) }), 'a'.repeat(32));
  assert.equal(transferJobId('paint_reference_edges', 'call-3', {}), null, 'edges are finishing, not the underpainting');
  assert.equal(transferJobId('paint_batch', 'call-4', {}), null);
});

test('a whole transfer that completed closes the move; one that stopped keeps it open for continue_reference_painting', () => {
  assert.deepEqual(underpaintingState({ job: 'j', whole: true, status: 'complete' }), { job: 'j', status: 'complete', closed: true });
  assert.deepEqual(underpaintingState({ job: 'j', whole: true, status: 'paused' }), { job: 'j', status: 'paused', closed: false });
  assert.equal(underpaintingState({ job: 'j', whole: false, status: 'complete' }), null, 'a patch is not the underpainting');
  assert.equal(underpaintingState({ job: null, whole: true, status: 'complete' }), null);
});

test('after the transfer completes no other painting call runs in the move; a stopped one may only be continued', () => {
  const closed = { job: 'j', status: 'complete', closed: true };
  for (const tool of ['paint_batch', 'paint_pass', 'fill_region', 'paint_reference_edges', 'continue_reference_painting', 'paint_accents'])
    assert.match(underpaintingRefusal(closed, tool, {}, 1) ?? '', /^Move 1 ended when the whole-picture underpainting completed/, tool);
  const paused = { job: 'j', status: 'paused', closed: false };
  assert.equal(underpaintingRefusal(paused, 'continue_reference_painting', { job_id: 'j' }, 1), null);
  assert.match(underpaintingRefusal(paused, 'paint_batch', {}, 1) ?? '', /continue_reference_painting with job_id "j"/);
  assert.match(underpaintingRefusal(paused, 'continue_reference_painting', { job_id: 'other' }, 1) ?? '', /job_id "j"/);
  assert.equal(underpaintingRefusal(undefined, 'paint_batch', {}, 1), null, 'a move without a whole transfer');
});

test('the painter and the move instructions are told the rule', () => {
  assert.match(closedNote(), /closed this move.*Stop now/);
  assert.match(UNDERPAINTING_MOVE_NOTE, /ends when it completes/);
});
