// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Plan step controls (openspec change plan-step-controls, approved by the artist with mockup B: plain-word buttons, no
// ticks). Per plan step the artist can:
//   - before painting: Skip it (it never runs and stays skipped when the planner proposes it again) or Restore it;
//   - while it paints: "Good enough → next step": the batch in progress finishes, nothing more is painted for the step,
//     it is met by the artist and the next step that is not skipped starts (Agent mode: the next move; Autopilot: the run
//     carries on with that step);
//   - after it finishes on its own (an Agent move ready to review): Met (keep the move, go on) or Redo (undo it and paint
//     the same step again, with what to change when the artist typed it). For a move that painted a plan step, the move
//     card's Keep and Undo are the same actions as Met and Redo.
// The marks live on the goal keyed by the step's identity: in a project folder its file, else its title (folder-notes
// stepKeys), as PLAN.md writes them; without a folder a stable id given to each step when the plan is made or revised
// (withStepIds), so a reworded step keeps its marks. Every "good enough" and "redo" is a lesson for later tuning,
// appended to a file in the chat's own folder; nothing is sent anywhere. The studio wires this in with a few hooks
// (planStepHost in studio.mjs).
import { constants } from 'node:fs';
import { open, realpath } from 'node:fs/promises';
import { basename, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { stepKeys, layerName } from './folder-notes.ts';
import type { StepMark, StepMarks } from './folder-notes.ts';

export const PLAN_STEP_ACTIONS = ['skip', 'restore', 'good_enough', 'met', 'redo'] as const;
export type PlanStepAction = typeof PLAN_STEP_ACTIONS[number];
export type PlanStepCommand = { id: string; action: PlanStepAction; step_key: string; text?: string };
export const LESSONS_FILE = 'plan-step-lessons.jsonl';
export const STEP_ID = /^[A-Za-z0-9_-]{1,40}$/;

type PlanStep = { title: string; scope?: string; done_when?: string; id?: string };
export type Move = { number: number; status: string; step?: number; step_key?: string; calls?: number; finished?: boolean;
  guides_only?: boolean; review?: { verdict?: string }; review_line?: string; likeness?: { luna?: Record<string, number> } };
export type Goal = { brief: { steps: PlanStep[] } | null; status?: string; current_step?: number; done_steps?: number[];
  step_marks?: StepMarks; step_batches?: Record<string, number>; moves?: Move[]; reference_jobs?: Record<string, number[]>;
  pace_history?: { step: number; progress?: number | null; action?: string }[]; reviews?: { verdict?: string }[] };
export type StepState = 'open' | 'skipped' | 'painting' | 'finishing' | 'finished' | 'met' | 'good_enough' | 'done';
/** source: the step's element image (its scope, when that is an image file, relative to the project folder);
 * batches: how many batches it has painted. The panel's Now painting card shows both. */
export type StepView = { index: number; key: string; title: string; state: StepState; redone?: number; source?: string; batches?: number };
const IMAGE_SCOPE = /\.(png|jpe?g|gif|webp)$/i;
type ViewOptions = { mode: string; busy: boolean; currentMove?: Move; folder?: boolean; pending?: string | null };
type Call = { id?: string; tool?: string; args?: Record<string, unknown> };

/** What the studio lends the controls. */
export interface PlanStepHost {
  getGoal(): Goal | null;
  mode(): string;
  busy(): boolean;
  currentMove(): Move | undefined;
  /** A project folder chat: PLAN.md is kept, steps are known by file or title. */
  folder(): boolean;
  chatDirectory(): string | null;
  /** The goal-likeness score of the last batch, once that check exists; null without one. */
  goalLikeness(): number | null;
  persist(): Promise<void>;
  publish(): void;
  say(message: string): void;
  /** PLAN.md rewritten with the ticks and marks (a no-op without a folder). */
  syncPlan(): Promise<void>;
  /** May the plan go on to the next step by itself? `auto`: after a run (not after Stop, an error, a fault, a mode
   * switch or a message the artist typed meanwhile); else the artist's own Met or Keep. */
  mayContinue(auto: boolean): boolean;
  /** Why this move may not be met yet (a pass its step makes mandatory has not run: the architecture texture), or null. */
  metRefusal?(move: Move): string | null;
  /** Keep the move: its status kept (published at once, so no other Keep or Undo can follow) and its layers merged. */
  keepMove(move: Move): Promise<void>;
  /** A folder chat: tick the kept move's step by identity (NOTES.md, its guide, PLAN.md). Returns the first open step. */
  tickFolderStep(move: Move): Promise<number>;
  /** Undo the move: its passes hidden, its status undone. */
  rejectMove(move: Move): Promise<void>;
  /** Paint the undone move's step again, with what to change when given. */
  retryMove(move: Move, note?: string): Promise<void>;
  /** Agent mode: paint the current step's move (Start painting's continuation). */
  nextStepMove(): Promise<void>;
  /** Every step is met, done or skipped. */
  finish(message: string): Promise<void>;
}

const ID = /^[A-Za-z0-9_-]{1,80}$/;
const fail = (why: string): never => { throw new Error('Invalid plan step command: ' + why + '.'); };

/** A panel command, checked: {type:'plan_step', id, action, step_key, text?}; text only for Redo, blank is none. */
export function parsePlanStepCommand(raw: unknown): PlanStepCommand {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fail('not an object');
  const value = raw as Record<string, unknown>;
  for (const key of Object.keys(value)) if (!['type', 'id', 'action', 'step_key', 'text'].includes(key)) fail('unknown field ' + key.slice(0, 40));
  const { id, action, step_key: stepKey, text } = value;
  if (typeof id !== 'string' || !ID.test(id)) fail('id');
  if (typeof action !== 'string' || !(PLAN_STEP_ACTIONS as readonly string[]).includes(action)) fail('action');
  if (typeof stepKey !== 'string' || !stepKey || stepKey.length > 400) fail('step_key');
  const command: PlanStepCommand = { id: id as string, action: action as PlanStepAction, step_key: stepKey as string };
  if (text !== undefined) {
    if (action !== 'redo') fail('text is only for Redo');
    if (typeof text !== 'string' || text.length > 1000) fail('text');
    const trimmed = (text as string).replace(/\s+/g, ' ').trim();
    if (trimmed) command.text = trimmed;
  }
  return command;
}

/** Each step's identity: in a folder chat its file or title (as PLAN.md knows it); otherwise its id, when it has one. */
export function stepIdentities(steps: readonly PlanStep[], folder = false): string[] {
  const keys = stepKeys(steps);
  return folder ? keys : steps.map((step, i) => typeof step.id === 'string' && STEP_ID.test(step.id) ? 'id:' + step.id : keys[i]);
}

/** A new or revised plan's steps with stable ids: a step keeps its own id, else the id of the step it was (same title
 * and occurrence in `previous`), else a new one. Ids are unique within the plan. */
export function withStepIds<B extends { steps: PlanStep[] }>(brief: B, previous?: { steps: PlanStep[] } | null, newId = () => randomUUID().slice(0, 8)): B {
  const before = previous?.steps ?? [], beforeKeys = stepKeys(before), afterKeys = stepKeys(brief.steps), used = new Set<string>();
  const steps = brief.steps.map((step, i) => {
    let id = typeof step.id === 'string' && STEP_ID.test(step.id) && !used.has(step.id) ? step.id : undefined;
    if (!id) { const was = before[beforeKeys.indexOf(afterKeys[i])]?.id; if (was && STEP_ID.test(was) && !used.has(was)) id = was; }
    while (!id || used.has(id)) id = newId();
    used.add(id);
    return { ...step, id };
  });
  return { ...brief, steps };
}

const markOf = (marks: StepMarks | undefined, key: string): StepMark | undefined => marks && Object.hasOwn(marks, key) ? marks[key] : undefined;

/** Steps that never run again: done (ticked), skipped, or met by the artist. */
export function closedSteps(keys: readonly string[], marks: StepMarks | undefined, done: readonly number[] = []): Set<number> {
  const closed = new Set(done.filter(i => i >= 0 && i < keys.length));
  keys.forEach((key, i) => { const mark = markOf(marks, key); if (mark?.skipped || mark?.met) closed.add(i); });
  return closed;
}

/** The first step from `from` on that is not closed; the plan's length when there is none. */
export function openStepFrom(keys: readonly string[], marks: StepMarks | undefined, done: readonly number[] = [], from = 0): number {
  const closed = closedSteps(keys, marks, done);
  for (let i = Math.max(0, from); i < keys.length; i++) if (!closed.has(i)) return i;
  return keys.length;
}

/** A move's step in the plan as it is now: by identity, else by index for a move without one. */
function moveStep(move: Move | undefined, keys: readonly string[]): number {
  if (!move) return -1;
  if (move.step_key) return keys.indexOf(move.step_key);
  return Number.isInteger(move.step) && (move.step ?? -1) < keys.length ? move.step ?? -1 : -1;
}

/** The last Agent move, while it waits for Keep / Undo (whatever the goal's status: paused, limited…). */
function readyMove(goal: Goal): Move | undefined {
  const move = goal.moves?.at(-1);
  return move?.status === 'ready' ? move : undefined;
}

/** The panel's plan list: each step with its state (the panel shows the buttons that state allows). */
export function planStepView(goal: Goal | null, { mode, busy, currentMove, folder = false, pending = null }: ViewOptions): StepView[] {
  const steps = goal?.brief?.steps ?? [];
  if (!goal || !steps.length) return [];
  const keys = stepIdentities(steps, folder), marks = goal.step_marks ?? {}, done = new Set(goal.done_steps ?? []);
  const painting = !busy ? -1 : mode === 'agent' ? moveStep(currentMove, keys)
    : mode === 'autopilot' && ['active', 'reviewing'].includes(goal.status ?? '') ? goal.current_step ?? 0 : -1;
  const ready = readyMove(goal), finished = ready && !ready.guides_only ? moveStep(ready, keys) : -1;
  return steps.map((step, index) => {
    const key = keys[index], mark = markOf(marks, key);
    const state: StepState = index === painting ? (pending === key ? 'finishing' : 'painting') : mark?.skipped ? 'skipped'
      : index === finished ? 'finished' : mark?.met === 'artist' ? 'met' : mark?.met === 'good_enough' ? 'good_enough' : done.has(index) ? 'done' : 'open';
    const batches = goal.step_batches?.[key] ?? 0, scope = step.scope?.trim() ?? '';
    return { index, key, title: layerName(step.title), state, ...(mark?.redone ? { redone: mark.redone } : {}),
      ...(IMAGE_SCOPE.test(scope) ? { source: scope } : {}), ...(batches > 0 ? { batches } : {}) };
  });
}

/** For the painter's (and the planner's) context: the steps the artist skipped or marked met. */
export function stepMarksContext(steps: readonly PlanStep[], marks: StepMarks | undefined, folder = false) {
  const keys = stepIdentities(steps, folder);
  const listed = steps.flatMap((step, i) => {
    const mark = markOf(marks, keys[i]);
    return mark?.skipped ? [{ step: i + 1, title: layerName(step.title), artist: 'skipped' }] : mark?.met ? [{ step: i + 1, title: layerName(step.title), artist: 'met' }] : [];
  });
  return listed.length ? { note: 'The artist skipped some plan steps and marked others met. Never paint a skipped step, never add it back to a plan, and paint nothing more for a met step.', steps: listed } : undefined;
}

/** One lesson appended to the chat folder's LESSONS_FILE (JSON lines), opened without following a link or blocking on
 * anything but a plain file. */
export async function recordLesson(directory: string, lesson: Record<string, unknown>): Promise<void> {
  const path = join(await realpath(directory), LESSONS_FILE);
  let handle;
  try { handle = await open(path, constants.O_WRONLY | constants.O_CREAT | constants.O_APPEND | constants.O_NOFOLLOW | constants.O_NONBLOCK, 0o600); }
  catch (error) {
    if (['ELOOP', 'EMLINK'].includes((error as NodeJS.ErrnoException).code ?? '')) throw new Error(`${basename(path)} is a link; lessons never follow links.`);
    if ((error as NodeJS.ErrnoException).code === 'ENXIO') throw new Error(`${basename(path)} is not a plain file.`);
    throw error;
  }
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.nlink > 1) throw new Error(`${basename(path)} is not a plain file; lessons never follow links.`);
    await handle.write(JSON.stringify(lesson) + '\n', null, 'utf8');
  } finally { await handle.close(); }
}

/** The controls over one chat: the panel's commands and the studio's hooks around painting calls and runs. */
export function planStepControls(host: PlanStepHost) {
  let inFlight = 0;
  let redirect: string | null = null;                      // Autopilot: the next painting call is refused with this
  let pendingKey: string | null = null;                    // Autopilot: "good enough" waiting for the batch in progress
  let pendingMove: Move | null = null;                     // Agent: the move "good enough" ends (this run only)
  let working = false;                                     // a Met / Redo (or the automatic keep) is under way

  const goalOf = (): Goal => { const goal = host.getGoal(); if (!goal?.brief?.steps?.length) throw new Error('There is no plan.'); return goal; };
  const stepsOf = (goal: Goal) => goal.brief?.steps ?? [];
  const keysOf = (goal: Goal) => stepIdentities(stepsOf(goal), host.folder());
  const mark = (goal: Goal, key: string, change: (mark: StepMark) => StepMark) => {
    const next = change({ ...(markOf(goal.step_marks, key) ?? {}) });
    const marks = { ...(goal.step_marks ?? {}) };
    if (Object.keys(next).length) marks[key] = next; else delete marks[key];
    goal.step_marks = marks;
  };
  const firstOpen = (goal: Goal, from = 0) => openStepFrom(keysOf(goal), goal.step_marks, goal.done_steps ?? [], from);
  const tick = (goal: Goal, index: number) => { goal.done_steps = [...new Set([...(goal.done_steps ?? []), index])].sort((a, b) => a - b); };
  const save = async () => { await host.syncPlan(); await host.persist(); host.publish(); };
  const view = (goal: Goal) => planStepView(goal, { mode: host.mode(), busy: host.busy(), currentMove: host.currentMove(), folder: host.folder(), pending: pendingOf(goal) });
  const pendingOf = (goal: Goal): string | null => {
    if (pendingKey) return pendingKey;
    const keys = keysOf(goal), index = pendingMove ? moveStep(pendingMove, keys) : -1;
    return index >= 0 ? keys[index] : null;
  };
  const keyOfCurrent = (goal: Goal): string | undefined => {
    const keys = keysOf(goal);
    if (host.mode() === 'agent') { const index = moveStep(host.currentMove(), keys); return index >= 0 ? keys[index] : undefined; }
    return keys[Math.min(goal.current_step ?? 0, keys.length - 1)];
  };

  async function lesson(goal: Goal, kind: 'good_enough' | 'redo', index: number, move: Move | undefined, text?: string) {
    const directory = host.chatDirectory();
    if (!directory) return;
    const steps = stepsOf(goal), key = keysOf(goal)[index];
    const pace = (goal.pace_history ?? []).filter(entry => entry.step === index).at(-1);
    const luna = move?.review || move?.review_line ? { verdict: move.review?.verdict ?? null, line: move.review_line ?? null }
      : pace || goal.reviews?.length ? { pace: pace ? { progress: pace.progress ?? null, action: pace.action ?? null } : null, review: goal.reviews?.at(-1)?.verdict ?? null }
      : null;
    try {
      await recordLesson(directory, { kind, at: new Date().toISOString(), mode: host.mode(), step: { number: index + 1, title: layerName(steps[index].title), key },
        batches: goal.step_batches?.[key] ?? 0, ...(move ? { move: move.number } : {}), luna, goal_likeness: host.goalLikeness(),
        ...(move?.likeness?.luna ? { goal_comparison: move.likeness.luna } : {}), ...(text ? { text } : {}) });
    } catch (error) { host.say('The lesson was not recorded: ' + (error as Error).message); }
  }

  /** A move the controls answer: the last move, ready, in Agent mode, that painted a step still in the plan. */
  function checkReady(goal: Goal, move: Move | undefined): { move: Move; index: number } {
    if (host.mode() !== 'agent') throw new Error('Met and Redo answer an Agent move: switch to Agent first.');
    if (host.busy() || working) throw new Error('Wait for the painting in progress to finish.');
    const ready = readyMove(goal);
    if (!move || move !== ready) throw new Error('There is no painted move to review.');
    const index = moveStep(move, keysOf(goal));
    if (index < 0 || move.guides_only) throw new Error('That move painted no step of the plan as it is now.');
    return { move, index };
  }

  /** The step is met: its move kept first (when there is one), then marked and ticked; the next open step is painted
   * when the plan may go on, or the plan finishes. */
  async function stepMet(goal: Goal, index: number, move: Move | undefined, source: 'artist' | 'good_enough', auto: boolean) {
    const keys = keysOf(goal), key = keys[index];
    if (move) await host.keepMove(move);
    mark(goal, key, m => ({ ...m, met: source }));
    let next: number;
    if (move && host.folder()) next = await host.tickFolderStep(move);
    else {
      tick(goal, index);
      next = firstOpen(goal);                                // a step restored earlier is painted first
      if (next < keys.length) goal.current_step = next;
      await save();
    }
    working = false;
    if (next >= keys.length) { await host.finish('Every step of the plan is met, done or skipped.'); return; }
    if (host.mayContinue(auto)) { await host.nextStepMove(); return; }
    await host.persist(); host.publish();
    host.say(`Step ${index + 1} is met. Press Start painting to go on with step ${next + 1}.`);
  }

  /** Autopilot: the pending "good enough" step is met; the run carries on with the next open step. Returns the note. */
  function advance(goal: Goal): string | null {
    const key = pendingKey;
    pendingKey = null;
    const steps = stepsOf(goal), index = key ? keysOf(goal).indexOf(key) : -1;
    if (index < 0) return null;
    mark(goal, key as string, m => ({ ...m, met: 'good_enough' }));
    tick(goal, index);
    const current = goal.current_step ?? 0, next = firstOpen(goal, Math.max(index + 1, current !== index ? current : 0));
    const what = `the artist marked step ${index + 1} ("${layerName(steps[index].title)}") good enough: paint nothing more for it.`;
    void save().catch(() => {});
    if (next >= steps.length) return what + ' Every step of the plan is met or skipped: request review when the whole painting meets the completion criteria.';
    goal.current_step = next;
    host.say('Moving on to: ' + layerName(steps[next].title));
    return `${what} Now paint step ${next + 1}: "${steps[next].title}" — ${steps[next].done_when ?? ''}`.trim();
  }

  const controls = {
    /** A panel command (validated here). Met and Redo go through the studio's Keep and Undo of the move. */
    async command(raw: unknown, review: (move: Move, action: 'keep' | 'undo', note?: string) => Promise<void>): Promise<void> {
      const command = parsePlanStepCommand(raw), goal = goalOf(), steps = stepsOf(goal);
      const index = keysOf(goal).indexOf(command.step_key);
      if (index < 0) throw new Error('That step is no longer in the plan.');
      const state = view(goal)[index].state, name = `step ${index + 1} (${layerName(steps[index].title)})`;
      if (command.action === 'skip') {
        if (['painting', 'finishing'].includes(state)) throw new Error(`Step ${index + 1} is painting: use Good enough → next step instead.`);
        if (state === 'finished') throw new Error(`Step ${index + 1} has finished: choose Met or Redo.`);
        if (state !== 'open') throw new Error(state === 'skipped' ? `Step ${index + 1} is already skipped.` : `Step ${index + 1} is already met.`);
        mark(goal, command.step_key, m => ({ ...m, skipped: true }));
        if (!host.busy() && (goal.current_step ?? 0) === index) goal.current_step = Math.min(firstOpen(goal, host.folder() ? 0 : index), steps.length - 1);
        await save(); host.say(`Skipped ${name}: it will not be painted.`); return;
      }
      if (command.action === 'restore') {
        if (state !== 'skipped') throw new Error(`Step ${index + 1} is not skipped.`);
        mark(goal, command.step_key, ({ skipped, ...rest }) => rest);
        if (!host.busy()) goal.current_step = host.folder() ? Math.min(firstOpen(goal), steps.length - 1) : Math.min(goal.current_step ?? 0, index);
        await save(); host.say(`Restored ${name}.`); return;
      }
      if (command.action === 'good_enough') {
        if (state === 'finishing') return;                     // pressed twice
        if (state !== 'painting') throw new Error(`Step ${index + 1} is not painting.`);
        const move = host.currentMove();
        await lesson(goal, 'good_enough', index, host.mode() === 'agent' ? move : undefined);
        if (host.mode() === 'agent' && move) {
          pendingMove = move; move.finished = true;            // the move ends after the turn in progress
          host.say(`Good enough: ${name} ends after the batch in progress, then the next step starts.`);
          await host.persist(); host.publish();
          if (!host.busy()) await controls.afterRun();
          return;
        }
        pendingKey = command.step_key;
        if (!inFlight) redirect = advance(goal);              // between calls: on at once; the next call is redirected
        else host.say(`Good enough: ${name} ends after the batch in progress.`);
        await host.persist(); host.publish(); return;
      }
      if (state !== 'finished') throw new Error(`Step ${index + 1} has not finished a move to review.`);
      const { move } = checkReady(goal, readyMove(goal));
      await review(move, command.action === 'met' ? 'keep' : 'undo', command.text);
    },
    /** Does Keep / Undo of this move answer a plan step (Met / Redo)? */
    stepped(move: Move | undefined): boolean {
      const goal = host.getGoal();
      return !!goal?.brief?.steps?.length && !!move && !move.guides_only && moveStep(move, keysOf(goal)) >= 0;
    },
    /** Met: the move kept, the step met by the artist, the next open step painted. The move card's Keep comes here. */
    async met(move: Move): Promise<void> {
      const goal = goalOf(), { index } = checkReady(goal, move);
      const owed = host.metRefusal?.(move);
      if (owed) throw new Error(owed);
      working = true;
      try { await stepMet(goal, index, move, 'artist', false); } finally { working = false; }
    },
    /** Redo: the move undone, then the redo counted and its lesson kept, then the same step painted again. The move
     * card's Undo comes here. */
    async redo(move: Move, note?: string): Promise<void> {
      const goal = goalOf(), { index } = checkReady(goal, move);
      working = true;
      try {
        await host.rejectMove(move);
        mark(goal, keysOf(goal)[index], m => ({ ...m, redone: (m.redone ?? 0) + 1 }));
        await lesson(goal, 'redo', index, move, note);
        await save();
      } finally { working = false; }
      await host.retryMove(move, note);
    },
    /** Before a painting call: refused after "good enough" (Agent: nothing more this move, except resuming a reference
     * job the move started; Autopilot: once, redirected). */
    beforeBatch(call?: Call): void {
      const move = host.currentMove(), goal = host.getGoal();
      if (host.mode() === 'agent' && move && move === pendingMove) {
        const job = call?.tool === 'continue_reference_painting' ? String(call.args?.job_id ?? '') : '';
        if (!job || !(goal?.reference_jobs?.[job] ?? []).includes(move.number))
          throw new Error('Nothing was painted: the artist marked this step good enough. Paint nothing more; stop now.');
      }
      if (redirect) { const note = redirect; redirect = null; throw new Error('Nothing was painted: ' + note); }
      if (goal && pendingKey && !inFlight) { const note = advance(goal); if (note) throw new Error('Nothing was painted: ' + note); }
      inFlight++;
    },
    /** After a painting call ran (or failed): counted for the step it painted. */
    batchEnded(): void {
      inFlight = Math.max(0, inFlight - 1);
      const goal = host.getGoal();
      if (!goal?.brief?.steps?.length) return;
      const key = keyOfCurrent(goal);
      if (key) goal.step_batches = { ...(goal.step_batches ?? {}), [key]: (goal.step_batches?.[key] ?? 0) + 1 };
    },
    /** After the painting call's own checks: Autopilot's pending "good enough" applies now, and the painter is told. */
    afterBatch<R extends { content?: unknown[] }>(response: R): R {
      const goal = host.getGoal();
      if (!goal || !pendingKey || inFlight) return response;
      const note = advance(goal);
      return note && Array.isArray(response?.content) ? { ...response, content: [...response.content, { type: 'text', text: JSON.stringify({ host_pacing: note }) }] } : response;
    },
    /** After a run ended (the panel is free): Autopilot's "good enough" is recorded; an Agent move ended by it is kept and
     * the next step starts, when the plan may go on. Only for the run that just ended: nothing carries over a resume. */
    async afterRun(): Promise<void> {
      const goal = host.getGoal();
      redirect = null;
      if (!goal?.brief?.steps?.length) { pendingKey = null; pendingMove = null; return; }
      if (pendingKey) { advance(goal); await host.persist(); host.publish(); }
      const move = pendingMove;
      if (!move || host.busy()) return;
      pendingMove = null;
      if (move !== goal.moves?.at(-1)) return;                // another chat, or a later move
      const index = moveStep(move, keysOf(goal));
      if (index < 0) { await host.persist(); host.publish(); return; }
      working = true;
      try { await stepMet(goal, index, move.status === 'ready' ? move : undefined, 'good_enough', true); } finally { working = false; }
    },
    /** Start painting: the current step is the first open one from where the plan stands. False when none is open. */
    settleCurrent(): boolean {
      const goal = host.getGoal();
      if (!goal?.brief?.steps?.length) return true;
      const keys = keysOf(goal), current = Math.min(goal.current_step ?? 0, keys.length - 1);
      if (!closedSteps(keys, goal.step_marks, goal.done_steps ?? []).has(current)) return true;
      const next = firstOpen(goal, host.folder() ? 0 : current), anywhere = next < keys.length ? next : firstOpen(goal, 0);
      if (anywhere >= keys.length) return false;
      goal.current_step = anywhere; return true;
    },
    /** Pacing's next step, past skipped and met ones; -1 when none is left. */
    nextOpen(step: number): number {
      const goal = host.getGoal();
      if (!goal?.brief?.steps?.length) return step;
      const keys = keysOf(goal), marks = goal.step_marks;
      for (let i = Math.max(0, step); i < keys.length; i++) { const m = markOf(marks, keys[i]); if (!m?.skipped && !m?.met) return i; }
      return -1;
    },
    /** What pacing tells the painter about the steps it jumps over from `from` to `to`: shown on the canvas, or the artist's. */
    jumpNote(from: number, to: number): string {
      const between = Array.from({ length: Math.max(0, to - from - 1) }, (_, i) => from + 1 + i);
      const shown = between.filter(i => !controls.isClosed(i)).map(i => i + 1), artist = between.filter(i => controls.isClosed(i)).map(i => i + 1);
      const list = (n: number[]) => `step${n.length > 1 ? 's' : ''} ${n.join(', ')}`;
      return (shown.length ? ` The canvas already shows ${list(shown)}.` : '') + (artist.length ? ` The artist skipped or marked met ${list(artist)}: paint nothing for ${artist.length > 1 ? 'them' : 'it'}.` : '');
    },
    /** Skipped or met by the artist: the step never runs again. */
    isClosed(step: number): boolean {
      const goal = host.getGoal(), steps = goal?.brief?.steps ?? [];
      const mark = goal && step >= 0 && step < steps.length ? markOf(goal.step_marks, keysOf(goal)[step]) : undefined;
      return !!(mark?.skipped || mark?.met);
    },
    isSkipped(step: number): boolean {
      const goal = host.getGoal(), steps = goal?.brief?.steps ?? [];
      return !!goal && step >= 0 && step < steps.length && !!markOf(goal.step_marks, keysOf(goal)[step])?.skipped;
    },
    /** The identity of step `index` (what a move records). */
    keyAt(index: number): string | undefined { const goal = host.getGoal(); return goal?.brief?.steps?.length ? keysOf(goal)[index] : undefined; },
    /** The step a retry repaints: the redone move's, by identity; -1 when it is gone. */
    indexOf(key: string | undefined): number { const goal = host.getGoal(); return key && goal?.brief?.steps?.length ? keysOf(goal).indexOf(key) : -1; },
    /** For the panel's view. */
    view(goal: Goal | null): StepView[] { return goal ? view(goal) : []; },
    working(): boolean { return working; },
  };
  return controls;
}
export type PlanStepControls = ReturnType<typeof planStepControls>;
