# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finish (paint_finish; openspec finish-stage, approved by the artist 2026-10-24): the stage between the whole-picture
underpainting and the accents, which turns the underpainting's even dabs into a finished painting. Soft areas and hard
areas are treated differently, as a painter does:

- where the GOAL has little structure (sky, mist, water: its gradient magnitude, blurred over EDGE_SIGMA, under SOFT_T),
  the canvas's OWN pixels are smoothed by a self-guided filter (box-filter guided filter, guide = the canvas's grey,
  GUIDED_R, GUIDED_EPS): the dabs melt into gradients while edges stay;
- elsewhere (buildings, towers, a bridge) short strokes are repainted from the goal: each grows both ways from a seed
  along the form (perpendicular to the goal's structure-tensor gradient), ends where the goal's Lab colour differs from
  the seed's by more than STOP, and has the goal's colour at its seed. Never along outlines: no tracing.

The algorithm and its numbers are the offline spike the artist judged (scratchpad finish/finish.py, 2026-10-24); sizes
are canvas pixels at SCALE_SIDE on the long side and scale with the canvas (never below a pixel or two).

As accent_adjust.py does: the clean composite below the Finish group is read once before anything is written, the work
is done per TILE square the area touches (never the whole canvas at once), and the result is two plain paint layers at
normal blending with the blend baked ("blend": the smoothed paint, its alpha the soft mask; "strokes": the strokes, their
alpha times the hard mask) in one "Finish" group inside the move's stage group, so the move's Undo removes it. Each tile
is read padded by the filters' and strokes' reach, so tiles join without seams; every stroke comes from a seed on one
grid over the whole canvas whose random numbers are a hash of its grid cell (a fixed seed per call), so a stroke that
crosses into the next tile is drawn there identically. No live filter mask. Krita keeps every write out of the
protected areas. Krita's window and the panel's Stop are served between strokes (RESPONSIVE_SECONDS), and the progress
file says which tile is painting; Stop ends the pass after the stroke it is on and keeps what is done.

The goal comes as a file in the chat folder (the attached goal, or its sharpened copy) with where its crop sits on the
canvas ({path, sha256, size, source, target}: the whole-picture transfer's placement, from the companion), decoded here
with OpenCV once a call; only its pixels under the work are resampled onto the canvas, in one piece.
"""
import importlib
import math
import os
import stat
import threading
import time
import numpy as np

FIELDS = ('name', 'goal', 'box', 'selection', 'inside_shape', 'detail', 'stage_id', 'region', 'expected_revision', 'panel')
GOAL_FIELDS = ('path', 'sha256', 'size', 'source', 'target')
SCALE_SIDE = 6000                             # the spike's canvas: every size below is in its pixels
EDGE_SIGMA = 40                               # how far "how much structure is here" looks
SOFT_T, SOFT_RAMP = 0.014, 0.006              # structure under SOFT_T is soft, fading over SOFT_RAMP
SOFT_BLUR = 6                                 # the soft mask's own blur
GUIDED_R, GUIDED_EPS = 10, 0.004              # the self-guided filter's radius and regularisation
TENSOR_SIGMA = 3                              # the structure tensor's blur: the form direction
COLOUR_SIGMA = 1.0                            # the goal's colour is read through this blur
SPACING = 4                                   # a seed every this many pixels (jittered in its cell)
STEP = 2                                      # a stroke grows this far a step
LENGTH = (10, 34)                             # a stroke's length at most (random between these)
WIDTH = (5, 9)                                # its width, narrower for a short stroke
STOP = 26                                     # Lab distance from the seed's colour that ends a stroke (L 0-100)
OPACITY = (0.8, 0.95)
SEED = 7                                      # fixed: the same call paints the same strokes
# Fine detail (openspec finish-stage goal 6, the artist 2026-10-24: "yess we need both"): on New Moscow the whole-picture
# Finish's 5-9 px strokes were blobby beside the domed church's 2-4 px windows and edges, and every check looked at reduced
# views. The lead's try-out on the church (550 x 750 canvas px of the 6000 px canvas, sharpened goal): these sizes, 100k
# strokes in 4.5 s, difference to the goal (blurred 4 px) 5.17 -> 2.14, windows and dome edges crisp. Only what differs
# from the default is listed; the soft mask and the form field are the default's. For an area: at most FINE_SHARE of the
# canvas (the whole 6000 x 4500 canvas fine would be about 6 M strokes, minutes on Krita's GUI thread).
# finer: Refine to the goal's second level (goal 8, the artist 2026-10-24: "i want the end result where our accents and
# finishes make it move eventually to the final"): fine repeated paints the same strokes again (church: 2.44 -> 2.44); finer
# took the church from colour 2.45 / edges 2.44 to 1.27 / 1.48 (area_compare.py), windows of 1-2 px drawn.
DETAILS = {'normal': {}, 'fine': {'width': (2, 4), 'length': (6, 18), 'spacing': 2, 'stop': 20, 'r': 4},
           'finer': {'width': (1.5, 2), 'length': (4, 10), 'spacing': 2, 'stop': 14, 'r': 2}}
DETAIL_LEVELS = ('normal', 'fine', 'finer')
FINE_SHARE = 0.15                             # fine and finer: at most this share of the canvas a call
TILE = 512                                    # work square: only the squares the area touches are read and written
RESPONSIVE_SECONDS = 0.2                      # Krita's events run at least this often during a pass
MAX_GOAL_BYTES = 64 * 1024 * 1024             # creative_reference.py REFERENCE_FILE_BYTES and REFERENCE_PIXELS
MAX_GOAL_PIXELS = 26_000_000
GOLDEN = np.uint64(0x9E3779B97F4A7C15)
KEYS = {'blend': 'blend_tiles', 'strokes': 'stroke_tiles'}

# command_queue is not hot-reloaded (creative_tools.py): fall back to a flag of our own after a plugin-only reload.
stop_requested = getattr(importlib.import_module('.command_queue', __package__), 'stop_requested', None) or threading.Event()


def reach3(sigma):
    """A Gaussian's reach (three sigma), the kernel radius every blur here uses, so a tile's pad is exact."""
    return int(math.ceil(3 * sigma))


def blur(image, sigma):
    import cv2
    radius = reach3(sigma)
    return cv2.GaussianBlur(image, (2 * radius + 1, 2 * radius + 1), sigma) if radius > 0 else image


def sizes(width, height, detail='normal'):
    """The spike's sizes on this canvas (or the fine try-out's, DETAILS): scaled by its long side against SCALE_SIDE, never
    below a pixel or two. `k` also scales the gradient (a structure is as strong per picture, whatever the pixels)."""
    if detail not in DETAILS:
        raise ValueError('detail is normal, fine or finer.')
    k = max(width, height) / SCALE_SIDE
    own = DETAILS[detail]
    length, wide = own.get('length', LENGTH), own.get('width', WIDTH)
    out = {'k': k, 'detail': detail, 'edge': max(2.0, EDGE_SIGMA * k), 'soft_blur': max(1.0, SOFT_BLUR * k),
           'r': max(2, int(round(own.get('r', GUIDED_R) * k))), 'stop': own.get('stop', STOP),
           'tensor': max(1.0, TENSOR_SIGMA * k), 'colour': max(0.5, COLOUR_SIGMA * k), 'spacing': max(2.0, own.get('spacing', SPACING) * k),
           'step': max(1.0, STEP * k), 'length': (max(4.0, length[0] * k), max(6.0, length[1] * k)),
           'width': (max(1.5, wide[0] * k), max(2.0, wide[1] * k))}
    out['steps'] = int(math.ceil(out['length'][1] / 2 / out['step']))
    # How far a stroke's pixels lie from its seed (its steps, half its widest width, anti-aliasing), and how far around
    # a point the goal is read for the soft mask and for a stroke's direction and colour.
    out['reach'] = int(math.ceil(out['steps'] * out['step'] + out['width'][1] / 2 + 2))
    out['mask_pad'] = reach3(out['edge']) + reach3(out['soft_blur']) + 1
    out['trace_pad'] = out['steps'] * int(math.ceil(out['step'])) + max(reach3(out['tensor']), reach3(out['colour'])) + 2
    out['goal_pad'] = out['reach'] + max(out['mask_pad'], out['trace_pad'])
    out['canvas_pad'] = 2 * out['r'] + 1
    return out


def grow(rect, pad, width, height):
    """`rect` [x, y, w, h] grown by `pad` on every side, inside the canvas."""
    x, y, w, h = rect
    left, top = max(0, x - pad), max(0, y - pad)
    return [left, top, min(width, x + w + pad) - left, min(height, y + h + pad) - top]


def tiles(bounds, width, height):
    """The TILE squares [x, y, w, h] (clipped to the canvas and to `bounds`) that `bounds` touches, top to bottom."""
    x, y, w, h = bounds
    out = []
    for ty in range(max(0, y // TILE), min((height - 1) // TILE, (y + h - 1) // TILE) + 1):
        for tx in range(max(0, x // TILE), min((width - 1) // TILE, (x + w - 1) // TILE) + 1):
            left, top = max(x, tx * TILE), max(y, ty * TILE)
            right, bottom = min(x + w, (tx + 1) * TILE, width), min(y + h, (ty + 1) * TILE, height)
            if right > left and bottom > top:
                out.append([left, top, right - left, bottom - top])
    return out


def placed(spec):
    """The canvas pixels the goal's target covers, whole pixels [x, y, w, h] (it may reach past the canvas)."""
    x, y, w, h = spec['target']
    left, top = int(math.floor(x)), int(math.floor(y))
    return [left, top, int(math.ceil(x + w)) - left, int(math.ceil(y + h)) - top]


def bounding(rects):
    """The rect [x, y, w, h] around all `rects`."""
    left, top = min(r[0] for r in rects), min(r[1] for r in rects)
    return [left, top, max(r[0] + r[2] for r in rects) - left, max(r[1] + r[3] for r in rects) - top]


def crop(pixels, at, rect):
    """The part of `pixels` (an array of canvas rect `at`) under canvas `rect`."""
    return pixels[rect[1] - at[1]:rect[1] - at[1] + rect[3], rect[0] - at[0]:rect[0] - at[0] + rect[2]]


def intersect(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return [left, top, right - left, bottom - top] if right > left and bottom > top else None


def soft_mask(goal, size):
    """Where the goal is soft (1) or hard (0): float32 of the goal crop's size (BGR float 0-1). Only the part at least
    size['mask_pad'] inside the crop's edges (or at the canvas's own edges) equals the whole canvas's mask."""
    import cv2
    grey = cv2.cvtColor(goal, cv2.COLOR_BGR2GRAY)
    gx, gy = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3) / 8, cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3) / 8
    structure = blur(np.hypot(gx, gy) * np.float32(size['k']), size['edge'])
    return blur(np.clip((SOFT_T - structure) / SOFT_RAMP, 0, 1).astype(np.float32), size['soft_blur'])


def box(a, r):
    import cv2
    return cv2.boxFilter(a, -1, (2 * r + 1, 2 * r + 1))


def guided(guide, p, r, eps):
    """The box-filter guided filter of `p` by `guide` (He et al.): edge-preserving smoothing."""
    mean_i, mean_p = box(guide, r), box(p, r)
    a = (box(guide * p, r) - mean_i * mean_p) / (box(guide * guide, r) - mean_i * mean_i + eps)
    b = mean_p - a * mean_i
    return box(a, r) * guide + box(b, r)


def smoothed(canvas, r):
    """The canvas's own BGR (float 0-1) smoothed by the self-guided filter, channel by channel, guided by its grey."""
    import cv2
    grey = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    return np.dstack([guided(grey, np.ascontiguousarray(canvas[..., c]), r, GUIDED_EPS) for c in range(3)])


def uniform(ix, iy, salt):
    """Uniform numbers in [0, 1) for seed grid cells (ix, iy): a hash of the cell, the call's SEED and `salt` (splitmix64),
    the same whichever tile asks."""
    with np.errstate(over='ignore'):
        h = (ix.astype(np.uint64) * GOLDEN) ^ (iy.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)) \
            ^ (np.uint64(SEED * 64 + salt) * np.uint64(0x165667B19E3779F9))
        h ^= h >> np.uint64(30); h *= np.uint64(0xBF58476D1CE4E5B9)
        h ^= h >> np.uint64(27); h *= np.uint64(0x94D049BB133111EB)
        h ^= h >> np.uint64(31)
    return (h >> np.uint64(11)).astype(np.float64) * (1.0 / (1 << 53))


def seeds(rect, size, limit):
    """The seeds whose strokes can reach `rect`: every grid cell of size['spacing'] within size['reach'] of it, jittered
    in its cell, inside `limit` (the goal's place on the canvas). Arrays x, y and per-seed random numbers u (keep,
    length, width, opacity, order)."""
    spacing, reach = size['spacing'], size['reach']
    x0, y0, w, h = rect
    ix = np.arange(int(math.floor((x0 - reach) / spacing)) - 1, int(math.ceil((x0 + w + reach) / spacing)) + 1)
    iy = np.arange(int(math.floor((y0 - reach) / spacing)) - 1, int(math.ceil((y0 + h + reach) / spacing)) + 1)
    gx, gy = np.meshgrid(ix, iy)
    gx, gy = gx.ravel(), gy.ravel()
    on = (gx >= 0) & (gy >= 0)
    gx, gy = gx[on], gy[on]
    x = gx * spacing + uniform(gx, gy, 1) * spacing
    y = gy * spacing + uniform(gx, gy, 2) * spacing
    lx, ly, lw, lh = limit
    keep = (x >= max(lx, x0 - reach)) & (x < min(lx + lw, x0 + w + reach)) & (y >= max(ly, y0 - reach)) & (y < min(ly + lh, y0 + h + reach))
    gx, gy, x, y = gx[keep], gy[keep], x[keep], y[keep]
    return x, y, {name: uniform(gx, gy, salt) for salt, name in enumerate(('keep', 'length', 'width', 'opacity', 'order'), 3)}


def field(goal, size):
    """The form direction (along the form, across the goal's gradient: fx, fy), the goal's Lab (float, L 0-100) and its
    colour (BGR 0-1), each read through its blur."""
    import cv2
    grey = cv2.cvtColor(goal, cv2.COLOR_BGR2GRAY)
    gx, gy = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3) / 8, cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3) / 8
    a, b, c = (blur(v, size['tensor']) for v in (gx * gx, gx * gy, gy * gy))
    theta = 0.5 * np.arctan2(2 * b, a - c)
    colour = blur(goal, size['colour'])
    return -np.sin(theta).astype(np.float32), np.cos(theta).astype(np.float32), cv2.cvtColor(colour, cv2.COLOR_BGR2LAB), colour


def trace(x, y, longest, fx, fy, lab, origin, width, height, size):
    """Every seed's stroke at once: from the seed both ways along the field in size['step'] steps until half its length
    (`longest`), off the canvas, or where the goal's Lab differs from the seed's by more than size['stop']. The field arrays
    start at canvas `origin`. Returns points (n, 2 * steps + 1, 2) in canvas pixels and the first and last valid index."""
    steps, step = size['steps'], size['step']
    ox, oy = origin
    n = len(x)
    points = np.zeros((n, 2 * steps + 1, 2), np.float64)
    points[:, steps, 0], points[:, steps, 1] = x, y
    c0 = lab[np.floor(y).astype(int) - oy, np.floor(x).astype(int) - ox]
    first, last = np.full(n, steps), np.full(n, steps)
    for sign in (1, -1):
        px, py = x.copy(), y.copy()
        dx0, dy0 = np.zeros(n, np.float32), np.zeros(n, np.float32)
        alive = np.ones(n, bool)
        for k in range(steps):
            alive &= k * step < longest / 2
            alive &= (px >= 0) & (py >= 0) & (px < width) & (py < height)
            if not alive.any():
                break
            i = np.flatnonzero(alive)
            xi, yi = np.floor(px[i]).astype(int) - ox, np.floor(py[i]).astype(int) - oy
            dx, dy = fx[yi, xi], fy[yi, xi]
            if k == 0:
                dx, dy = dx * sign, dy * sign
            else:
                flip = dx * dx0[i] + dy * dy0[i] < 0
                dx, dy = np.where(flip, -dx, dx), np.where(flip, -dy, dy)
            px[i] += dx * step; py[i] += dy * step
            dx0[i], dy0[i] = dx, dy
            inside = (px[i] >= 0) & (py[i] >= 0) & (px[i] < width) & (py[i] < height)
            ok = inside.copy()
            j = i[inside]
            ok[inside] = np.linalg.norm(lab[np.floor(py[j]).astype(int) - oy, np.floor(px[j]).astype(int) - ox] - c0[j], axis=1) <= size['stop']
            alive[i[~ok]] = False
            kept = i[ok]
            slot = steps + sign * (k + 1)
            points[kept, slot, 0], points[kept, slot, 1] = px[kept], py[kept]
            if sign == 1:
                last[kept] = slot
            else:
                first[kept] = slot
    return points, first, last


def strokes_for(rect, goal, goal_rect, hard, limit, width, height, size, breathe=None):
    """The strokes layer of `rect` (premultiplied BGR and alpha, float32 h x w x 4) from the goal crop (BGR 0-1) at
    `goal_rect`, whose hard mask (1 - soft) is `hard`, and how many strokes touch it. Strokes are composited in their
    seeds' order (a hash), so every tile draws a shared stroke the same. `breathe(count)` runs between strokes."""
    import cv2
    fx, fy, lab, colour = field(goal, size)
    gx0, gy0 = goal_rect[0], goal_rect[1]
    x, y, u = seeds(rect, size, intersect(limit, [0, 0, width, height]) or [0, 0, 0, 0])
    xi, yi = np.floor(x).astype(int) - gx0, np.floor(y).astype(int) - gy0
    kept = u['keep'] <= hard[yi, xi]
    x, y, xi, yi = x[kept], y[kept], xi[kept], yi[kept]
    u = {name: values[kept] for name, values in u.items()}
    longest = size['length'][0] + u['length'] * (size['length'][1] - size['length'][0])
    points, first, last = trace(x, y, longest, fx, fy, lab, (gx0, gy0), width, height, size)
    count = last - first + 1
    widths = (size['width'][0] + u['width'] * (size['width'][1] - size['width'][0])) * (0.6 + 0.4 * np.minimum(1, count / 6))
    opacity = OPACITY[0] + u['opacity'] * (OPACITY[1] - OPACITY[0])
    colours = colour[yi, xi]
    rx, ry, rw, rh = rect
    out = np.zeros((rh, rw, 4), np.float32)
    drawn = 0
    for s in np.argsort(u['order'], kind='stable'):
        poly = points[s, first[s]:last[s] + 1]
        if len(poly) < 2:
            poly = np.vstack([poly, poly + 0.5])
        w = widths[s]
        xa, ya = (np.maximum(poly.min(0) - w, 0)).astype(int)
        xb, yb = (poly.max(0) + w + 1).astype(int)
        xb, yb = min(xb, width), min(yb, height)
        left, top, right, bottom = max(xa, rx), max(ya, ry), min(xb, rx + rw), min(yb, ry + rh)
        if right <= left or bottom <= top:
            continue
        m = np.zeros((yb - ya, xb - xa), np.uint8)
        cv2.polylines(m, [((poly - (xa, ya)) * 4).astype(np.int32)], False, 255, max(1, int(w)), cv2.LINE_AA, shift=2)
        a = m[top - ya:bottom - ya, left - xa:right - xa].astype(np.float32) * np.float32(opacity[s] / 255)
        view = out[top - ry:bottom - ry, left - rx:right - rx]
        view *= (1 - a)[..., None]
        view += a[..., None] * np.append(colours[s], 1).astype(np.float32)
        drawn += 1
        if breathe is not None and drawn % 256 == 0:
            breathe(drawn)
    return out, drawn


def finish_tile(tile, canvas, canvas_rect, goal, goal_rect, limit, width, height, size, coverage=None, breathe=None):
    """One tile's two layers as BGRA uint8 bytes (None where nothing shows) and what it did. `canvas` is the clean
    composite (BGRA uint8) at `canvas_rect` and `goal` the goal resampled onto the canvas (BGR uint8) at `goal_rect`, both
    padded around the tile; `coverage` (tile's h x w, 0-1) the area. Blend: the smoothed canvas, alpha the soft mask.
    Strokes: their colour, alpha theirs times the hard mask. Over the canvas they give the spike's picture:
    canvas*(1 - soft) + smoothed*soft, the strokes over that where it is hard."""
    x, y, w, h = tile
    goal_f = goal.astype(np.float32) / 255
    soft_all = soft_mask(goal_f, size)
    inner_goal = (slice(y - goal_rect[1], y - goal_rect[1] + h), slice(x - goal_rect[0], x - goal_rect[0] + w))
    soft = soft_all[inner_goal]
    keep = np.ones((h, w), np.float32) if coverage is None else coverage.astype(np.float32)
    inner_canvas = (slice(y - canvas_rect[1], y - canvas_rect[1] + h), slice(x - canvas_rect[0], x - canvas_rect[0] + w))
    seen = canvas[inner_canvas]
    blend_bytes = strokes_bytes = None
    report = {'soft': float(soft.mean()), 'strokes': 0}
    alpha = soft * keep * (seen[..., 3].astype(np.float32) / 255)
    if alpha.max() > 0:
        own = smoothed(canvas[..., :3].astype(np.float32) / 255, size['r'])[inner_canvas]
        pixels = np.empty((h, w, 4), np.uint8)
        pixels[..., :3] = np.clip(np.round(own * 255), 0, 255)
        pixels[..., 3] = np.clip(np.round(alpha * 255), 0, 255)
        blend_bytes = pixels.tobytes()
    hard = 1 - soft_all
    if (hard[inner_goal] * keep).max() > 0:
        layer, report['strokes'] = strokes_for(tile, goal_f, goal_rect, hard, limit, width, height, size, breathe)
        a = layer[..., 3]
        pixels = np.zeros((h, w, 4), np.uint8)
        shown = a > 0
        pixels[..., :3][shown] = np.clip(np.round(layer[..., :3][shown] / a[shown][:, None] * 255), 0, 255)
        pixels[..., 3] = np.clip(np.round(a * (1 - soft) * keep * 255), 0, 255)
        if pixels[..., 3].any():
            strokes_bytes = pixels.tobytes()
    return blend_bytes, strokes_bytes, report


def check_goal(spec, folder, width, height):
    """The goal {path, sha256, size, source, target}: a file directly inside the chat folder (or a folder in it), no link,
    at most MAX_GOAL_BYTES; `source` a crop of its listed pixels (`size`), `target` where it sits on the canvas with the
    same proportions. Returns the checked spec."""
    from .creative_validation import fields
    if not isinstance(spec, dict):
        raise ValueError('goal is {path, sha256, size, source, target}.')
    fields(spec, GOAL_FIELDS, GOAL_FIELDS)
    refused = ValueError('The goal image must be a file in the chat folder.')
    path = spec['path']
    if not folder or not isinstance(path, str) or not os.path.isabs(path) or '..' in path.split(os.sep):
        raise refused
    root = os.path.realpath(folder)
    if os.path.commonpath([root, os.path.realpath(path)]) != root or os.path.islink(path):
        raise refused
    if not isinstance(spec['sha256'], str) or len(spec['sha256']) != 64:
        raise ValueError('goal sha256 is the file’s hash.')
    numbers = lambda v, n: isinstance(v, list) and len(v) == n and all(not isinstance(i, bool) and isinstance(i, (int, float)) for i in v)
    if not numbers(spec['size'], 2) or not all(0 < v <= 100000 for v in spec['size']):
        raise ValueError('goal size is [width, height] of the goal image.')
    for key in ('source', 'target'):
        if not numbers(spec[key], 4) or spec[key][2] <= 0 or spec[key][3] <= 0:
            raise ValueError('goal %s is [x, y, w, h].' % key)
    sx, sy, sw, sh = spec['source']
    if sx < 0 or sy < 0 or sx + sw > spec['size'][0] + 0.5 or sy + sh > spec['size'][1] + 0.5:
        raise ValueError('goal source must fit the goal image.')
    if abs(sw / sh / (spec['target'][2] / spec['target'][3]) - 1) > 0.02:
        raise ValueError('goal source and target must have matching proportions.')
    if intersect([int(v) for v in spec['target']], [0, 0, width, height]) is None:
        raise ValueError('The goal does not lie on the canvas.')
    return spec


def read_goal(spec):
    """The goal file's pixels (BGR uint8, as OpenCV decodes it) after its size and hash are checked: opened without
    following a link, a regular file, its declared size from the header before anything is decoded."""
    import cv2
    import hashlib
    refused = ValueError('The goal image must be a file in the chat folder.')
    try:
        handle = os.open(spec['path'], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except FileNotFoundError:
        raise ValueError('The goal image is no longer in the chat folder.') from None
    except OSError:
        raise refused from None
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_GOAL_BYTES:
            raise ValueError('The goal image must be a file of at most %d MB.' % (MAX_GOAL_BYTES // (1024 * 1024)))
        chunks, total = [], 0
        while total <= MAX_GOAL_BYTES:
            chunk = os.read(handle, 1 << 22)
            if not chunk:
                break
            chunks.append(chunk); total += len(chunk)
        data = b''.join(chunks)
    finally:
        os.close(handle)
    if hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('The goal image changed: look at the canvas and try again.')
    declared = declared_size(data)
    if declared is None or declared[0] * declared[1] > MAX_GOAL_PIXELS:
        raise ValueError('The goal image must be a PNG or JPEG of at most %d million pixels.' % (MAX_GOAL_PIXELS // 1_000_000))
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if pixels is None or (pixels.shape[1], pixels.shape[0]) != declared:
        raise ValueError('Could not decode the goal image.')
    return pixels


def declared_size(data):
    """(width, height) a PNG's or a JPEG's header declares, read before anything is decoded; None for anything else."""
    import struct
    if data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR':
        return struct.unpack('>II', data[16:24])
    if data[:2] != b'\xff\xd8':
        return None
    position = 2
    while position + 9 < len(data):
        if data[position] != 0xFF:
            return None
        marker = data[position + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        length = struct.unpack('>H', data[position + 2:position + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack('>HH', data[position + 5:position + 9])
            return width, height
        position += 2 + length
    return None


class GoalOnCanvas:
    """The goal's crop resampled onto canvas pixels: any canvas rect, the same values whichever rect asks (each canvas
    pixel's centre mapped into the goal, bicubic; a crop reduced by more than 2x is first area-reduced to about the
    target's size, once)."""

    def __init__(self, pixels, spec):
        import cv2
        dh, dw = pixels.shape[:2]
        fx, fy = dw / spec['size'][0], dh / spec['size'][1]           # the listed pixels onto the decoded ones
        sx, sy, sw, sh = spec['source']
        left, top = int(math.floor(sx * fx)), int(math.floor(sy * fy))
        right, bottom = min(dw, int(math.ceil((sx + sw) * fx))), min(dh, int(math.ceil((sy + sh) * fy)))
        crop = pixels[top:bottom, left:right]
        tx, ty, tw, th = spec['target']
        scale = tw / (sw * fx)                                        # canvas pixels a decoded pixel
        self.origin = (sx * fx - left, sy * fy - top)
        if scale < 0.5:
            reduce = (max(1, int(round(crop.shape[1] * scale * 2))), max(1, int(round(crop.shape[0] * scale * 2))))
            k = reduce[0] / crop.shape[1], reduce[1] / crop.shape[0]
            crop = cv2.resize(crop, reduce, interpolation=cv2.INTER_AREA)
            self.origin = (self.origin[0] * k[0], self.origin[1] * k[1])
            scale = scale / k[0]
        self.crop, self.scale, self.target = np.ascontiguousarray(crop), scale, (tx, ty)

    def rect(self, rect):
        """BGR uint8 of canvas `rect` [x, y, w, h]: canvas pixel X sits at goal (X + 0.5 - tx) / scale + ox - 0.5."""
        import cv2
        x, y, w, h = rect
        a = 1.0 / self.scale
        matrix = np.array([[a, 0, (x + 0.5 - self.target[0]) * a + self.origin[0] - 0.5],
                           [0, a, (y + 0.5 - self.target[1]) * a + self.origin[1] - 0.5]], np.float64)
        return cv2.warpAffine(self.crop, matrix, (w, h), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


class FinishCraft:
    """The plugin side of paint_finish: one reversible pass, one Finish group of two baked layers."""

    def _finish_limit(self, doc, session, params):
        """The area: its coverage reader (x, y, w, h -> h x w float 0-1, or None for all) and its bounds on the canvas."""
        width, height = doc.width(), doc.height()
        if params.get('selection'):
            selection = self._region_load(session, params['selection'], doc)
            bounds = [selection.x(), selection.y(), selection.width(), selection.height()] if hasattr(selection, 'x') else [0, 0, width, height]
            read = lambda x, y, w, h: np.frombuffer(bytes(selection.pixelData(x, y, w, h)), np.uint8).reshape(h, w).astype(np.float32) / 255
            return read, bounds
        if params.get('inside_shape'):
            from . import shape_mask
            rect, data = shape_mask.read_shape(params['inside_shape'], session.get('output'), width, height)
            plane = np.frombuffer(data, np.uint8).reshape(rect[3], rect[2])
            def read(x, y, w, h):
                out = np.zeros((h, w), np.float32)
                part = intersect([x, y, w, h], list(rect))
                if part:
                    px, py, pw, ph = part
                    out[py - y:py - y + ph, px - x:px - x + pw] = plane[py - rect[1]:py - rect[1] + ph, px - rect[0]:px - rect[0] + pw] / 255.0
                return out
            return read, list(rect)
        if params.get('box'):
            return None, [int(v) for v in params['box']]
        return None, [0, 0, width, height]

    def _finish_validate(self, doc, session, params):
        from .creative_validation import fields, text
        fields(params, FIELDS, ('name', 'goal'))
        text(params['name'], 'name', 120)
        check_goal(params['goal'], session.get('output'), doc.width(), doc.height())
        if sum(1 for key in ('box', 'selection', 'inside_shape') if params.get(key)) > 1:
            raise ValueError('Limit the finish with one area: a box, a selection or a shape.')
        if params.get('box') is not None:
            from .geometry_data import bounds as checked_bounds
            checked_bounds(params['box'], doc.width(), doc.height())
        if params.get('selection'):
            self._region_check_named(doc, session, text(params['selection'], 'selection', 2000))
        if params.get('inside_shape'):
            self._region_shape_selection(doc, session, params['inside_shape'])
        detail = params.get('detail', 'normal')
        sizes(doc.width(), doc.height(), detail)
        work = self._finish_work(doc, session, params)
        if not work:
            raise ValueError('The area lies outside where the goal sits on the canvas: nothing to finish.')
        if detail != 'normal':
            # The area's own pixels, not its bounding box (review finding: a thin diagonal part was refused by its box).
            coverage_of = self._finish_limit(doc, session, params)[0]
            share = sum(float(coverage_of(*t).sum()) if coverage_of else t[2] * t[3] for t in work) / float(doc.width() * doc.height())
            if share > FINE_SHARE:
                raise ValueError('Nothing was painted: fine detail paints at most %d%% of the canvas a call (this area is %d%%). '
                                 'For a larger area call refine_to_goal with it (the artist\u2019s Paint only here area by default, or a box): '
                                 'it refines the area square by square, fine then finer, where it still differs from the goal.'
                                 % (round(FINE_SHARE * 100), round(share * 100)))
        try:
            import cv2  # noqa: F401
        except Exception as error:
            raise ValueError('Finish needs OpenCV and numpy in Krita’s Python (the Creative Agent’s packages; '
                             'reinstall them from the panel): ' + str(error)) from None
        self._craft_check_rgba(doc, 'Finish')
        self._craft_validate_create(doc, session, {'name': params['name'], 'type': 'group', **{k: params[k] for k in ('stage_id', 'panel') if k in params}})

    def _finish_work(self, doc, session, params, limit=None):
        """The tiles to finish: the area's bounds where the goal sits, square by square."""
        width, height = doc.width(), doc.height()
        bounds = (limit or self._finish_limit(doc, session, params))[1]
        area = intersect(bounds, placed(params['goal']))
        area = area and intersect(area, [0, 0, width, height])
        return tiles(area, width, height) if area else []

    def _finish_apply(self, doc, session, params, result):
        from .qt_compat import QCoreApplication
        from . import canvas_projection
        started = time.monotonic()
        width, height = doc.width(), doc.height()
        size = sizes(width, height, params.get('detail', 'normal'))
        limit = self._finish_limit(doc, session, params)
        work = self._finish_work(doc, session, params, limit)
        coverage_of = limit[0]
        spec = params['goal']
        # Where the goal is, on the canvas only: a placement rounded or reaching past an edge seeds nothing off it.
        target = intersect(placed(spec), [0, 0, width, height])
        self._creative_progress(session, 'painting', 'Finish: reading the goal image')
        goal = GoalOnCanvas(read_goal(spec), spec)
        group = self._craft_create(doc, session, {'name': params['name'], 'type': 'group', **{k: params[k] for k in ('stage_id', 'panel') if k in params}})
        node = self._creative_node(doc, group['layer_id'])
        # One clean read, before any Finish layer has pixels: the composite below the group over all the work, padded.
        union = bounding([grow(tile, size['canvas_pad'], width, height) for tile in work])
        self._creative_progress(session, 'painting', 'Finish: reading the canvas')
        canvas = self._accents_clean_reads(doc, session, node, [union])[tuple(union)]
        # The goal on the canvas under all the work, resampled in one piece: OpenCV's fixed-point warp rounds a pixel's
        # position by where its rect starts, so tiles resampled apart differed by a level here and there (and their strokes
        # with them).
        goal_union = bounding([grow(tile, size['goal_pad'], width, height) for tile in work])
        goal_pixels = goal.rect(goal_union)
        layers = {}
        for label in ('blend', 'strokes'):                         # the strokes above the blend
            layer = doc.createNode('%s · %s' % (params['name'], label), 'paintlayer')
            children = node.childNodes()
            if layer is None or not node.addChildNode(layer, children[-1] if children else None):
                raise RuntimeError('Krita could not add the finish layer.')
            session['layers'].add(layer.uniqueId().toString())
            layer.setBlendingMode('normal')                       # the blend is baked: nothing blends inside the group
            layers[label] = layer
        told = [time.monotonic()]
        stopped = False
        done = {'tiles': 0, 'blend_tiles': 0, 'stroke_tiles': 0, 'strokes': 0, 'soft': 0.0}

        def breathe(count=None, tile_number=None):
            # Krita's window, the panel and its Stop are served; the Now card hears which tile is painting.
            if time.monotonic() - told[0] < RESPONSIVE_SECONDS:
                return
            told[0] = time.monotonic()
            QCoreApplication.processEvents()
            self._creative_progress(session, 'painting', 'Finish: square %d of %d%s' % (
                done['tiles'] + 1, len(work), ' · %s strokes' % format(done['strokes'] + (count or 0), ',') if done['strokes'] or count else ''))

        for tile in work:
            if stop_requested.is_set():
                stopped = True
                break
            breathe()
            x, y, w, h = tile
            coverage = coverage_of(x, y, w, h) if coverage_of else None
            if coverage is not None and not coverage.any():
                done['tiles'] += 1
                continue
            goal_rect = grow(tile, size['goal_pad'], width, height)
            canvas_rect = grow(tile, size['canvas_pad'], width, height)
            own = crop(canvas, union, canvas_rect)
            blend, strokes, report = finish_tile(tile, own, canvas_rect, crop(goal_pixels, goal_union, goal_rect), goal_rect, target, width, height, size,
                                                 coverage, lambda count: breathe(count))
            for label, pixels in (('blend', blend), ('strokes', strokes)):
                if pixels is None:
                    continue
                if layers[label].setPixelData(pixels, x, y, w, h) is False:
                    raise RuntimeError('Krita rejected the finish layer pixels.')
                done[KEYS[label]] += 1
            if blend is not None or strokes is not None:
                canvas_projection.pixels_written(doc, tile)
            done['tiles'] += 1; done['strokes'] += report['strokes']; done['soft'] += report['soft'] * w * h
        area = sum(t[2] * t[3] for t in work[:done['tiles']]) or 1
        painted = done['blend_tiles'] or done['stroke_tiles']
        if not painted:
            # Nothing was painted (a Stop before the first square, or no square showed anything): no empty group is left.
            for layer in list(layers.values()) + [node]:
                session['layers'].discard(layer.uniqueId().toString())
            node.remove()
        for label, layer in layers.items():                       # a layer that got nothing is not left empty in the group
            if painted and not done[KEYS[label]]:
                session['layers'].discard(layer.uniqueId().toString())
                layer.remove()
        # whole: the whole picture at the default detail (the companion's "the whole picture is finished", from the passes).
        whole = size['detail'] == 'normal' and not any(params.get(k) for k in ('box', 'selection', 'inside_shape'))
        out = dict(group, finish={'detail': size['detail'], 'whole': whole, 'tiles': done['tiles'], 'of_tiles': len(work), 'blend_tiles': done['blend_tiles'],
                                  'stroke_tiles': done['stroke_tiles'], 'strokes': done['strokes'],
                                  'soft_share': round(done['soft'] / area, 3), 'ms': int((time.monotonic() - started) * 1000)},
                   layers={label: layer.uniqueId().toString() for label, layer in layers.items()
                           if done[KEYS[label]]})
        if not painted:
            out['contribution_removed'] = True
        if stopped:
            out.update(stopped='Stopped by the artist: the finish is kept where it was painted (%d of %d squares).' % (done['tiles'], len(work)),
                       stopped_after_tiles=done['tiles'])
        return out
