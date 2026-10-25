// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A refine step per part (openspec plan-from-request goal 2, approved by the artist 2026-10-24). Refine to the goal was one
// 6-minute step over the whole picture that the artist could not judge part by part; the full folder plan now has, after
// the Finish, one "Refine: <group>" step per group of the folder's elements, each with Met / Redo / Skip, then Accents.
// Touch-ups (the artist, 2026-10-25, approved): each part step refining its area fully took 7.5+ minutes live, 45-60 for the
// plan, so the plan refines the whole picture once first ("Refine to the goal") and each part step is a short touch-up of
// its area after it (refine-goal.ts TOUCH_UP: one round, a few minutes, only what is still above the bar there).
//
// The grouping rule (general: any folder, nothing New Moscow-specific). The folder's numbered element images are already
// in the artist's order (project-folder.ts reads them by number; artists number them as they build the picture, usually
// back to front), so neighbours are grouped: up to 4 elements one each; more, ceil(n / 2) groups between 4 and 7, the
// earlier groups one larger when they do not divide evenly (12 elements: 6 pairs; 15: 7 groups). The planner sees the
// draft's groups and may regroup by meaning (sky and moon; the bridge and the river) in its proposal; the host keeps its
// groups only when they cover every element once in 1-7 groups (plan-stages.ts shapePlan), else these.
//
// Each step finds its area: Find it on each part's name (find-it.ts, the shapes model on the goal placed on the canvas),
// the union of the found outlines is the step's Paint only here area, and refine_to_goal refines inside it (refine-goal.ts
// works in the area by default). When any part is not found the card asks the artist to select it (ask_for_selection's
// card), never refining the whole picture instead (studio.mjs refinePartArea).
// This module imports no .mjs.
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { elementsNamed, type FolderStep } from './project-folder.ts';
import { readFound } from './find-it.ts';
import { encodePlane } from './shapes/png.ts';

type Element = { name: string; guess: string };
export type RefineGroup = { label: string; parts: string[] };
/** At most this many refine steps (the proposal: aim for 4-7). */
export const MAX_GROUPS = 7;
const MIN_GROUPS = 4;

/** "Moonlit sky", "Historic buildings" -> "Moonlit sky and historic buildings"; three or more with commas. */
export function groupName(guesses: readonly string[]): string {
  const names = guesses.map((g, i) => { const t = String(g).trim(); return i && /^[A-Z](?![A-Z])/.test(t) ? t[0]!.toLowerCase() + t.slice(1) : t; }).filter(Boolean);
  return (names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names.at(-1) : names[0] ?? 'part').slice(0, 180);
}

/** The folder's elements in groups of neighbours (see the header for the rule). */
export function refineGroups(elements: readonly Element[]): RefineGroup[] {
  const n = elements.length;
  if (!n) return [];
  const count = n <= MIN_GROUPS ? n : Math.min(MAX_GROUPS, Math.max(MIN_GROUPS, Math.ceil(n / 2)));
  const size = Math.floor(n / count), extra = n % count, groups: RefineGroup[] = [];
  let at = 0;
  for (let g = 0; g < count; g++) {
    const take = elements.slice(at, at += size + (g < extra ? 1 : 0));
    groups.push({ label: groupName(take.map(e => e.guess)), parts: take.map(e => e.name) });
  }
  return groups;
}

/** A group's step: refine_to_goal inside the union of its parts' found areas (a touch-up after the whole-picture refine). */
export function refineStep(group: RefineGroup): FolderStep {
  return { title: `Refine: ${group.label}`, done_when: `A touch-up after the whole-picture refine: what is still far from the goal in ${group.label} is close to the goal image at full size, forms, windows and edges as crisp as the goal shows them.`,
    scope: group.label, kind: 'refine_part', tool: 'refine_to_goal', parts: [...group.parts] };
}

/** The element files a refine step refines: its own `parts` (those still in the folder), else the elements its title names
 * after "Refine:" (an older PLAN.md line, or a step the artist added by hand). */
export function partsOf(step: { title: string; parts?: readonly string[] }, elements: readonly Element[]): string[] {
  const names = elements.map(e => e.name);
  if (Array.isArray(step.parts) && step.parts.length) return step.parts.filter(name => names.includes(name));
  return elementsNamed(String(step.title ?? '').replace(/^\s*refine\s*:\s*/i, ''), elements);
}

type FoundMask = { mask_path: string; bounds: number[]; canvas: number[] };
/** The union of found areas (each a mask in the chat folder's .shapes, cropped to its bounds) as one found mask there,
 * with its bounds, canvas and share of the canvas: what the panel loads and adoptArea takes. One area is returned as it is. */
export async function unionFound(directory: string, found: readonly FoundMask[]): Promise<{ mask_path: string; bounds: [number, number, number, number]; canvas: [number, number]; share: number }> {
  if (!found.length) throw new Error('Nothing was found to join.');
  const planes = await Promise.all(found.map(async f => ({ f, plane: await readFound(directory, f) })));
  const [cw = 0, ch = 0] = found[0]!.canvas;
  const x0 = Math.min(...found.map(f => f.bounds[0]!)), y0 = Math.min(...found.map(f => f.bounds[1]!));
  const x1 = Math.max(...found.map(f => f.bounds[0]! + f.bounds[2]!)), y1 = Math.max(...found.map(f => f.bounds[1]! + f.bounds[3]!));
  const width = x1 - x0, height = y1 - y0, data = new Uint8Array(width * height);
  for (const { f, plane } of planes) {
    const [bx = 0, by = 0] = f.bounds;
    for (let j = 0; j < plane.height; j++) for (let i = 0; i < plane.width; i++)
      if ((plane.data[j * plane.width + i] ?? 0) >= 128) data[(by - y0 + j) * width + (bx - x0 + i)] = 255;
  }
  let inside = 0;
  for (const v of data) if (v) inside++;
  const share = Math.round(inside / Math.max(1, cw * ch) * 10000) / 10000;
  const bounds: [number, number, number, number] = [x0, y0, width, height], canvas: [number, number] = [cw, ch];
  if (found.length === 1) return { mask_path: found[0]!.mask_path, bounds, canvas, share };
  const key = createHash('sha256').update(JSON.stringify(bounds)).update(data).digest('hex').slice(0, 24);
  const folder = join(directory, '.shapes'), mask_path = join(folder, 'found-' + key + '.png');
  await mkdir(folder, { recursive: true });
  await writeFile(mask_path, encodePlane({ width, height, data }));
  return { mask_path, bounds, canvas, share };
}
