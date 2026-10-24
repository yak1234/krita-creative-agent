// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The placed goal as the plugin reads it from the chat folder: {path, sha256, size, source, target} (finish_pass.py
// check_goal). paint_finish sends it, and so do the full-size checks for an area (area_compare.py; finish-stage goals 7-8):
// the goal file (its sharpened copy when there is one) where the whole-picture transfer placed it, never as base64.
import { readFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';

export type PlacedGoal = { reference: { id: string; path: string; width?: number; height?: number; name?: string; sharpened?: unknown };
  source: number[]; target: number[]; from: 'transfer' | 'proportions' };
export type GoalSpec = { path: string; sha256: string; size: [number, number]; source: number[]; target: number[] };

// A goal's hash, by file and modification: a sharpened goal is a 38 MB file, read again only when it changes.
const hashes = new Map<string, { stamp: string; sha: string }>();
export async function fileHash(path: string): Promise<string> {
  const info = await stat(path), stamp = `${info.size}:${info.mtimeMs}`, known = hashes.get(path);
  if (known?.stamp === stamp) return known.sha;
  const sha = createHash('sha256').update(await readFile(path)).digest('hex');
  hashes.set(path, { stamp, sha });
  while (hashes.size > 4) hashes.delete(hashes.keys().next().value!);
  return sha;
}

const hundredths = (v: number) => Math.round(v * 100) / 100;
/** The spec the plugin checks; throws when the goal's size is unknown. */
export async function goalSpec(goal: PlacedGoal): Promise<GoalSpec> {
  const width = Number(goal.reference.width), height = Number(goal.reference.height);
  if (!(width > 0 && height > 0)) throw new Error('The goal image’s size is unknown: attach it again.');
  return { path: goal.reference.path, sha256: await fileHash(goal.reference.path), size: [width, height],
    source: goal.source.map(hundredths), target: goal.target.map(hundredths) };
}
