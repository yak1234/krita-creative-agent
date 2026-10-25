// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Auto-approve (openspec auto-approve; the artist, 2026-10-25: "in general an auto approve mode, it's standard in agentic
// systems"). The panel holds the countdown: each card that waits for the artist takes its default answer after the
// Auto-approve delay (settings-schema.mjs) unless the artist acts first, and sends the same command its button sends.
// This module is the companion's part: the delays, the card kinds that may be answered, the record of each auto-answer
// for the diagnostics, and the recommended option a choice card carries (`recommended`). Mechanism only: which card
// recommends what is decided where the card is made (STAGE_CARD, CLOSEUP_ANSWERS, ask_question).

/** The delays the setting offers, in seconds (0: Immediately); 'off' is the default. */
export const AUTO_APPROVE_DELAYS = Object.freeze([0, 10, 30, 60] as const);
/** The cards the panel may answer: a finished plan step (Met), a move outside a plan (Keep), the Sharpen goal offer
 * (Sharpen) and its review (Use sharpened), and a question or close-up question that marks a recommended option. */
export const AUTO_APPROVE_KINDS = Object.freeze(['plan_step', 'move', 'sharpen_offer', 'sharpen_review', 'question', 'closeup'] as const);
export type AutoApproveKind = typeof AUTO_APPROVE_KINDS[number];
export type AutoApproveRecord = { type: 'auto_approve'; kind: AutoApproveKind; answer: string; delay: number; card?: string };

const isKind = (value: unknown): value is AutoApproveKind => (AUTO_APPROVE_KINDS as readonly unknown[]).includes(value);

/** The diagnostics row for the panel's auto_approved command ({kind, answer, delay, card?}), or null when malformed. */
export function autoApproveRecord(command: unknown): AutoApproveRecord | null {
  if (!command || typeof command !== 'object') return null;
  const { kind, answer, delay, card } = command as Record<string, unknown>;
  if (!isKind(kind) || typeof answer !== 'string' || !answer.trim() || answer.length > 200) return null;
  if (typeof delay !== 'number' || !(AUTO_APPROVE_DELAYS as readonly number[]).includes(delay)) return null;
  return { type: 'auto_approve', kind, answer, delay, ...(typeof card === 'string' && card.length <= 200 ? { card } : {}) };
}

export const YOU_DECIDE = 'You decide';
/** A painter's question (ask_question) recommends "You decide": the painter then makes the call, as the artist would let
 * it. The panel adds that option to every question card; the painter's own spelling is kept when it offered one. */
export function recommendYouDecide<Q extends { options: readonly string[] }>(question: Q): Q & { recommended: string } {
  const own = question.options.find(option => option.toLowerCase().replace(/[ .]+$/, '').trim() === 'you decide');
  return { ...question, recommended: own ?? YOU_DECIDE };
}
