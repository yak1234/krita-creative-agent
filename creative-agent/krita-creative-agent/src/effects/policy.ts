// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The build policy of custom effects (openspec custom-effects): effects/policy.yaml, the numbers that bound when and how an
// effect is built. The file ships with the app and is read once; a missing, unreadable or invalid file (or a single value
// outside what the engine allows) gives the default, never an error, so a build always has a policy.
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';

export type Policy = {
  failures_before_build: number;   // the same effect failing this many times in a chat triggers a build
  candidates: number;              // recipes built per attempt
  retries: number;                 // one retry per invalid candidate
  minutes: number;                 // the whole build's time budget
  preview_side: number;            // candidates render at this long side, px
  auto_keep_min_seconds: number;   // Auto-approve presses Keep after at least this long
  token_effort: number;            // a move painting an effect by hand with fewer strokes than this (no fill, no effect tool) failed; 0: off
};

export const DEFAULT_POLICY: Readonly<Policy> = Object.freeze({
  failures_before_build: 2, candidates: 3, retries: 1, minutes: 4, preview_side: 1024, auto_keep_min_seconds: 20, token_effort: 40 });

/** The most (and least) each value may be, whatever the file says: the build budget's hard limits. */
const LIMITS: Record<keyof Policy, [number, number]> = {
  failures_before_build: [1, 10], candidates: [1, 3], retries: [0, 1], minutes: [1, 4], preview_side: [128, 1024], auto_keep_min_seconds: [20, 3600], token_effort: [0, 1000],
};

/** The policy in `file`; each value that is missing, not a whole number or outside its limits is the default. Never throws. */
export function readPolicy(file: string): Policy {
  const policy: Policy = { ...DEFAULT_POLICY };
  let data: unknown;
  try {
    data = parse(readFileSync(file, 'utf8'), { logLevel: 'silent', maxAliasCount: 0 });
  } catch {
    return policy;
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return policy;
  for (const key of Object.keys(LIMITS) as (keyof Policy)[]) {
    const value = (data as Record<string, unknown>)[key];
    const [lo, hi] = LIMITS[key];
    if (typeof value === 'number' && Number.isInteger(value) && value >= lo && value <= hi) policy[key] = value;
  }
  return policy;
}
