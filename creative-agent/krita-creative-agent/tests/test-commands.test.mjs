// creative_test_command: the panel commands a test chat may be sent, validated against what the test chat shows (its
// plan, its question, its found areas) before anything reaches the test companion. No files or processes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { panelCommand, TEST_COMMANDS } from '../src/test-commands.ts';

const folder = '/tmp/runs/test-1';
const view = (more = {}) => ({ testFolder: folder, mode: 'agent', planSteps: [{ index: 0, key: 'underpainting', title: 'Underpainting', state: 'open' },
  { index: 1, key: 'accents', title: 'Accents', state: 'open' }], question: null, closeupQuestion: null, foundAreas: [], folderElements: ['01-moonlit-sky.png'], ...more });
const found = { request_id: 'f1', part: 'the sky', mask_path: folder + '/data/chat/.shapes/found-0123456789abcdef01234567.png', bounds: [0, 0, 10, 5], canvas: [10, 10] };

test('only the allowlisted panel commands, with known parameters', () => {
  assert.deepEqual([...TEST_COMMANDS].sort(), ['answer', 'closeup_answer', 'find_it', 'folder_guess', 'folder_study', 'paint_only_here', 'plan_step', 'set_limits', 'set_mode', 'sharpen_answer', 'start_plan', 'stop']);
  for (const type of ['shutdown', 'end', 'open_folder', 'configure_provider', 'delete_chat', 'import_archive', 'shapes_model', 'prompt', '', 7])
    assert.throws(() => panelCommand(type, {}, view()), /not a test command|Allowed/, String(type));
  assert.throws(() => panelCommand('stop', { now: true }, view()), /unknown parameter now/);
  assert.throws(() => panelCommand('stop', [], view()), /object/);
  assert.deepEqual(panelCommand('stop', undefined, view()), { command: { type: 'stop' } });
  assert.deepEqual(panelCommand('set_mode', { mode: 'autopilot' }, view()), { command: { type: 'set_mode', mode: 'autopilot' } });
  assert.throws(() => panelCommand('set_mode', { mode: 'god' }, view()), /mode/);
});

test('start_plan and plan_step as the panel sends them, only for the plan the test chat shows', () => {
  const start = panelCommand('start_plan', {}, view()).command;
  assert.equal(start.type, 'prompt'); assert.equal(start.start_plan, true); assert.equal(start.chat_mode, 'agent');
  assert.equal(start.text, 'Start painting from this plan.'); assert.match(start.message_id, /^[0-9a-f]{32}$/);
  assert.throws(() => panelCommand('start_plan', {}, view({ planSteps: [] })), /no plan/);
  const step = panelCommand('plan_step', { action: 'redo', step_key: 'accents', text: 'Crisper lamps.' }, view()).command;
  assert.deepEqual({ ...step, id: undefined }, { type: 'plan_step', id: undefined, action: 'redo', step_key: 'accents', text: 'Crisper lamps.' });
  assert.match(step.id, /^[0-9a-f]{32}$/);
  assert.throws(() => panelCommand('plan_step', { action: 'skip', step_key: 'sky' }, view()), /not a step of the plan.*underpainting, accents/);
  assert.throws(() => panelCommand('plan_step', { action: 'delete', step_key: 'accents' }, view()), /action/);
  assert.throws(() => panelCommand('plan_step', { action: 'skip', step_key: 'accents', text: 'x' }, view()), /Redo/);
});

test('find_it by name; Paint only here from a found outline or a mask inside the test folder, never elsewhere', () => {
  const find = panelCommand('find_it', { part: 'the sky' }, view()).command;
  assert.equal(find.type, 'find_it'); assert.equal(find.part, 'the sky'); assert.match(find.request_id, /^[0-9a-f]{32}$/);
  assert.throws(() => panelCommand('find_it', { part: ' ' }, view()), /part/);
  assert.throws(() => panelCommand('paint_only_here', { action: 'set' }, view()), /Find it/);
  const fromFound = panelCommand('paint_only_here', { action: 'set' }, view({ foundAreas: [{ request_id: 'old', error: 'nothing' }, found] }));
  assert.deepEqual(fromFound, { area: { action: 'set', mask_path: found.mask_path, bounds: [0, 0, 10, 5], canvas: [10, 10], name: 'the sky' } });
  assert.equal(panelCommand('paint_only_here', { action: 'set', found: 'f1', name: 'Sky' }, view({ foundAreas: [found] })).area.name, 'Sky');
  assert.throws(() => panelCommand('paint_only_here', { action: 'set', found: 'f2' }, view({ foundAreas: [found] })), /no found area f2/);
  const mask = { action: 'set', mask_path: folder + '/masks/sky.png', bounds: [0, 0, 4, 4], canvas: [10, 10] };
  assert.equal(panelCommand('paint_only_here', mask, view()).area.mask_path, mask.mask_path);
  for (const mask_path of ['/Users/artist/new_moscow/sky.png', folder + '/../test-2/sky.png', 'sky.png', folder + '/sky.jpg'])
    assert.throws(() => panelCommand('paint_only_here', { ...mask, mask_path }, view()), /inside the test chat/, mask_path);
  assert.throws(() => panelCommand('paint_only_here', { ...mask, bounds: [0, 0, 4] }, view()), /bounds/);
  assert.deepEqual(panelCommand('paint_only_here', { action: 'clear' }, view()), { area: { action: 'clear' } });
});

test('answers go to the question the test chat shows: a Paint only here card with its proposal or a found outline', () => {
  assert.throws(() => panelCommand('answer', { text: 'Yes' }, view()), /no question/);
  const proposal = { mask_path: folder + '/data/chat/.shapes/found-aaaaaaaaaaaaaaaaaaaaaaaa.png', bounds: [1, 1, 2, 2], canvas: [10, 10] };
  const question = { id: 'q1', question: 'Is this the sky?', options: ['Use this', 'Adjust with Freehand', 'Paint everywhere'], select_area: { part: 'the sky', proposal } };
  const asked = view({ question });
  assert.throws(() => panelCommand('answer', { text: 'Use this', question_id: 'q0' }, asked), /q1/);
  const use = panelCommand('answer', { text: 'Use this', area: 'proposal' }, asked);
  assert.deepEqual(use.area, { action: 'set', ...proposal, name: 'the sky' });
  assert.equal(use.command.type, 'prompt'); assert.equal(use.command.text, 'Use this'); assert.equal(use.command.paint_only_here, undefined, 'the area goes first, protected');
  assert.equal(panelCommand('answer', { text: 'Use my selection', area: 'found' }, view({ question, foundAreas: [found] })).area.mask_path, found.mask_path);
  assert.equal(panelCommand('answer', { text: 'Paint everywhere' }, asked).area, undefined);
  assert.throws(() => panelCommand('answer', { text: 'Use this', area: 'proposal' }, view({ question: { id: 'q2', question: 'Which sky?', options: [] } })), /no proposed outline/);
  assert.throws(() => panelCommand('answer', { text: 'Use this', area: 'mine' }, asked), /area/);
  const closeup = view({ closeupQuestion: { id: 'c1', question: 'Does this close-up match?', options: ['Yes', 'No', 'You decide'] } });
  assert.deepEqual(panelCommand('closeup_answer', { answer: 'Yes' }, closeup), { command: { type: 'closeup_answer', question_id: 'c1', answer: 'Yes' } });
  assert.throws(() => panelCommand('closeup_answer', { answer: 'Maybe' }, closeup), /Yes, No, You decide/);
  assert.throws(() => panelCommand('closeup_answer', { answer: 'Yes' }, view()), /no close-up question/);
  assert.deepEqual(panelCommand('folder_guess', { name: '01-moonlit-sky.png', guess: 'the sky' }, view()).command, { type: 'folder_guess', name: '01-moonlit-sky.png', guess: 'the sky' });
  assert.throws(() => panelCommand('folder_guess', { name: 'other.png', guess: 'x' }, view()), /element/);
  // The Folder tab's study menu and choice card (folder-study).
  assert.deepEqual(panelCommand('folder_study', { action: 'exclude', name: '01-moonlit-sky.png' }, view()).command, { type: 'folder_study', action: 'exclude', name: '01-moonlit-sky.png' });
  assert.deepEqual(panelCommand('folder_study', { action: 'choose', choice: 'pick', picked: ['01-moonlit-sky.png'] }, view()).command,
    { type: 'folder_study', action: 'choose', choice: 'pick', picked: ['01-moonlit-sky.png'] });
  assert.deepEqual(panelCommand('folder_study', { action: 'stop' }, view()).command, { type: 'folder_study', action: 'stop' });
  assert.throws(() => panelCommand('folder_study', { action: 'exclude', name: 'other.png' }, view()), /element/);
  assert.throws(() => panelCommand('folder_study', { action: 'choose', choice: 'some' }, view()), /choice is plan, all, pick or none/);
  assert.throws(() => panelCommand('folder_study', { action: 'choose', choice: 'pick', picked: ['other.png'] }, view()), /element/);
  assert.throws(() => panelCommand('folder_study', { action: 'delete' }, view()), /action is/);
  assert.deepEqual(panelCommand('folder_study', { action: 'study', name: 'final_goal.png' }, view({ folderImages: ['final_goal.png', '01-moonlit-sky.png'] })).command,
    { type: 'folder_study', action: 'study', name: 'final_goal.png' }, 'the goal can be studied too');
});

test('set_limits sets the test chat allowance as the panel does: AI images 0-20 or null for no limit (to test /canvas-reference with real pictures)', () => {
  assert.deepEqual(panelCommand('set_limits', { ai_images: 3 }, view()).command, { type: 'set_limits', limits: { minutes: 0, passes: 0, ai_images: 3 } });
  assert.deepEqual(panelCommand('set_limits', { ai_images: null }, view()).command.limits.ai_images, null);
  assert.throws(() => panelCommand('set_limits', { ai_images: 50 }, view()), /0-20/);
  assert.throws(() => panelCommand('set_limits', { budget: 1 }, view()), /unknown/i);
});
