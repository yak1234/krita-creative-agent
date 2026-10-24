// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Sharper eyes (openspec luna-goal-reviewer goal 3, the artist 2026-10-24): the painter's canvas view may grow from the
// plugin's VIEW_SIDE (1568 px on the long side) to 2048 px, and Luna's goal-comparison crops to the size Luna reads 1:1,
// but only as far as each model actually reads (the resolution probe, resolution-probe.ts): a larger view is not sent
// where the model would shrink it anyway. The execution setting view_size (settings-schema.mjs) is Auto by default: the
// painter model's measured side, else today's size; or a size the artist chooses. The measured sides come from
// model-resolutions.json (shipped, from probes run with scripts/resolution-probe.ts) and the artist's own probe results
// in the data folder (resolution-probe.json), which win. The plugin is told through view_options view_side.
export const VIEW_SIDE_TODAY = 1568;
export const MAX_VIEW_SIDE = 2048;
export type ProbeRecord = { view_side?: number; crop_side?: number; reads?: number; measured_at?: string };
export type ProbeRecords = Record<string, ProbeRecord>;

/** The key a model's probe result is kept under: provider and model id. */
export const modelKey = (provider: string, model: string): string => `${provider}:${model}`;

const side = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 512;

/** The canvas view's long side: the artist's chosen size, or (Auto) the painter model's measured side within
 * MAX_VIEW_SIDE, else VIEW_SIDE_TODAY. */
export function resolvedViewSide(setting: 'auto' | number, record: ProbeRecord | null | undefined): number {
  if (typeof setting === 'number') return setting;
  return side(record?.view_side) ? Math.min(record.view_side, MAX_VIEW_SIDE) : VIEW_SIDE_TODAY;
}

/** The longest side of one goal-comparison crop: the decision model's measured crop side, else `fallback`. */
export function resolvedCropSide(record: ProbeRecord | null | undefined, fallback: number): number {
  return side(record?.crop_side) ? record.crop_side : fallback;
}
