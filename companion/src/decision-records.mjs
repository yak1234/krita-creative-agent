// Typed Krita decisions for the decision-model dataset (openspec krita-decision-dataset).
// A decision is {decision_id, kind, state, questions, images, answers, answered_by}, in the
// Decisions API form (noul / choice / score), recorded as one small Langfuse trace each.
import { createHash } from 'node:crypto';

export const DECISION_KINDS = ['review-check', 'pass-keep', 'pass-failures', 'route', 'progress'];
const STATE_LIMIT = 1500;

// Stable ids: the same decision always maps to the same id, and so to the same trace id.
export function decisionId(chatId, kind, ...parts) {
  if (!DECISION_KINDS.includes(kind)) throw new Error('Unknown decision kind: ' + kind);
  return [chatId, kind, ...parts].map(String).join(':');
}

// Bounded text state: what a text-only model sees. Longest fields shrink first.
export function boundedState(state, limit = STATE_LIMIT) {
  const copy = structuredClone(state);
  const fit = () => JSON.stringify(copy).length <= limit;
  for (const key of ['recent_operations', 'user_directions']) while (!fit() && copy[key]?.length) copy[key].shift();
  for (const key of ['objective', 'plan_step', 'statement'])
    if (!fit() && typeof copy[key] === 'string') copy[key] = copy[key].slice(0, Math.max(80, copy[key].length - (JSON.stringify(copy).length - limit))) + '…';
  return copy;
}

export const CHECK_MET_QUESTION = {
  type: 'noul',
  instructions: 'Looking at the canvas, is this statement about the painting true?',
  criteria: { true: 'The canvas visibly fulfils the statement.', false: 'The canvas does not fulfil the statement, or only partly.' },
};

// One review check as a decision. The reviewer's evidence is its answer's reason,
// never part of the state: in text-only training it would leak the label.
export function reviewCheckDecision({ chatId, reviewIndex, review, check, statement, objective, imageDataUrl, canvas }) {
  return {
    decision_id: decisionId(chatId, 'review-check', reviewIndex, check.id),
    kind: 'review-check',
    state: boundedState({ statement, objective, canvas: canvas ?? null, plan_revision: review.revision ?? null, pass_count: review.pass_count ?? null }),
    questions: { met: CHECK_MET_QUESTION },
    images: imageDataUrl ? [imageDataUrl] : [],
    answers: { met: { type: 'noul', noul: check.met ? 1 : 0, evidence: check.evidence ?? '' } },
    answered_by: 'reviewer',
    recorded_at: review.at ?? null,
  };
}

export const HARD_GRAPHIC_QUESTION = {
  type: 'noul',
  instructions: 'Does AFTER replace painted, blended transitions with a hard, flat, poster-like or vector-like look that is not present in BEFORE?',
  criteria: { true: 'AFTER newly looks graphic: hard flat shapes, cut-out edges, ribbon-like strokes.', false: 'No new graphic flatness; transitions stay painted.' },
};

// Luna's hard-graphic judgement on one pass as a single-question decision.
export function hardGraphicDecision({ chatId, observationId, probability, images, at }) {
  return {
    decision_id: decisionId(chatId, 'pass-failures', observationId, 'hard_graphic'),
    kind: 'pass-failures',
    state: boundedState({ statement: 'This paint pass newly made the canvas look hard, flat or poster-like.', image_order: ['BEFORE the pass', 'AFTER the pass'] }),
    questions: { hard_graphic: HARD_GRAPHIC_QUESTION },
    images,
    answers: { hard_graphic: { type: 'noul', noul: probability } },
    answered_by: 'luna',
    recorded_at: at ?? null,
  };
}

// Deterministic sampling key, so the same seed picks the same rows.
export const sampleKey = (seed, id) => createHash('sha256').update(seed + '\0' + id).digest('hex');
