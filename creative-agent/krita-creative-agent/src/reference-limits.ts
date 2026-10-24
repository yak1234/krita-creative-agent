// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// How large a reference the reference tools take, declared once for the companion (the plugin's own copy is
// creative_reference.py REFERENCE_FILE_BYTES / REFERENCE_PIXELS). Large enough for a goal image sharpened 4x
// (goal-sharpen.ts: 5792 x 4344 for New Moscow): the transfer reads it whole, the other tools (trace, accents, masses,
// likeness, close-up alignment) decode it reduced while read. The plugin checks a file's declared size before decoding.
export const REFERENCE_BYTES = 64 * 1024 * 1024;
export const REFERENCE_PIXELS = 26_000_000;
export const REFERENCE_MB = REFERENCE_BYTES / (1024 * 1024);
/** Above this many pixels a plain PNG reference is decoded in the companion (png-rgba.ts), not on Krita's GUI thread. */
export const PLUGIN_DECODE_PIXELS = 4_000_000;
/** Recipe sizes in source pixels, 4x their bounds for a 1500-pixel goal: a goal sharpened 4x needs four times the source
 * pixels for the same stroke on the canvas (a 24-pixel step on the original is a 96-pixel one on the sharpened goal). */
export const STEP_MAX = 256, EDGE_SPACING_MAX = 64, SURFACE_SPACING_MAX = 128, SURFACE_LENGTH_MAX = 800;
