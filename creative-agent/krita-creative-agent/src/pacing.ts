// Run pacing by a decision model (Luna today; an Unsloth decision model later, behind
// the same Decisions API). After each painting call the host sends ONE request about the
// canvas: is each visible check of the current and next plan steps true, does the whole
// painting look finished, and (when the call painted) did it introduce a known artifact.
// Decisions bill input only, so several yes/no questions on one image cost about one.
// Yes/no checks about visible things replaced a vague "is this step established?" choice:
// in a traced run Luna answered that "keep going" 34 times in a row (next step never above
// 0.36) because the step asked for guide lines the painter never drew.
import { QUESTIONS, artifactQuestions, artifactAnswers, artifactFindings, type Finding } from './visual-checks.ts';
import type { Answer, DecisionResult, FallbackReason, NoulQuestion, Questions } from './decisions/types.ts';

/** A plan step as the brief stores it (the fields pacing reads). */
export type PlanStep = { title?: string; done_when?: string; checks?: string[] };
export type Brief = { steps?: PlanStep[]; requirements?: string[]; completion?: string[] };
/** One visible check of a step and the probability Luna gave it. */
export type StepCheck = { text: string; p: number };
/** A parsed pacing decision: check probabilities by step index, the finished probability, and the artifact answers. */
export type PaceDecision = { checks: Record<number, StepCheck[]>; finished: number;
  mistakes: { probabilities: Record<string, number>; established: number } | null; fallback?: undefined };
export type PaceFallback = { fallback: FallbackReason | 'no_decision'; checks?: undefined; finished?: undefined; mistakes?: undefined };
export type PaceAction =
  | { action: 'none'; reason: string }
  | { action: 'request_review'; progress: number | null; reason: 'finished' | 'last_step_met' }
  | { action: 'continue'; progress: number | null; unmet: string[]; reason?: 'transfer_only' }
  | { action: 'next_step'; step: number; progress: number | null };
/** One pacing decision as the goal's pace history keeps it. */
export type PaceHistoryEntry = { step: number; progress?: number | null; method?: string | null };
/** A painting call as the host records it: a batch carries its actions. */
export type PaintingCall = { tool?: string; args?: Record<string, any> } | null | undefined;
/** The plan revision's record of which steps had authored (not transferred) painting. */
export type StepWork = { revision: unknown; transfer: boolean; authored: number[] };

export const CHECK_MET = 0.6;          // a check counts as visible from this probability
export const FINISHED_MET = 0.7;       // the whole painting plausibly done: call the reviewer
export const MISTAKE_MET = QUESTIONS.pass.threshold;
export const LOOKAHEAD = 2;            // later steps also checked, so steps the canvas already shows are skipped
export const MIN_ACTIONS_BEFORE_REVIEW = 3;
const MAX_CHECKS = 5;

// A step's checks; older plans without them use their done_when as one check.
export const stepChecks = (step: PlanStep | undefined): string[] => (step?.checks?.length ? step.checks : [step?.done_when || step?.title]).filter((check): check is string => Boolean(check)).slice(0, MAX_CHECKS);
const checkedSteps = (steps: PlanStep[], currentStep: number) => steps.map((step, index) => index).filter(i => i >= currentStep && i <= currentStep + LOOKAHEAD);
const yesNo = (instructions: string, yes: string, no: string): NoulQuestion => ({ type: 'noul', instructions, criteria: { true: yes, false: no } });

/** Questions for one pacing request. mistakes: also ask whether the call introduced a known artifact (needs BEFORE and AFTER parts);
 *  reference: the call painted stitched reference chunks; closeUp: a CLOSE-UP of actual canvas pixels is attached. */
export function paceQuestions({ steps, currentStep, mistakes = false, reference = false, closeUp = false }:
  { steps: PlanStep[]; currentStep: number; mistakes?: boolean; reference?: boolean; closeUp?: boolean }): Questions {
  const questions: Questions = {};
  const where = closeUp ? ' Judge surface, texture, edges and any dot or grid pattern on the CLOSE-UP (actual pixels); the CURRENT CANVAS is shrunk.' : '';
  for (const s of checkedSteps(steps, currentStep))
    stepChecks(steps[s]).forEach((text, i) => { questions[`s${s}_c${i}`] = yesNo(`Is this visibly true on the CURRENT CANVAS? ${text}${where}`,
      'Clearly visible on the canvas now.', 'Missing, unclear or contradicted by the canvas.'); });
  questions.finished = yesNo('Does the CURRENT CANVAS plausibly meet every item of FINISHED WHEN?',
    'Every listed item is visibly met.', 'At least one listed item is missing or wrong.');
  if (mistakes) Object.assign(questions, artifactQuestions({ reference, prefix: 'mistake_' }));
  return questions;
}

export function paceState({ brief, currentStep, actionsSinceReview, lastReview }:
  { brief: Brief | null | undefined; currentStep: number; actionsSinceReview: number; lastReview?: { met: number; total: number; unmet: string[] } | null | false }): string[] {
  const steps = brief?.steps ?? [];
  return [
    'PLAN (painted in this order): ' + steps.map((s, i) => `${i + 1}. ${s.title}${i === currentStep ? ' ← current' : ''}`).join(' | '),
    'FINISHED WHEN: ' + [...(brief?.requirements ?? []), ...(brief?.completion ?? [])].join(' | ').slice(0, 1200),
    `Painting actions since the last review: ${actionsSinceReview}.`,
    lastReview ? `Last review: ${lastReview.met}/${lastReview.total} checks met. Unmet: ${lastReview.unmet.join(' | ').slice(0, 600)}` : 'No review yet.',
  ];
}

const probability = (answer: Answer | undefined): number | null => answer?.type === 'noul' && Number.isFinite(answer.noul) && answer.noul >= 0 && answer.noul <= 1 ? answer.noul : null;

/** {checks: {step: [{text, p}]}, finished, mistakes: {probabilities: {id: p}, established}} or {fallback}. */
export function parsePace(result: DecisionResult | null | undefined, { steps, currentStep, mistakes = false, reference = false }:
  { steps: PlanStep[]; currentStep: number; mistakes?: boolean; reference?: boolean }): PaceDecision | PaceFallback {
  if (result?.fallback) return { fallback: result.fallback };
  const answers = result?.answers ?? {}, checks: Record<number, StepCheck[]> = {};
  for (const s of checkedSteps(steps, currentStep)) {
    const parsed = stepChecks(steps[s]).map((text, i) => ({ text, p: probability(answers[`s${s}_c${i}`]) }));
    checks[s] = parsed as StepCheck[];   // every p is a number once the next line has passed
    if (parsed.some(c => c.p === null)) return { fallback: 'service_or_response_error' };
  }
  const finished = probability(answers.finished);
  if (finished === null) return { fallback: 'service_or_response_error' };
  // A malformed artifact answer drops the artifact check, not the pacing.
  return { checks, finished, mistakes: mistakes ? artifactAnswers(answers, { reference, prefix: 'mistake_' }) : null };
}

const met = (checks: StepCheck[] | undefined) => checks?.length && checks.every(c => c.p >= CHECK_MET);
/** Step progress on the 0-3 scale the plateau and stall rules use: mean check probability. */
export const stepProgress = (checks: StepCheck[] | undefined): number | null => checks?.length ? 3 * checks.reduce((sum, c) => sum + c.p, 0) / checks.length : null;

// The host's action for a decision. The current step is the first one whose checks are not
// all visible, so a canvas that already shows a step (an existing painting) skips it.
// handPainted(step): false when the step's checks may only be met by a reference transfer (see stepWork).
export function paceAction(answer: PaceDecision | PaceFallback | null | undefined, { currentStep, stepCount, actionsSinceReview, unchangedSinceReview, handPainted = () => true }:
  { currentStep: number; stepCount: number; actionsSinceReview: number; unchangedSinceReview?: boolean; handPainted?: (step: number) => boolean }): PaceAction {
  if (!answer || answer.fallback) return { action: 'none', reason: answer?.fallback ?? 'no_decision' };
  const progress = stepProgress(answer.checks[currentStep]);
  const reviewable = actionsSinceReview >= MIN_ACTIONS_BEFORE_REVIEW && !unchangedSinceReview;
  if (answer.finished >= FINISHED_MET && reviewable) return { action: 'request_review', progress, reason: 'finished' };
  if (met(answer.checks[currentStep])) {
    if (!handPainted(currentStep)) return { action: 'continue', progress, unmet: [], reason: 'transfer_only' };
    let next = currentStep + 1;
    while (next < stepCount && met(answer.checks[next]) && handPainted(next)) next++;
    if (next < stepCount) return { action: 'next_step', step: next, progress };
    if (reviewable) return { action: 'request_review', progress, reason: 'last_step_met' };
  }
  return { action: 'continue', progress, unmet: (answer.checks[currentStep] ?? []).filter(c => c.p < CHECK_MET).map(c => c.text) };
}

/** Artifacts the call probably introduced, with labels; severe ones are sure damage to an established painting. */
export const foundMistakes = (answer: PaceDecision | PaceFallback | null | undefined): Finding[] => answer?.mistakes ? artifactFindings(answer.mistakes, MISTAKE_MET).map(f => ({ ...f, probability: Math.round(f.probability * 100) / 100 })) : [];

// Two low-progress decisions in a row on the same step: tell the painter to change method.
export function stalled(history: PaceHistoryEntry[], step: number): boolean {
  const recent = history.filter(h => h.step === step).slice(-2);
  return recent.length === 2 && recent.every(h => Number.isFinite(h.progress) && h.progress! < 1);
}

// Luna's "keep going" with a score that has stopped rising means more painting is not finishing
// this step (a run spent 2 hours and 33 decisions on step 1 at 1.3-1.9 of 3). Returns 'plateau'
// when the best of the last PLATEAU_WINDOW scores is no better than before them, 'cap' after
// STEP_DECISION_CAP decisions on one step whatever the scores, 'stall' after STALL_LIMIT low
// scores in a row whose latest is not a clear gain (the "change method" note has had its chance),
// otherwise null. Pacing runs once per painting call and a reference job takes 15-30 minutes, so a
// traced finishing run spent 9 hours and 3 decisions on step 1 at 0.3-0.8 of 3 repainting one rectangle.
export const PLATEAU_WINDOW = 4, PLATEAU_GAIN = 0.15, STEP_DECISION_CAP = 12, STALL_LIMIT = 3;
export function levelledOff(history: PaceHistoryEntry[], step: number): 'cap' | 'stall' | 'plateau' | null {
  const onStep = history.filter(h => h.step === step);
  if (onStep.length >= STEP_DECISION_CAP) return 'cap';
  const scores = onStep.map(h => h.progress).filter((p): p is number => Number.isFinite(p));
  const low = scores.slice(-STALL_LIMIT);
  if (low.length === STALL_LIMIT && low.every(p => p < 1) && low.at(-1)! < Math.max(...low.slice(0, -1)) + PLATEAU_GAIN) return 'stall';
  if (scores.length < PLATEAU_WINDOW * 2) return null;
  const recent = scores.slice(-PLATEAU_WINDOW), before = scores.slice(0, -PLATEAU_WINDOW);
  if (Math.min(...recent) < 1) return null;
  return Math.max(...recent) < Math.max(...before) + PLATEAU_GAIN ? 'plateau' : null;
}

// A reference transfer stamps the whole reference as small dabs, so Luna sees every step's checks
// met at once: a traced run jumped from step 1 to step 5 and never drew the car, hands or mirror
// those steps asked for. After a transfer, a later step counts only once it has authored painting.
export const TRANSFER_TOOLS = ['paint_from_reference', 'continue_reference_painting'];
const NOT_AUTHORED = [...TRANSFER_TOOLS, 'apply_filter', 'adjust_layer', 'set_layer'];
type CallAction = { tool: string | undefined; args: Record<string, any> };
/** `list.includes(tool)` for a tool name that may be missing (no list holds undefined). */
const listed = (list: string[], tool: string | undefined) => list.includes(tool as string);
const actionsOf = (call: PaintingCall): CallAction[] => call?.tool === 'paint_batch' ? (call.args?.actions ?? []).map((a: { tool?: string; arguments?: Record<string, any> }) => ({ tool: a.tool, args: a.arguments ?? {} })) : [{ tool: call?.tool, args: call?.args ?? {} }];

/** The plan revision's work record after this call: {revision, transfer, authored: [steps]}. */
export function stepWork(work: StepWork | null | undefined, call: PaintingCall, { revision, step }: { revision: unknown; step: number }): StepWork {
  const next: StepWork = work && work.revision === revision ? { ...work, authored: [...work.authored] } : { revision, transfer: false, authored: [] };
  const actions = actionsOf(call);
  if (actions.some(a => listed(TRANSFER_TOOLS, a.tool))) next.transfer = true;
  if (actions.some(a => a.tool && !NOT_AUTHORED.includes(a.tool)) && !next.authored.includes(step)) next.authored.push(step);
  return next;
}
/** handPainted for paceAction: the first step (big shapes) may come from a transfer; later ones need authored work. */
export const handPaintedBy = (work: StepWork | null | undefined) => (step: number): boolean => !work?.transfer || step === 0 || work.authored.includes(step);

// The same method again and again without the step's checks rising: a traced run made five
// reference transfers and ten blur or noise-reducer masks to hide the dabs those transfers left.
// Authored stroke work is never refused this way; only methods that work on the whole picture are.
const SMOOTHING = /blur|noise ?reducer|smooth|denoise|median/i;
// The reference tools are one method: each repaints the target from the same source crop, and a
// traced painter told to change method switched from a transfer to a surface pass on the same rectangle.
const REFERENCE_TOOLS = [...TRANSFER_TOOLS, 'paint_reference_edges', 'paint_reference_surface'];
function methodOf({ tool, args }: CallAction): string | null {
  if (listed(REFERENCE_TOOLS, tool)) return 'reference painting';
  if (tool === 'apply_filter') return SMOOTHING.test(args.filter ?? '') ? 'smoothing filter' : 'filter ' + String(args.filter ?? '');
  if (tool === 'paint_recipe') return 'stroke recipe';
  return null;
}
/** The call's method for the no-progress rule, or null for authored or mixed work. */
export function callMethod(call: PaintingCall): string | null {
  const methods = new Set(actionsOf(call).filter(a => !listed(['adjust_layer', 'set_layer'], a.tool)).map(methodOf));
  return methods.size === 1 ? [...methods][0] : null;
}
export const METHOD_TRIES = 2;
/** Methods whose last METHOD_TRIES calls on this step each failed to raise its best progress by PLATEAU_GAIN. */
export function exhaustedMethods(history: PaceHistoryEntry[], step: number): string[] {
  const failed: Record<string, number> = {}; let best: number | null = null;
  for (const h of history.filter(h => h.step === step)) {
    if (!Number.isFinite(h.progress)) continue;
    const progress = h.progress as number;   // finite, from the line above
    if (h.method && best !== null) failed[h.method] = progress < best + PLATEAU_GAIN ? (failed[h.method] ?? 0) + 1 : 0;
    best = best === null ? progress : Math.max(best, progress);
  }
  return Object.keys(failed).filter(m => failed[m] >= METHOD_TRIES);
}

// The whole-canvas view of a 6000 px painting is shrunk about 4x, which hides the dab texture a
// finishing step must remove: a traced check "no dot or grid pattern remains" could not be judged.
// Pacing also sends one actual-pixel crop of where the call painted, at most CLOSE_UP_SIDE a side.
export const CLOSE_UP_SIDE = 1568, CLOSE_UP_MIN = 768;
export type Region = [number, number, number, number];
/** The [x,y,w,h] canvas window for that close-up: centred on the union of the painted areas, or null
 *  when nothing says where the call painted or the whole view already shows actual pixels. */
export function closeUpRegion(areas: unknown[] | null | undefined, { width, height }: { width: number; height: number }): Region | null {
  const valid = (areas ?? []).filter((a): a is Region => Array.isArray(a) && a.length === 4 && a.every(Number.isFinite) && a[2] > 0 && a[3] > 0);
  if (!valid.length || !(width > 0 && height > 0) || Math.max(width, height) <= CLOSE_UP_SIDE) return null;
  const x0 = Math.min(...valid.map(a => a[0])), y0 = Math.min(...valid.map(a => a[1]));
  const x1 = Math.max(...valid.map(a => a[0] + a[2])), y1 = Math.max(...valid.map(a => a[1] + a[3]));
  const size = (span: number, total: number) => Math.min(total, CLOSE_UP_SIDE, Math.max(CLOSE_UP_MIN, Math.ceil(span)));
  const w = size(x1 - x0, width), h = size(y1 - y0, height);
  const place = (centre: number, span: number, total: number) => Math.max(0, Math.min(total - span, Math.round(centre - span / 2)));
  return [place((x0 + x1) / 2, w, width), place((y0 + y1) / 2, h, height), w, h];
}
