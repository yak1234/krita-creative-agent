// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Open routes (src/open-routes.ts): the move's "allowed now / not now and why" line, from the checks the host runs on each
// call. LIVE 2026-10-23/24: about 25 refusals in 10 chats, found one at a time. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { openRoutesLine } from '../src/open-routes.ts';

test('the line names what is allowed now and what is not, with the reason the host would give', () => {
  const line = openRoutesLine({ fillNudge: true, wholeTransfer: 'Reference transfer is for underpainting and is off from step 3 of 3: it only stamps the reference again as dabs. A focal patch ...',
    patchTransfer: null, typedCap: { marks: 12, px: 120 }, unifyUsed: 'gaussian blur filter', liveFilters: true });
  assert.match(line, /^OPEN ROUTES this move/);
  assert.match(line, /Allowed now:[^\n]*paint_from_reference on a region of at most 20% of the canvas/);
  assert.match(line, /Not now:[^\n]*a whole-canvas paint_from_reference \(off from step 3 of 3\)/);
  assert.match(line, /fill_region before a reference colour pass/);
  assert.match(line, /typed strokes over 12 small marks a call or wider than 120 px/);
  assert.match(line, /another whole-canvas softening pass \(gaussian blur filter used the chat's one; soften an element or a region instead\)/);
  assert.match(line, /apply_filter as a live mask or filter layer \(use mode copy\)/);
  assert.match(line, /the artist's own layers are never filtered or repainted/);
});

test('an open canvas says so: every route is open', () => {
  const line = openRoutesLine({ fillNudge: false, wholeTransfer: null, patchTransfer: null, typedCap: null, unifyUsed: null, liveFilters: false });
  assert.match(line, /Allowed now:[^\n]*whole-canvas paint_from_reference[^\n]*typed strokes/);
  assert.doesNotMatch(line, /Not now:[^\n]*(fill_region|typed)/);
});
