// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// When Toska builds a new effect (openspec custom-effects): decided in code, never by the model. The same effect failing
// policy.failures_before_build times (2) in a chat starts a build. A failure is:
// - a token effort, from the move's own counts (tokenEffort; nothing is sent anywhere): an effect painted by hand with
//   fewer than policy.token_effort strokes and no fill, or an effect tool whose report painted nothing;
// - Luna's "effect met" decision (effectMet) saying no after an Agent move whose request names an effect: one yes/no
//   question with the request and the canvas before and after the move. Luna failing (null) is never a failure;
// - a redo: the artist asks again, in a new message, for the effect the painter's previous move named and finished. An
//   Undo alone never counts (the studio passes only typed messages).
// Failures are kept per place (`at`, the move): a move judged met and then asked again counts once, as a failure. A
// build consumes the failures that started it, so another needs failures_before_build new ones. Never built: an effect a
// library effect's cue covers (the painter has paint_effect for it), one discarded in this chat (only /new-effect builds
// it again), and any effect while another builds (one build at a time). The studio keeps one EffectFailures per chat in
// memory and starts the build without waiting for it (studio.mjs).
// Which effect a request names: by words (effectAsked: the built-in words and the library's names and cue phrases), or,
// with Decision checks on, by one Luna choice (classifyEffect) that falls back to the words. This module imports no .mjs.
import type { ChoiceQuestion, DecisionImage, DecisionMaker } from '../decisions/types.ts';
import type { Policy } from './policy.ts';
import { samePart } from '../snow-tool.ts';

/** The atmospheric, weather, light and particle effects a request can name, each with its words (whole words or phrases,
 * any case). Words that mostly name objects in everyday requests (petals, stars, dust, bubbles) are left out, or kept only
 * in a phrase that is the effect ("falling petals", "starry sky", "dust motes"). */
export const EFFECT_WORDS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  fog: ['fog', 'foggy', 'mist', 'misty', 'haze', 'hazy'],
  snow: ['snow', 'snowy', 'snowing', 'snowfall', 'snowflake', 'snowflakes', 'snowstorm', 'blizzard', 'flurries', 'falling snow'],
  rain: ['rain', 'rainy', 'raining', 'raindrops', 'rainfall', 'rainstorm', 'drizzle', 'downpour'],
  smoke: ['smoke', 'smoky'],
  steam: ['steam', 'steamy'],
  fire: ['fire', 'flames', 'blaze'],
  sparks: ['sparks', 'embers'],
  'light rays': ['god rays', 'light rays', 'sun rays', 'sunrays', 'sunbeams', 'sunbeam', 'light shafts', 'shafts of light', 'crepuscular rays', 'rays of light'],
  'dust motes': ['dust motes', 'floating dust'],
  lightning: ['lightning'],
  bokeh: ['bokeh'],
  'lens flare': ['lens flare', 'lens flares'],
  fireflies: ['fireflies'],
  'falling petals': ['falling petals', 'drifting petals', 'falling leaves'],
  'starry sky': ['starry sky', 'starfield'],
  aurora: ['aurora', 'northern lights'],
});

/** An effect word followed by one of these names a thing, not the effect: "fire station", "rain boots", "snow globe". */
const OBJECT_AFTER = new Set(['station', 'stations', 'truck', 'trucks', 'engine', 'engines', 'escape', 'hydrant', 'place', 'fighter', 'fighters',
  'alarm', 'door', 'exit', 'extinguisher', 'boot', 'boots', 'coat', 'coats', 'jacket', 'gear', 'gutter', 'barrel', 'globe', 'shovel', 'plough',
  'plow', 'detector', 'train', 'lamp', 'lamps', 'lights', 'pit', 'wood', 'man', 'men', 'drop', 'bottle', 'cone', 'machine', 'brick', 'bricks']);

type Term = { name: string; pattern: RegExp };
type LibraryLike = Iterable<{ name: string; cue: string }>;

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const termOf = (name: string, words: readonly string[]): Term => ({ name, pattern: new RegExp(
  `(?<![\\p{L}\\p{N}])(?:${[...words].sort((a, b) => b.length - a.length).map(w => escape(w).replace(/[ -]+/g, '[\\s-]+')).join('|')})(?![\\p{L}\\p{N}])`, 'giu') });
const BUILT_IN: Term[] = Object.entries(EFFECT_WORDS).map(([name, words]) => termOf(name, words));
const LEADING = /^(?:(?:a|an|the|some)\s+)+/i;

/** A library effect's words: its name (hyphens as spaces) and each phrase of its cue of at most three words. */
function libraryTerms(library: LibraryLike | undefined): Term[] {
  const out: Term[] = [];
  for (const recipe of library ?? []) {
    const phrases = String(recipe.cue ?? '').split(/[,;]|\bor\b|\band\b/i).map(p => p.trim().replace(LEADING, '').trim())
      .filter(p => p && p.split(/\s+/).length <= 3 && /\p{L}/u.test(p));
    out.push(termOf(recipe.name, [recipe.name.replace(/-/g, ' '), ...phrases]));
  }
  return out;
}

/** Every effect a text names, in the order it names them; the library's effects (their names and cue phrases) first. */
export function effectsNamed(text: string, library?: LibraryLike): string[] {
  const said = String(text ?? '');
  const found: { name: string; at: number }[] = [];
  for (const [rank, term] of [...libraryTerms(library), ...BUILT_IN].entries()) {
    for (const match of said.matchAll(term.pattern)) {
      const next = said.slice(match.index! + match[0].length).match(/^[\s-]+(\p{L}+)/u)?.[1]?.toLowerCase();
      if (next && OBJECT_AFTER.has(next)) continue;
      found.push({ name: term.name, at: match.index! * 1000 + rank });
      break;
    }
  }
  return [...new Set(found.sort((a, b) => a.at - b.at).map(f => f.name))];
}

/** The effect a request names, by its words (the first when it names several); null when it names none. */
export function effectAsked(text: string, library?: LibraryLike): string | null {
  return effectsNamed(text, library)[0] ?? null;
}

/** Whether two effect names are one effect: the same effect by its words ("mist" and "fog"), else a shared word
 * ("aurora" and "aurora borealis"). */
export function sameEffect(a: string, b: string): boolean {
  const x = String(a ?? '').trim(), y = String(b ?? '').trim();
  if (!x || !y) return false;
  const nx = effectAsked(x), ny = effectAsked(y);
  if (nx && ny) return nx === ny;
  return x.toLowerCase() === y.toLowerCase() || samePart(x, y);
}

/** The library effect that covers `effect` (its name, or an effect its cue names), or null: such an effect is used, never built. */
export function libraryEffectFor(effect: string, library: LibraryLike): string | null {
  for (const recipe of library)
    if (sameEffect(effect, recipe.name) || effectsNamed(recipe.cue).some(named => sameEffect(effect, named))) return recipe.name;
  return null;
}

export type PreviousMove = { number: number; finished?: boolean; effect?: string | null; summary?: string; title?: string };
/** A redo: the artist's new typed message asks for `effect`, the effect the previous move named (its request's, else its
 * summary's) and finished (finish_move). The failure is that move's ({effect, at}); null for anything else. Keep, retry
 * (an Undo), continue and plan-step moves are not typed, so an Undo alone never counts. */
export function redoOf(effect: string | null, previous: PreviousMove | null | undefined, typed: boolean): { effect: string; at: string } | null {
  if (!typed || !effect || !previous?.finished) return null;
  const named = previous.effect ?? effectAsked(previous.summary ?? previous.title ?? '');
  return named && sameEffect(named, effect) ? { effect: named, at: `move-${previous.number}` } : null;
}

/** What a move painted, as the studio counts it (afterPainting): strokes, actions without strokes (fills, transfers),
 * effect-tool calls (paint_snow, paint_effect) and what their reports painted (flakes and caps, pixels). */
export type MoveCounts = { strokes?: number; unstroked?: number; effect_calls?: number; effect_painted?: number };
/** A token effort, from the move's own counts: an effect tool whose reports painted nothing, or, without one, fewer than
 * policy.token_effort strokes and no fill. policy.token_effort 0 turns it off. */
export function tokenEffort(counts: MoveCounts, policy: Pick<Policy, 'token_effort'>): boolean {
  if (!(policy.token_effort > 0)) return false;
  if ((counts.effect_calls ?? 0) > 0) return !((counts.effect_painted ?? 0) > 0);
  return !((counts.unstroked ?? 0) > 0) && (counts.strokes ?? 0) < policy.token_effort;
}

/** One chat's effect failures (kept in memory by the studio for the chat). */
export class EffectFailures {
  /** The effect being built now, or null: one build at a time. The studio sets and clears it. */
  building: string | null = null;
  private log = new Map<string, Map<string, boolean>>();
  private consumed = new Map<string, Set<string>>();
  private gaveUp: string[] = [];

  private keyOf(effect: string): string {
    for (const key of this.log.keys()) if (sameEffect(key, effect)) return key;
    return effect;
  }

  /** A judgement of `effect` at `at` (the move): failed or met. A later judgement at the same place replaces it. */
  record(effect: string, failed: boolean, at: string): void {
    const key = this.keyOf(effect);
    const entries = this.log.get(key) ?? new Map<string, boolean>();
    entries.set(at, failed);
    this.log.set(key, entries);
  }

  /** How many places `effect` failed in this chat since its last build. */
  failures(effect: string): number {
    const key = this.keyOf(effect), used = this.consumed.get(key);
    return [...(this.log.get(key)?.entries() ?? [])].filter(([at, failed]) => failed && !used?.has(at)).length;
  }

  /** Whether a build of `effect` starts now: it failed often enough, it was not discarded, and nothing is building. */
  due(effect: string, policy: Pick<Policy, 'failures_before_build'>): boolean {
    return this.building === null && !this.isDiscarded(effect) && this.failures(effect) >= policy.failures_before_build;
  }

  /** A build of `effect` starts: it is building, and its failures so far are used up. */
  launched(effect: string): void {
    this.building = effect;
    const key = this.keyOf(effect), used = this.consumed.get(key) ?? new Set<string>();
    for (const [at, failed] of this.log.get(key) ?? []) if (failed) used.add(at);
    this.consumed.set(key, used);
  }

  /** The artist discarded a build of `effect`: it is not built again in this chat (only /new-effect builds it). */
  discarded(effect: string): void {
    if (!this.isDiscarded(effect)) this.gaveUp.push(effect);
  }

  isDiscarded(effect: string): boolean {
    return this.gaveUp.some(e => sameEffect(e, effect));
  }
}

/** Above this probability of yes, the effect was met; a classification counts from this confidence. */
export const MET = 0.5;

/** Luna's "effect met" decision: one yes/no question with the request and the canvas before and after the move. True when
 * met, false when not (or only a token effort), null when Luna could not answer (never a failure). Never throws. */
export async function effectMet({ client, request, before, after, signal }: { client: DecisionMaker | null; request: string;
  before: DecisionImage | null; after: DecisionImage | null; signal?: AbortSignal }): Promise<boolean | null> {
  if (!client || !before || !after) return null;
  let result;
  try {
    result = await client.decide({ purpose: 'effect-met', ...(signal ? { signal } : {}),
      parts: [`REQUEST (the artist's words, quoted): ${JSON.stringify(String(request).slice(0, 500))}`,
        'BEFORE (the canvas before this painting move):', before, 'AFTER (the canvas after it):', after],
      questions: { met: { type: 'noul',
        instructions: 'The REQUEST asks for a visual effect (such as fog, snow, rain, smoke or light rays). Comparing BEFORE and AFTER, '
          + 'does AFTER show that effect as the request asks for it, clearly visible over the picture, and not just a token effort '
          + '(a few marks, a faint patch, or something that reads as a different effect)?',
        criteria: { true: 'The effect is clearly painted as asked.', false: 'The effect is missing, a token effort, or reads as something else.' } } } });
  } catch {
    return null;
  }
  if (!result || 'fallback' in result && result.fallback) return null;
  const answer = 'answers' in result ? result.answers.met : undefined;
  if (answer?.type !== 'noul' || !Number.isFinite(answer.noul) || answer.noul < 0 || answer.noul > 1) return null;
  return answer.noul >= MET;
}

/** Luna's reading of which effect a request asks for: one choice over the built-in effects and the library's, or none.
 * {effect} (null: it asks for no effect), or null when Luna could not answer or was unsure (the caller falls back to the
 * words, effectAsked). The decision types have no free text, so an effect outside the list reads as none. Never throws. */
export async function classifyEffect({ client, text, library, signal }: { client: DecisionMaker | null; text: string;
  library?: LibraryLike; signal?: AbortSignal }): Promise<{ effect: string | null } | null> {
  if (!client || !String(text ?? '').trim()) return null;
  const names = [...new Set([...[...(library ?? [])].map(r => r.name), ...Object.keys(EFFECT_WORDS)])].slice(0, 40);
  const question: ChoiceQuestion = { type: 'choice',
    instructions: 'The message is an artist’s request to a painter, in any language. Does it ask to paint an atmospheric, weather, light or particle '
      + 'effect over the picture (fog, snow, rain, smoke, light rays and the like)? Pick that effect, or none when it asks for objects, colours, '
      + 'forms or anything else (rose petals, a fire station, stars on a flag and rain boots are objects, not effects).',
    criteria: { none: 'It asks for no such effect.', ...Object.fromEntries(names.map((n, i) => [`effect_${i + 1}`, `The effect: ${n}.`])) } };
  let result;
  try {
    result = await client.decide({ purpose: 'effect-asked', ...(signal ? { signal } : {}),
      parts: [`MESSAGE (quoted): ${JSON.stringify(String(text).slice(0, 500))}`], questions: { effect: question } });
  } catch {
    return null;
  }
  if (!result || 'fallback' in result && result.fallback) return null;
  const answer = 'answers' in result ? result.answers.effect : undefined;
  if (answer?.type !== 'choice' || !(answer.choice in question.criteria)) return null;
  const confidence = Number(answer.confidence ?? answer.probabilities?.[answer.choice] ?? 1);
  if (!(confidence >= MET)) return null;
  if (answer.choice === 'none') return { effect: null };
  return { effect: names[Number(answer.choice.slice('effect_'.length)) - 1] ?? null };
}
