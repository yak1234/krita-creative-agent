"""Straight edges of a selection that cut through open paint.

A selection that ends in a long, dead-straight line where the painting is the same on both sides (a seed step
clipped by its `bounds` rectangle, or a colour selection stopped at a faint pasted panel) prints that line into
whatever is painted through it: run 10-12's fills and stamps showed it as a "flat block" Luna undid. A straight
edge along a real object (a flat roofline) has different paint on each side and is fine.
"""
import numpy as np

MIN_SHARE = 0.05            # an edge counts from this share of the canvas side it runs along
MIN_PIXELS = 48             # and never shorter than this
PROBE = 6                   # px either side of the edge where the paint is compared
OPEN_STEP = 24              # mean colour difference (0-255) below which both sides are the same paint
LIMIT = 8


def _runs(flags):
    """[start, end) of each run of True in a 1-d bool array."""
    padded = np.concatenate(([0], flags.astype(np.int8), [0]))
    change = np.flatnonzero(np.diff(padded))
    return zip(change[0::2], change[1::2])


def _scan(selected, colour, minimum, probe, open_step):
    """Edges between row r and r+1 of `selected` (h, w): (r + 1, start, end, colour step)."""
    h = selected.shape[0]
    crossing = selected[:-1] != selected[1:]
    found = []
    for r in np.flatnonzero(crossing.sum(axis=1) >= minimum):
        above, below = colour[max(0, r - probe)], colour[min(h - 1, r + 1 + probe)]
        for start, end in _runs(crossing[r]):
            if end - start >= minimum:
                step = float(np.abs(above[start:end] - below[start:end]).mean())
                if step < open_step:
                    found.append((int(r) + 1, int(start), int(end), step))
    return found


def open_edges(mask, bgra, rect, canvas):
    """Straight selection edges through open paint, longest first (at most LIMIT), in canvas pixels:
    [{edge: horizontal|vertical, at, from, to, length, step}]. `mask` (1 byte/px) and `bgra` (the visible painting,
    4 bytes/px) cover `rect` [x, y, w, h], which the caller grows by a pixel inside the canvas, so an edge on the
    rect's side is seen; the canvas border is never an edge."""
    min_share, min_pixels, probe, open_step = MIN_SHARE, MIN_PIXELS, PROBE, OPEN_STEP
    x, y, w, h = rect
    selected = np.frombuffer(mask, np.uint8).reshape(h, w) >= 128
    colour = np.frombuffer(bgra, np.uint8).reshape(h, w, 4)[..., :3].astype(np.int16)
    found = []
    for at, start, end, step in _scan(selected, colour, max(min_pixels, min_share * canvas[0]), probe, open_step):
        found.append({'edge': 'horizontal', 'at': y + at, 'from': x + start, 'to': x + end, 'length': end - start, 'step': round(step, 1)})
    for at, start, end, step in _scan(selected.T, colour.transpose(1, 0, 2), max(min_pixels, min_share * canvas[1]), probe, open_step):
        found.append({'edge': 'vertical', 'at': x + at, 'from': y + start, 'to': y + end, 'length': end - start, 'step': round(step, 1)})
    return sorted(found, key=lambda e: -e['length'])[:LIMIT]
