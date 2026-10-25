// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Reading the artist's messages (openspec luna-goal-reviewer goal 2, approved by the artist 2026-10-23). Element names in
// typed messages were matched by keywords, which added and painted elements on "don't paint the sky" or "the light is too
// harsh" until a negation patch, and never understood "les tours du Kremlin". Now one Luna decision on each typed Agent
// message (text only, any language) answers: which folder element it asks to work on (if the folder names elements), does
// it ask for one part of the picture, does it say not to work on something, is it a change from the reference or a return
// to it, does it ask for hand painting? messagePolicy turns the answers into what the host does: adding or targeting an
// element step, asking the painter to ask for a Paint only here area, a departure, the typed-stroke exemption.
//
// The rules (the proposal's): Luna acts only with Decision checks on Guide and only when it is sure (SURE); when Luna is
// off, failed or unsure the host does nothing irreversible: no step is added (the keyword rules may target a step already
// in the plan, and ask the artist before adding one), and an unsure reference answer leaves the move measured only, never
// undone (goal-likeness.ts). The keyword rules (project-folder.ts elementsNamed, goal-likeness.ts departureRequested,
// typed-strokes.ts handPaintingRequested) stay as the offline fallback. On Evaluate the reference answer still counts, as
// the departure check always has (a departure only makes the host undo less); everything else is the keywords'.
// Mechanism only: the studio asks and applies (studio.mjs); this module imports no .mjs.
import { basename } from 'node:path';
import type { DecisionMaker, Questions, FallbackReason } from './decisions/types.ts';
import { elementsNamed } from './project-folder.ts';

/** An answer counts from this probability (a noul) or confidence (a choice); a noul at or under 1 - SURE is a sure no. */
export const SURE = 0.7;
export type Element = { name: string; guess: string };
export type ReferenceAnswer = 'change' | 'return' | 'neither';
/** A folder plan's stages (plan-from-request goal 1), in their painting order. */
export type PlanStage = 'underpainting' | 'finish' | 'refine' | 'accents';
export const PLAN_STAGES: readonly PlanStage[] = ['underpainting', 'finish', 'refine', 'accents'];
export type ScopeAnswer = 'whole' | 'stages' | 'neither';
/** The stages a message asks for, while a folder plan is being made: the whole painting, only some stages, or neither,
 * and each stage's probability of being asked for (null: no usable answer). */
export type StageReading = { scope: { choice: ScopeAnswer; confidence: number } | null; asked: Record<PlanStage, number | null> };
/** Plan or not (single-image-plans goal 1): does the message ask for one thing or several steps in order? */
export type PlanAnswer = 'one' | 'several';
export type Reading = {
  /** The element the message asks to work on now (name null: none), or null when no element was asked about or answered. */
  element: { name: string | null; confidence: number } | null;
  one_part: number | null; negation: number | null; hand_painting: number | null;
  reference: { choice: ReferenceAnswer; confidence: number } | null;
  /** Only when asked (`stages`: a folder plan is being made), else null. */
  stages: StageReading | null;
  /** Only when asked (`plan`: a single-image chat could plan this message), else null. */
  plan: { choice: PlanAnswer; confidence: number } | null;
  elapsed_ms: number; cost: number; input_tokens: number; fallback?: FallbackReason;
};
export type MessagePolicy = {
  source: 'luna' | 'keywords';
  target: string | null;        // the element step this message paints (added first when in `add`)
  add: string[];                // element steps added now: only Luna, sure, on Guide
  ask_add: string[];            // named by keywords but not in the plan: ask the artist before adding
  part: boolean;                // one part of the picture, no element: the painter asks for its area first
  departure: 'departure' | 'return' | 'neither' | null;   // null: the phrases decide (goal-likeness.ts)
  hand_painting: boolean | null;                           // null: the phrases decide (typed-strokes.ts)
};

const REFERENCE: Record<ReferenceAnswer, string> = {
  change: 'It asks for something that differs from or adds to the reference (another colour, light, mood, atmosphere, grade or style, an added or removed object, a changed shape).',
  return: 'It asks to go back to the reference or to match it more closely.',
  neither: 'It asks to paint, refine or finish what the reference shows, only says what not to paint or what to leave alone, or says nothing about the reference.',
};
const noul = (instructions: string, yes: string, no: string) => ({ type: 'noul' as const, instructions, criteria: { true: yes, false: no } });
// The plan's stages (plan-from-request goal 1, the artist 2026-10-24: "paint the underpainting" still queued Finish, Refine
// and Accents). Asked in the same single decision, only while a folder plan is being made.
const SCOPE: Record<ScopeAnswer, string> = {
  whole: 'It asks for the whole painting: to paint it all, like the goal image, the whole thing, every stage.',
  stages: 'It asks only for one or some stages of the painting (the underpainting, the finish, refining, the accents), not the whole painting.',
  neither: 'It names no stage and does not ask for the whole painting (a greeting, a question, a comment, one part of the picture).',
};
// Plan or not (single-image-plans goal 1, the artist 2026-10-25: "Should Luna decide if it's a thing request or multipart
// request" -> "Yes"). One more choice in the same single decision, asked only where a single-image plan could be made.
const PLAN_STEPS: Record<PlanAnswer, string> = {
  one: 'It asks for one thing: one change, one part, one addition or one stage of the painting (or it is a question or a comment).',
  several: 'It asks for several things to do one after another: two or more stages (the underpainting, the finish, refining to the goal, the accents), a stage and something to add, or several things to add.',
};
const STAGE_TEXT: Record<PlanStage, string> = {
  underpainting: 'the underpainting: the first lay-in of the whole picture\u2019s colours and light from the goal image (a block-in)',
  finish: 'the finish: the soft areas blended and the forms restroked over the whole picture',
  refine: 'refining: bringing the picture (or its parts) closer to the goal image, crisper and more detailed',
  accents: 'the accents: lights, glints, darks and fine lines',
};

/** Luna's reading of one typed message: one text decision. A fallback is no reading (every answer null). */
export async function readMessage({ client, text, elements, signal, stages = false, plan = false }: { client: DecisionMaker; text: string; elements: readonly Element[]; signal?: AbortSignal;
  /** A folder plan is being made: also ask which of its stages the message asks for. */
  stages?: boolean;
  /** A single-image chat could plan this message: also ask whether it asks for one thing or several steps. */
  plan?: boolean }): Promise<Reading> {
  const empty: Reading = { element: null, one_part: null, negation: null, hand_painting: null, reference: null, stages: null, plan: null, elapsed_ms: 0, cost: 0, input_tokens: 0 };
  const listed = elements.slice(0, 24);
  const questions: Questions = {
    ...(listed.length ? { element: { type: 'choice' as const,
      instructions: 'The message may be in any language. Which one of the listed parts of the picture does it ask the painter to work on now? '
        + 'Answer none when it is about the whole picture or its overall light, colour or mood, about a part not listed, or when it only says to leave a part alone or not to paint it.',
      criteria: { none: 'It asks to work on none of the listed parts now.',
        ...Object.fromEntries(listed.map((e, i) => [`element_${i + 1}`, `${e.guess} (the image ${basename(e.name)})`])) } } } : {}),
    one_part: noul('Does the message ask to work on one particular part or object of the picture (the sky, the towers, a face, the car), rather than the whole picture or its overall light, colour or mood?',
      'It asks to work on one part or object.', 'It is about the whole picture, its overall look, or no part at all.'),
    negation: noul('Does the message say not to work on something, or to leave something alone ("don’t", "leave ... alone", "not the ...", in any language)?',
      'It says not to work on something.', 'It says nothing like that.'),
    reference: { type: 'choice' as const, instructions: 'The painting is made from a goal reference image. What does the message ask, compared with that reference? Saying not to paint something, or to leave it alone, is no change from the reference.', criteria: { ...REFERENCE } },
    hand_painting: noul('Does the message ask for hand-painted work: visible or expressive brushstrokes, painting by hand or freehand?',
      'It asks for hand-painted work.', 'It does not ask for hand-painted work.'),
    ...(stages ? {
      plan_scope: { type: 'choice' as const, instructions: 'The painter is about to plan a painting in stages: the underpainting, the finish, refining toward the goal image, the accents. What does the message ask for?', criteria: { ...SCOPE } },
      ...Object.fromEntries(PLAN_STAGES.map(stage => [`stage_${stage}`, noul(`Does the message ask for ${STAGE_TEXT[stage]}? Saying not to do it, or to leave it for later, is no.`,
        'It asks for this stage.', 'It does not ask for this stage.')])),
    } : {}),
    ...(plan ? { plan_steps: { type: 'choice' as const, instructions: 'The painting is made from a goal image. Does the message ask the painter for one thing, or for several steps to do one after another?', criteria: { ...PLAN_STEPS } } } : {}),
  };
  let result;
  try {
    result = await client.decide({ signal, purpose: 'read-message', questions,
      parts: ['THE ARTIST’S MESSAGE to the painter, about a painting in progress:', String(text ?? '').slice(0, 2000)] });
  } catch { return { ...empty, fallback: 'service_or_response_error' }; }
  if (result.fallback) return { ...empty, elapsed_ms: result.elapsed_ms, fallback: result.fallback };
  const a = result.answers;
  const p = (answer: unknown): number | null => {
    const v = (answer as { type?: string; noul?: unknown } | undefined);
    return v?.type === 'noul' && typeof v.noul === 'number' && v.noul >= 0 && v.noul <= 1 ? v.noul : null;
  };
  const picked = (answer: unknown, keys: readonly string[]): { choice: string; confidence: number } | null => {
    const v = answer as { type?: string; choice?: unknown; confidence?: unknown; probabilities?: Record<string, unknown> } | undefined;
    if (v?.type !== 'choice' || typeof v.choice !== 'string' || !keys.includes(v.choice)) return null;
    const c = v.probabilities?.[v.choice] ?? v.confidence;
    return { choice: v.choice, confidence: typeof c === 'number' && Number.isFinite(c) ? Math.round(c * 100) / 100 : 0 };
  };
  const elementKeys = ['none', ...listed.map((_, i) => `element_${i + 1}`)];
  const element = listed.length ? picked(a.element, elementKeys) : null;
  const reference = picked(a.reference, Object.keys(REFERENCE));
  const scope = stages ? picked(a.plan_scope, Object.keys(SCOPE)) : null;
  const steps = plan ? picked(a.plan_steps, Object.keys(PLAN_STEPS)) : null;
  return { element: element ? { name: element.choice === 'none' ? null : listed[Number(element.choice.slice(8)) - 1]!.name, confidence: element.confidence } : null,
    one_part: p(a.one_part), negation: p(a.negation), hand_painting: p(a.hand_painting),
    reference: reference as Reading['reference'],
    stages: stages ? { scope: scope as StageReading['scope'], asked: Object.fromEntries(PLAN_STAGES.map(stage => [stage, p(a[`stage_${stage}`])])) as Record<PlanStage, number | null> } : null,
    plan: steps as Reading['plan'],
    elapsed_ms: result.elapsed_ms, cost: result.usage.cost, input_tokens: result.usage.input_tokens };
}

/** What the host does with a typed message. `act`: Luna acts (Decision checks on Guide); `planned`: the element files
 * that already have a step. With no usable reading (Luna off or failed) or Luna not acting, the keyword rules decide
 * what they safely can. */
export function messagePolicy({ reading, act, text, elements, planned }: { reading: Reading | null; act: boolean; text: string; elements: readonly Element[]; planned: readonly string[] }): MessagePolicy {
  const usable = reading && !reading.fallback ? reading : null;
  const sureYes = (v: number | null | undefined) => typeof v === 'number' && v >= SURE;
  const sureNo = (v: number | null | undefined) => typeof v === 'number' && v <= 1 - SURE;
  const departure = usable?.reference && usable.reference.confidence >= SURE
    ? ({ change: 'departure', return: 'return', neither: 'neither' } as const)[usable.reference.choice] : null;
  if (usable && act) {
    const element = usable.element, sureElement = element && element.confidence >= SURE ? element.name : null;
    const negated = sureYes(usable.negation);
    return { source: 'luna', target: sureElement, add: sureElement && !planned.includes(sureElement) ? [sureElement] : [], ask_add: [],
      part: !sureElement && !(element?.name) && sureYes(usable.one_part) && !negated,
      departure, hand_painting: sureYes(usable.hand_painting) ? true : sureNo(usable.hand_painting) ? false : null };
  }
  const named = elementsNamed(text, elements);
  const target = named.find(name => planned.includes(name)) ?? null;
  return { source: 'keywords', target, add: [], ask_add: named.filter(name => !planned.includes(name)), part: false, departure, hand_painting: null };
}
