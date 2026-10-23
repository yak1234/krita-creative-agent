import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { hasGoalReference, referenceColourPassMade, referenceFirstContext, paintedTransfers, fillNudge, isFillNudge } from '../src/reference-first.ts';

test('a goal or general reference counts; an asset, a construction map, a part and a palette reference do not', () => {
  assert.equal(hasGoalReference([{ role: 'reference', purpose: 'general' }]), true);
  assert.equal(hasGoalReference([{ purpose: 'composition' }]), true, 'role and purpose default as the studio stores them');
  assert.equal(hasGoalReference([{}]), true);
  for (const r of [{ role: 'asset', purpose: 'material' }, { role: 'construction-map', purpose: 'composition' },
    { role: 'reference', purpose: 'general', part_kind: 'part' }, { role: 'reference', purpose: 'palette' }])
    assert.equal(hasGoalReference([r]), false, JSON.stringify(r));
  assert.equal(hasGoalReference(undefined), false);
});

test('a colour pass is a transfer that painted, in this plan revision and not undone; surface, edges and empty jobs are not', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'reference-first-'));
  const scope = JSON.stringify([2]);
  try {
    assert.equal(await referenceColourPassMade(directory, { revision: 2 }), false, 'no jobs folder');
    const folder = join(directory, 'reference-paintings'); await mkdir(folder);
    const job = (id, recipe, completed, jobScope = scope) => writeFile(join(folder, id.repeat(32) + '.json'), JSON.stringify({ id: id.repeat(32), recipe, completed, scope: jobScope }));
    await job('a', { mode: 'edges' }, 300); await job('b', {}, 0); await job('c', { mode: 'surface' }, 10);
    await job('d', {}, 500, JSON.stringify([1]));
    assert.equal(await referenceColourPassMade(directory, { revision: 2 }), false, 'a transfer for another plan revision does not count');
    assert.equal((await paintedTransfers(directory, { revision: 2 })).length, 0);
    await job('e', {}, 10);
    assert.equal(await referenceColourPassMade(directory, { revision: 2 }), true);
    assert.equal(await referenceColourPassMade(directory, { revision: 2, undone: new Set(['e'.repeat(32)]) }), false, 'an undone transfer counts as not done');
    assert.equal((await paintedTransfers(directory, { revision: 2 })).length, 1, 'but it is still a painted transfer job, as the reference tools count them');
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('the nudge and the guidance name paint_from_reference only while a whole transfer would be accepted', () => {
  assert.match(fillNudge(true), /^This painting has a reference\. Lay its colours first with paint_from_reference/);
  assert.doesNotMatch(fillNudge(true), /paint_reference_surface/);
  assert.doesNotMatch(fillNudge(false), /paint_from_reference/);
  assert.match(fillNudge(false), /paint_reference_surface and paint_reference_edges over the paint already there/);
  for (const transfer of [true, false]) {
    assert.match(fillNudge(transfer), /Call fill_region again if a flat fill is really intended\.$/);
    assert.ok(isFillNudge(fillNudge(transfer)));
  }
  assert.equal(isFillNudge('Painting is disabled'), false);
});

test('each skill is added at most once: one the artist\'s message already expanded is not repeated', () => {
  const block = name => `<skill name="${name}">${name} body</skill>`;
  const both = referenceFirstContext('Paint the sky.', block);
  assert.match(both, /reference-transfer body/);
  assert.doesNotMatch(both, /guided-trace body/, 'no guides by default: guided-trace comes with a request for guides');
  assert.match(both, /guides only when the artist asks/i);
  const one = referenceFirstContext(block('guided-trace') + '\n\ntrace it', block);
  assert.equal(one.split('<skill name="guided-trace"').length - 1, 0);
  assert.match(one, /reference-transfer body/);
  assert.doesNotMatch(referenceFirstContext(block('guided-trace') + block('reference-transfer'), block), /body/);
});

test('later moves get a one-line reminder, not the skills again; the lead names the tool that is available', () => {
  const block = name => `<skill name="${name}">${name} body</skill>`;
  const reminder = referenceFirstContext('Paint the sky.', block, { full: false });
  assert.doesNotMatch(reminder, /<skill/);
  assert.equal(reminder.trim().split('\n').length, 1, 'one line');
  assert.match(reminder, /skill given earlier/);
  assert.match(referenceFirstContext('x', block), /with paint_from_reference/);
  assert.doesNotMatch(referenceFirstContext('x', block, { transfer: false }), /paint_from_reference/);
  assert.match(referenceFirstContext('x', block, { transfer: false, full: false }), /paint_reference_surface and paint_reference_edges/);
});
