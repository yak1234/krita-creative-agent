// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The plan follows the request (openspec plan-from-request goals 1-3, approved by the artist 2026-10-24: "yes please").
// A project folder always got the same four steps, whatever the artist asked: "paint the underpainting" still queued the
// Finish, Refine and Accents. Now the stages a folder plan holds come from the artist's message:
//
// - Luna's reading (message-reading.ts, the same single call that reads each Agent message) answers, while a folder plan is
//   made, whether the message asks for the whole painting, only some stages, or neither, and which stages. It decides when
//   it acts (Decision checks on Guide) and is sure (SURE). The keywords (stagesNamed) are the fallback; with Luna off or not
//   acting they decide, and a message that names no stage gets the full plan (as before: nothing paints before Start
//   painting, so the artist sees it first). Only when Luna acts, is unsure, and the keywords name nothing, the plan card
//   asks (STAGE_CARD).
// - The host keeps the order rules (orderStages): an underpainting before anything that needs one, Refine only after a
//   whole-picture Finish, Accents last. The finish and refine tools refuse a canvas with no underpainting, and refining
//   before the finish would refine the dabbed underpainting (finish-stage goal 8).
// - The steps (folderPlanSteps): one a stage; the refine stage is a refine step per group of the folder's elements
//   (refine-parts.ts), or one whole-picture "Refine to the goal" for a folder without elements. Each step records its kind
//   and tool; the planner may reword titles and checks and regroup the parts, but shapePlan holds the stages to what was
//   asked, in order, and checks each tool (stepTool).
// Mechanism only: the studio asks and applies (studio.mjs planFolder); this module imports no .mjs.
import { SURE, PLAN_STAGES, type PlanStage, type Reading } from './message-reading.ts';
import { folderStepKind, UNDERPAINTING_STEP, FINISH_STEP, REFINE_STEP, ACCENTS_STEP, type FolderStep, type FolderStepKind } from './project-folder.ts';
import { groupName, refineStep, type RefineGroup } from './refine-parts.ts';

export { PLAN_STAGES, type PlanStage };
export type StageSource = 'luna' | 'keywords' | 'default' | 'card' | 'ask';
/** stages null: ask the artist (the plan card). whole: the message asked for the whole painting (or named no stage). */
export type StageAnswer = { stages: PlanStage[] | null; whole: boolean; source: StageSource };
type Element = { name: string; guess: string };
type Step = FolderStep & { checks?: string[]; id?: string };

const WHOLE = 'whole composition';
/** A step that names guides: the artist asked for them (as studio.mjs GUIDES_STEP). */
const GUIDES = /\b(?:guides?|trac(?:e|ing)|construction lines?)\b/i;
const ALL = (): PlanStage[] => [...PLAN_STAGES];
const fold = (text: string) => text.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[‘’]/g, "'");
// A negation splits its clause: what comes before it is asked for, what follows is taken away ("paint everything except
// the accents": the whole set without accents; review 2026-10-24). "later" and "not yet" take the whole clause away.
const NEGATED = /\b(?:no|not|don'?t|do not|never|without|skip|except|avoid|leave out|no need|drop|remove|take out)\b/;
const POSTPONED = /\blater\b|\bnot yet\b/;
/** A clause asks for a stage (rather than talking about it, "the highlights are too bright"): a verb of asking. */
const ASKING = /\b(?:add|paint|do|include|also|now|next|then|start|run|want|please|plus|let'?s|continue with|go on with|move on to|actually)\b/;
const WHOLE_WORDS = /\b(?:whole (?:thing|painting|picture|plan|lot)|everything|all of it|it all|like the goal|as the goal (?:image )?shows|full plan|all (?:the )?(?:stages|steps)|(?:from )?start to finish|the complete painting|finish (?:it|the (?:painting|picture)))\b/;
const STAGE_WORDS: Record<PlanStage, RegExp> = {
  underpainting: /\bunder-?paint(?:ing)?\b|\bblock[- ]?in\b|\blay[- ]?in\b/,
  finish: /(?<!\bto )\bfinish(?:ing)?\b(?!\s+(?:it|the (?:painting|picture|whole)))|\bblend(?:ing)?\b/,
  refine: /\brefin(?:e|ing|ement)\b|\bdetail(?:s|ing)?\b/,
  accents: /\baccents?\b|\bhighlights?\b|\bglints?\b/,
};

/** The stages a message names by keyword, in their painting order, whether it asks for the whole painting, and the stages
 * it says not to do (`removed`: named after a negation, or in a clause put off for later). `explicit`: only a clause
 * with a verb of asking counts as asking (a later request on a plan, a revision of a draft). */
export function stagesNamed(text: string, { explicit = false }: { explicit?: boolean } = {}): { stages: PlanStage[]; whole: boolean; removed: PlanStage[] } {
  const asked: string[] = [], refused: string[] = [];
  for (const clause of fold(String(text ?? '')).split(/[.!?;,\n]|\bbut\b/)) {
    if (POSTPONED.test(clause)) { refused.push(clause); continue; }
    const at = NEGATED.exec(clause)?.index ?? -1;
    const before = at < 0 ? clause : clause.slice(0, at);
    if (at >= 0) refused.push(clause.slice(at));
    if (!explicit || ASKING.test(before)) asked.push(before);
  }
  const removed = PLAN_STAGES.filter(stage => refused.some(c => STAGE_WORDS[stage].test(c)));
  return { stages: PLAN_STAGES.filter(stage => !removed.includes(stage) && asked.some(c => STAGE_WORDS[stage].test(c))),
    whole: asked.some(c => WHOLE_WORDS.test(c)), removed };
}

/** What the plan holds for this message (see the header). `act`: Luna acts (Decision checks on Guide). A stage the
 * message says not to do is taken away from any answer, the whole set included. */
export function stagePolicy({ reading, act, text }: { reading: Reading | null; act: boolean; text: string }): StageAnswer {
  const named = stagesNamed(text), minus = (answer: StageAnswer): StageAnswer => !answer.stages || !named.removed.length ? answer
    : { ...answer, stages: answer.stages.filter(stage => !named.removed.includes(stage)), whole: false };
  const keywords: StageAnswer | null = named.whole ? { stages: ALL(), whole: true, source: 'keywords' }
    : named.stages.length ? { stages: named.stages, whole: false, source: 'keywords' } : null;
  const fallback: StageAnswer = keywords ?? { stages: ALL(), whole: true, source: 'default' };
  const read = reading && !reading.fallback ? reading.stages : null;
  if (!act || !read) return minus(fallback);
  const scope = read.scope && read.scope.confidence >= SURE ? read.scope.choice : null;
  if (scope === 'whole') return minus({ stages: ALL(), whole: true, source: 'luna' });
  if (scope === 'stages') {
    const asked = PLAN_STAGES.filter(stage => (read.asked[stage] ?? 0) >= SURE);
    if (asked.length) return minus({ stages: asked, whole: false, source: 'luna' });
    return minus(keywords ?? { stages: null, whole: false, source: 'ask' });
  }
  if (scope === 'neither') return minus(fallback);
  return minus(keywords ?? { stages: null, whole: false, source: 'ask' });
}

/** A message that revises a plan already drafted, or asks more of an approved one (review 2026-10-24: "rename the finish
 * step" dropped Refine and Accents; "use warmer colours" grew an underpainting into the full plan). The plan keeps its
 * stages; only those the message explicitly asks for are added (a verb of asking, or Luna acting, sure and with such a
 * verb's meaning: scope "stages"), only those it says not to do are removed, and nothing falls back to the full plan. */
export function reviseStages({ current, reading, act, text }: { current: readonly PlanStage[]; reading: Reading | null; act: boolean; text: string }):
  { stages: PlanStage[]; added: PlanStage[]; removed: PlanStage[]; source: StageSource } {
  const named = stagesNamed(text, { explicit: true });
  const read = act && reading && !reading.fallback ? reading.stages : null;
  const lunaScope = read?.scope && read.scope.confidence >= SURE ? read.scope.choice : null;
  const luna = lunaScope === 'whole' ? ALL() : lunaScope === 'stages' ? PLAN_STAGES.filter(stage => (read!.asked[stage] ?? 0) >= SURE) : [];
  const ask = new Set<PlanStage>([...(named.whole ? ALL() : named.stages), ...luna]);
  const want = PLAN_STAGES.filter(stage => (current.includes(stage) || ask.has(stage)) && !named.removed.includes(stage));
  const ordered = orderStages(want).stages.filter(stage => !named.removed.includes(stage) || ask.has(stage));
  return { stages: ordered, added: ordered.filter(stage => !current.includes(stage)), removed: current.filter(stage => !ordered.includes(stage)),
    source: luna.length && !named.stages.length && !named.whole ? 'luna' : 'keywords' };
}

/** The plan card shown when the stages are unclear (the existing question card: goal.question with these options). */
export const STAGE_CARD = Object.freeze({
  question: 'Which stages should the plan hold? I could not tell from your message.',
  options: ['The underpainting only', 'Underpainting and finish', 'The whole plan'] as string[],
});
/** The stages a plan card answer gives, or null for anything else (typed text is read as a new message). */
export function stagesFromCard(answer: string): PlanStage[] | null {
  const at = STAGE_CARD.options.indexOf(String(answer ?? '').trim());
  return at === 0 ? ['underpainting'] : at === 1 ? ['underpainting', 'finish'] : at === 2 ? ALL() : null;
}

const WHY: Partial<Record<PlanStage, string>> = {
  underpainting: 'the finish, refining and accents work over an underpainting, so the plan starts with one',
  finish: 'Refine comes only after a whole-picture Finish, so the plan holds the Finish first',
};
/** The order rules: the stages asked, with what they need added (unless `done` in this chat already), in painting order. */
export function orderStages(asked: readonly PlanStage[], { done = [] }: { done?: readonly PlanStage[] } = {}): { stages: PlanStage[]; added: { stage: PlanStage; because: string }[] } {
  const want = new Set(asked), added: { stage: PlanStage; because: string }[] = [];
  const need = (stage: PlanStage) => { if (!want.has(stage) && !done.includes(stage)) { want.add(stage); added.push({ stage, because: WHY[stage]! }); } };
  if (want.has('refine')) need('finish');
  if (want.size && !want.has('underpainting') && [...want].some(s => s !== 'underpainting')) need('underpainting');
  return { stages: PLAN_STAGES.filter(stage => want.has(stage)), added: added.sort((a, b) => PLAN_STAGES.indexOf(a.stage) - PLAN_STAGES.indexOf(b.stage)) };
}

/** The tools a step of each kind paints with (the first is the kind's own); null: any painting tool. */
export const KIND_TOOLS: Readonly<Record<FolderStepKind, readonly string[] | null>> = Object.freeze({
  underpainting: ['paint_from_reference'], finish: ['paint_finish'], refine: ['refine_to_goal'], refine_part: ['refine_to_goal'],
  accents: ['paint_accents'], element: ['paint_from_reference', 'paint_finish', 'paint_accents', 'refine_to_goal'], whole: null,
});
/** A step's tool, checked: kept when it is one of `known` and fits the step's kind, else the kind's own tool (with a note
 * for the diagnostics). A whole-picture step of the artist's may use any painting tool; an unknown one is dropped. */
export function stepTool(step: { kind?: FolderStepKind; tool?: string }, known: readonly string[]): { tool?: string; note?: string } {
  const kind = step.kind ?? 'whole', fits = KIND_TOOLS[kind], own = fits?.[0];
  const tool = typeof step.tool === 'string' ? step.tool.trim() : '';
  if (!tool) return own ? { tool: own } : {};
  if (!known.includes(tool)) return own ? { tool: own, note: `${tool} is not a painting tool: ${own}` } : { note: `${tool} is not a painting tool` };
  if (fits && !fits.includes(tool)) return { tool: own, note: `${tool} does not do a ${kind} step: ${own}` };
  return { tool };
}

const STAGE_STEP: Record<Exclude<PlanStage, 'refine'>, () => Step> = {
  underpainting: () => ({ title: UNDERPAINTING_STEP, done_when: 'The goal image’s colours and light are laid over the whole canvas, every element where the goal image has it.', scope: WHOLE, kind: 'underpainting', tool: 'paint_from_reference' }),
  finish: () => ({ title: FINISH_STEP, done_when: 'The soft areas (sky, mist, water) are blended smooth and the forms are painted in strokes that follow them, from the goal image, on the whole picture.', scope: WHOLE, kind: 'finish', tool: 'paint_finish' }),
  accents: () => ({ title: ACCENTS_STEP, done_when: 'The lights, darks and fine detail the goal image shows are crisp on the whole picture, in the underpainting’s own paint.', scope: WHOLE, kind: 'accents', tool: 'paint_accents' }),
};
const wholeRefine = (): Step => ({ title: REFINE_STEP, done_when: 'Every part of the picture is close to the goal image at full size: its forms, windows and edges as crisp as the goal shows them.', scope: WHOLE, kind: 'refine', tool: 'refine_to_goal' });

/** The steps for these stages (already in order): the refine stage is one step a group of parts, or one whole-picture step. */
export function folderPlanSteps(stages: readonly PlanStage[], groups: readonly RefineGroup[]): Step[] {
  return stages.flatMap(stage => stage === 'refine' ? (groups.length ? groups.map(refineStep) : [wholeRefine()]) : [STAGE_STEP[stage]()]);
}

/** The stage a step of this kind belongs to, or null (an element or the artist's own whole-picture step). */
const stageOf = (kind: FolderStepKind): PlanStage | null =>
  kind === 'refine_part' ? 'refine' : (PLAN_STAGES as readonly string[]).includes(kind) ? kind as PlanStage : null;

/** The stages of the folder plan not yet in it, in order: what a later request may add (the end of a plan offers them). */
export function nextStages(steps: readonly { title: string; scope?: string; kind?: string }[]): PlanStage[] {
  const have = new Set(steps.map(step => stageOf(folderStepKind(step))).filter(Boolean));
  return PLAN_STAGES.filter(stage => !have.has(stage));
}

/** Groups the planner proposed are used when they cover every element of the folder once, in 1-7 non-empty groups. */
function validGroups(groups: string[][], elements: readonly Element[]): boolean {
  const names = elements.map(e => e.name), seen = groups.flat();
  return groups.length >= 1 && groups.length <= 7 && groups.every(g => g.length) && seen.length === names.length
    && new Set(seen).size === seen.length && seen.every(name => names.includes(name));
}

/**
 * The planner's proposal shaped by the host: the stage steps are the draft's (the stages the artist asked for, in order),
 * each keeping the planner's words when it proposed a step of that kind (its title too when the title still reads as that
 * kind, so an older reader of PLAN.md finds it); the refine steps are the planner's groups when valid, else the draft's;
 * the artist's own whole-picture steps (a guides step) follow the underpainting and element steps come last. Every tool
 * is checked (stepTool). `dropped`: the titles of stage steps the artist did not ask for; `notes`: tool corrections.
 */
export function shapePlan(proposed: readonly Step[], { draft, elements, known, keepWhole = [] }: { draft: readonly Step[]; elements: readonly Element[]; known: readonly string[];
  /** Titles of whole-picture steps the artist made (in PLAN.md or the plan editor): kept. */ keepWhole?: readonly string[] }):
  { steps: Step[]; dropped: string[]; notes: string[] } {
  const kinds = proposed.map(step => folderStepKind(step));
  const asked = new Set(draft.map(step => stageOf(folderStepKind(step))));
  // A whole-picture step the request did not ask for is a stage under another name ("Blend and restroke the forms" for
  // "paint the underpainting"; review 2026-10-24): only a guides step and the artist's own steps stay.
  const kept = new Set(keepWhole.map(t => t.trim().toLowerCase()));
  const wholeKept = (step: Step) => GUIDES.test(`${step.title} ${step.done_when ?? ''}`) || kept.has(String(step.title).trim().toLowerCase());
  const dropped = proposed.filter((step, i) => { const stage = stageOf(kinds[i]!); return stage ? !asked.has(stage) : kinds[i] === 'whole' && !wholeKept(step); }).map(step => step.title);
  const pool = new Map<FolderStepKind, Step[]>();
  proposed.forEach((step, i) => { const kind = kinds[i]!; if (stageOf(kind)) pool.set(kind, [...(pool.get(kind) ?? []), step]); });
  const words = (mine: Step, theirs: Step | undefined): Step => {
    if (!theirs) return mine;
    const kind = folderStepKind(mine), title = String(theirs.title ?? '').trim();
    const keep = title && folderStepKind({ title }) === kind;
    return { ...mine, ...(keep ? { title: title.slice(0, 200) } : {}), ...(theirs.done_when ? { done_when: theirs.done_when } : {}),
      ...(theirs.checks?.length ? { checks: theirs.checks } : {}), ...(theirs.id ? { id: theirs.id } : {}), ...(theirs.tool ? { tool: theirs.tool } : {}) };
  };
  const theirParts = (pool.get('refine_part') ?? []).map(step => (Array.isArray(step.parts) ? step.parts : []).map(String));
  const regroup = draft.some(step => folderStepKind(step) === 'refine_part') && validGroups(theirParts, elements);
  const stageSteps: Step[] = [];
  let refined = false;
  for (const step of draft) {
    const kind = folderStepKind(step);
    if (kind === 'refine_part') {
      if (regroup) {
        if (!refined) for (const [i, theirs] of (pool.get('refine_part') ?? []).entries()) {
          const parts = theirParts[i]!, label = String(theirs.title ?? '').replace(/^\s*refine\s*:\s*/i, '').trim();
          const own = refineStep({ parts, label: label || groupLabel(parts, elements) });
          stageSteps.push({ ...words(own, { ...theirs, title: '' }), title: own.title });
        }
        refined = true;
      } else stageSteps.push(words(step, pool.get('refine_part')?.shift()));
      continue;
    }
    stageSteps.push(words(step, pool.get(kind)?.shift()));
  }
  const whole = proposed.filter((step, i) => kinds[i] === 'whole' && wholeKept(step)), element = proposed.filter((_, i) => kinds[i] === 'element');
  const at = stageSteps.findIndex(step => folderStepKind(step) === 'underpainting') + 1;
  const ordered = [...stageSteps.slice(0, at), ...whole, ...stageSteps.slice(at), ...element].slice(0, 16);
  const notes: string[] = [];
  const steps = ordered.map(step => {
    const kind = folderStepKind(step), checked = stepTool({ kind, tool: step.tool }, known);
    if (checked.note) notes.push(`${step.title}: ${checked.note}`);
    const { tool: _tool, ...rest } = step;
    return { ...rest, kind, ...(checked.tool ? { tool: checked.tool } : {}) };
  });
  return { steps, dropped, notes };
}

const groupLabel = (parts: readonly string[], elements: readonly Element[]): string =>
  groupName(parts.map(name => elements.find(e => e.name === name)?.guess ?? name));
