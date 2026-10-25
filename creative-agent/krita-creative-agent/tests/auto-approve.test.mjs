// Auto-approve (openspec auto-approve, the artist 2026-10-25: "an auto approve mode, it's standard in agentic systems").
// The panel counts down on each card that waits and takes its default answer; the companion declares the setting, marks
// the recommended option of the choice cards that have one, and records every auto-answer in the diagnostics.
import test from 'node:test';
import assert from 'node:assert/strict';
import { executionSettings } from '../src/execution-settings.mjs';
import { panelSchema, SETTINGS } from '../src/settings-schema.mjs';
import { AUTO_APPROVE_DELAYS, AUTO_APPROVE_KINDS, autoApproveRecord, recommendYouDecide } from '../src/auto-approve.ts';
import { StudioRuntime } from '../src/studio.mjs';
import { STAGE_CARD } from '../src/plan-stages.ts';

test('Auto-approve: Off by default; Immediately, 10, 30 or 60 s; one schema entry the panel builds from', () => {
  assert.equal(executionSettings().auto_approve, 'off', 'the artist turns it on');
  for (const delay of [0, 10, 30, 60]) assert.equal(executionSettings({ auto_approve: delay }).auto_approve, delay);
  for (const wrong of ['30', 45, true, null]) assert.throws(() => executionSettings({ auto_approve: wrong }), /Auto-approve/);
  const field = panelSchema().find(f => f.key === 'auto_approve');
  assert.equal(field.label, 'Auto-approve');
  assert.equal(field.accessible, 'Auto-approve');
  assert.deepEqual(field.options, [{ value: 'off', label: 'Off' }, { value: 0, label: 'Immediately' }, { value: 10, label: '10 s' },
    { value: 30, label: '30 s' }, { value: 60, label: '60 s' }]);
  assert.match(field.tooltip, /Undo/); assert.match(field.tooltip, /never/i);
  assert.deepEqual(AUTO_APPROVE_DELAYS, [0, 10, 30, 60]);
  assert.ok(SETTINGS.find(s => s.key === 'auto_approve'));
});

test('an auto-answer record: a known card kind, its answer and the delay; anything else is no record', () => {
  assert.deepEqual(autoApproveRecord({ type: 'auto_approved', kind: 'plan_step', answer: 'met', delay: 30, card: 'title:sky#0' }),
    { type: 'auto_approve', kind: 'plan_step', answer: 'met', delay: 30, card: 'title:sky#0' });
  assert.deepEqual(autoApproveRecord({ kind: 'move', answer: 'keep', delay: 0 }), { type: 'auto_approve', kind: 'move', answer: 'keep', delay: 0 });
  assert.deepEqual([...AUTO_APPROVE_KINDS], ['plan_step', 'move', 'sharpen_offer', 'sharpen_review', 'question', 'closeup']);
  assert.equal(autoApproveRecord({ kind: 'delete_layers', answer: 'yes', delay: 0 }), null, 'an unknown card');
  assert.equal(autoApproveRecord({ kind: 'move', answer: 'keep', delay: 45 }), null, 'a delay the setting never offers');
  assert.equal(autoApproveRecord({ kind: 'move', answer: '', delay: 10 }), null);
  assert.equal(autoApproveRecord({ kind: 'move', answer: 'x'.repeat(201), delay: 10 }), null);
  assert.equal(autoApproveRecord(null), null);
  assert.equal(autoApproveRecord({ kind: 'move', answer: 'keep', delay: 10, card: 7 }).card, undefined, 'a card id is a short string or left out');
});

test('the studio records each auto-answer in the diagnostics, and ignores a malformed one', () => {
  const recorded = [];
  const fake = { diagnostics: { record: event => recorded.push(event) } };
  StudioRuntime.prototype.recordAutoApprove.call(fake, { type: 'auto_approved', kind: 'sharpen_offer', answer: 'sharpen', delay: 10 });
  StudioRuntime.prototype.recordAutoApprove.call(fake, { type: 'auto_approved', kind: 'nothing', answer: 'x', delay: 10 });
  assert.deepEqual(recorded, [{ type: 'auto_approve', kind: 'sharpen_offer', answer: 'sharpen', delay: 10 }]);
});

test('choice cards mark a recommended option only where a default answer is safe', () => {
  assert.equal(STAGE_CARD.recommended, 'The whole plan', 'the stage card: the whole plan, as when no stage is named');
  assert.ok(STAGE_CARD.options.includes(STAGE_CARD.recommended));
  // The painter's own questions: "You decide" (the panel adds it to every question) lets the painter choose.
  assert.deepEqual(recommendYouDecide({ question: 'Which sky?', options: ['Warm', 'Cool'] }),
    { question: 'Which sky?', options: ['Warm', 'Cool'], recommended: 'You decide' });
  assert.equal(recommendYouDecide({ question: 'q', options: ['A', 'you decide.'] }).recommended, 'you decide.', 'its own spelling, when the painter offered it');
});
