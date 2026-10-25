# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Full-size checks for an area (openspec finish-stage goals 7-8, the artist 2026-10-24: "yess we need both"; "i want the
end result where our accents and finishes make it move eventually to the final").

On New Moscow every check looked at a reduced view: goal likeness's 64-cell grid (94 canvas px a cell), the accent
finder's residual on the reference decode against the ~1024 px look, the painter's and Luna's views. There the canvas
and the goal looked the same (likeness ΔE 0.4), paint_accents found nothing, and yet at full size the church was blobby
beside the goal: Finish's strokes were 5-9 px wide, its windows and edges 2-4 px. Here the canvas and the goal are
compared at full canvas resolution, the goal mapped through its placement (finish_pass.GoalOnCanvas: the sharpened goal
when there is one), read from the chat folder as paint_finish reads it.

- area_likeness: how far an area is from the goal at full size: `colour`, the mean CIE76 ΔE of both blurred over BLUR
  canvas px (texture under a pixel or two does not count, a blob where the goal has a window does), and `edges`, the
  mean difference of their gradient magnitudes over EDGE_BLUR (crispness counts). Worked in TILE squares, each read
  padded by the blurs' reach, so any area is measured at full size in bounded memory. Measured on the church (550 x 750
  of the 6000 px canvas, the lead's fine try-out): colour 4.95 -> 2.44, edges 3.59 -> 2.43, where the 64-cell grid said
  0.38 -> 0.17.
- area_accents: paint_accents' finder (accent_find.find) on the goal's and the canvas's pixels of the area at full size,
  so after a fine Finish the remaining crisp lights, darks and lines are found at their real size. One piece of at most
  AREA_PIXELS (reduced by area-averaging above that: the finder's scales are shares of the crop, so a larger area keeps
  its standouts); the accents come back in canvas pixels.
- refine_map: the whole canvas (or an area) in CELL squares ranked by what is left to do, colour + edges (Refine to the
  goal, goal 8, picks its worst regions from it). With `soft`, each cell also gets `soft`: the mean of the Finish's own soft
  mask (finish_pass.soft_mask) over it, 0 (all structure) to 1 (sky, mist, water), so Refine gives a mostly soft region the
  fine pass only (the artist, 2026-10-25). About 1 s on the whole 6000 x 4500 canvas; Refine asks once a call.

Read-only: the composite is read with the agent's guide lines hidden (as the accents read it) and nothing is written.
"""
import math
import time
import numpy as np

AREA_PIXELS = 4_000_000          # the accent finder's area at most (as creative_reference.TRACE_PIXELS), reduced above it
BLUR = 2.0                       # colour compared through this blur (canvas px at finish_pass.SCALE_SIDE)
EDGE_BLUR = 1.0                  # edges: gradient magnitude through this blur
TILE = 1024                      # measured square by square, each padded by the blurs' reach
FIELDS = ('goal', 'rect')
ACCENT_FIELDS = FIELDS + ('kinds', 'strength', 'max_accents')
MAP_FIELDS = ('goal', 'rect', 'cell', 'soft')


def _finish():
    from . import finish_pass
    return finish_pass


def blurs(width, height):
    """BLUR and EDGE_BLUR on this canvas: scaled with its long side as finish_pass's sizes are, never below a pixel."""
    k = max(width, height) / _finish().SCALE_SIDE
    return max(1.0, BLUR * k), max(0.7, EDGE_BLUR * k)


def pad_for(width, height):
    colour, edge = blurs(width, height)
    return int(math.ceil(3 * max(colour, edge))) + 2


def _lab(bgr, sigma):
    import cv2
    image = bgr.astype(np.float32) / 255
    return cv2.cvtColor(cv2.GaussianBlur(image, (0, 0), sigma), cv2.COLOR_BGR2LAB)


def _gradient(bgr, sigma):
    import cv2
    grey = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), sigma)
    return np.hypot(cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)) / 8


def difference_maps(canvas_bgr, goal_bgr, sigmas):
    """Per pixel: colour (ΔE of the blurred pair) and edges (|gradient magnitude difference|), float32."""
    colour = np.linalg.norm(_lab(canvas_bgr, sigmas[0]) - _lab(goal_bgr, sigmas[0]), axis=2)
    edges = np.abs(_gradient(canvas_bgr, sigmas[1]) - _gradient(goal_bgr, sigmas[1]))
    return colour, edges


def squares(rect, side):
    """`rect` [x, y, w, h] in squares of `side` on one grid from the canvas origin, clipped to it."""
    x, y, w, h = rect
    out = []
    for top in range((y // side) * side, y + h, side):
        for left in range((x // side) * side, x + w, side):
            l, t = max(x, left), max(y, top)
            r, b = min(x + w, left + side), min(y + h, top + side)
            if r > l and b > t:
                out.append([l, t, r - l, b - t])
    return out


def measure(read_canvas, read_goal, rect, width, height, cell=None, tile=None, breathe=None, soft=False):
    """The area's full-size difference: {'colour', 'edges', 'pixels'} and, with `cell`, every cell's own ([x, y, w, h],
    colour, edges; with `soft` its goal's soft share too). read_canvas(rect) -> BGR(A) uint8, read_goal(rect) -> BGR uint8,
    both of canvas rect [x, y, w, h].
    Square by square (TILE, a whole number of cells), each read padded by the blurs' reach, so the sums do not depend on
    the squares."""
    finish = _finish()
    sigmas, pad = blurs(width, height), pad_for(width, height)
    side = tile or TILE
    if cell:
        side = max(cell, (side // cell) * cell)
    sums = {'colour': 0.0, 'edges': 0.0, 'pixels': 0}
    cells, softs = {}, {}
    sizes = finish.sizes(width, height) if cell and soft else None
    for square in squares(rect, side):
        padded = finish.grow(square, pad, width, height)
        canvas = read_canvas(padded)[..., :3]
        goal = read_goal(padded)
        colour, edges = difference_maps(np.ascontiguousarray(canvas), goal, sigmas)
        inner = (slice(square[1] - padded[1], square[1] - padded[1] + square[3]), slice(square[0] - padded[0], square[0] - padded[0] + square[2]))
        colour, edges = colour[inner], edges[inner]
        sums['colour'] += float(colour.sum()); sums['edges'] += float(edges.sum()); sums['pixels'] += colour.size
        if cell:
            for part in squares(square, cell):
                key = (part[0] // cell, part[1] // cell)
                view = (slice(part[1] - square[1], part[1] - square[1] + part[3]), slice(part[0] - square[0], part[0] - square[0] + part[2]))
                entry = cells.setdefault(key, [0.0, 0.0, 0, part])
                entry[0] += float(colour[view].sum()); entry[1] += float(edges[view].sum()); entry[2] += colour[view].size
            if sizes:
                # The Finish's soft mask, read with its own (wider) pad so it equals the whole canvas's mask here.
                wide = finish.grow(square, sizes['mask_pad'], width, height)
                mask = finish.soft_mask(read_goal(wide).astype(np.float32) / 255, sizes)
                mask = mask[square[1] - wide[1]:square[1] - wide[1] + square[3], square[0] - wide[0]:square[0] - wide[0] + square[2]]
                for part in squares(square, cell):
                    key = (part[0] // cell, part[1] // cell)
                    view = mask[part[1] - square[1]:part[1] - square[1] + part[3], part[0] - square[0]:part[0] - square[0] + part[2]]
                    entry = softs.setdefault(key, [0.0, 0])
                    entry[0] += float(view.sum()); entry[1] += view.size
        if breathe is not None:
            breathe()
    n = max(1, sums['pixels'])
    out = {'colour': round(sums['colour'] / n, 3), 'edges': round(sums['edges'] / n, 3), 'pixels': sums['pixels']}
    if cell:
        out['cells'] = [dict({'rect': entry[3], 'colour': round(entry[0] / entry[2], 3), 'edges': round(entry[1] / entry[2], 3),
                              'score': round((entry[0] + entry[1]) / entry[2], 3)},
                             **({'soft': round(softs[key][0] / max(1, softs[key][1]), 3)} if key in softs else {}))
                        for key, entry in cells.items()]
        out['cells'].sort(key=lambda c: -c['score'])
    return out


def find_on(goal_bgr, canvas_bgr, kinds, strength, max_accents):
    """accent_find.find on the goal's and the canvas's pixels of one area (same size, BGR uint8): accents in its pixels."""
    import cv2
    from . import accent_find
    h, w = goal_bgr.shape[:2]
    rgba = np.dstack([cv2.cvtColor(goal_bgr, cv2.COLOR_BGR2RGB), np.full((h, w), 255, np.uint8)])
    seen = cv2.cvtColor(np.ascontiguousarray(canvas_bgr[..., :3]), cv2.COLOR_BGR2RGB)
    return accent_find.find(rgba, [0, 0, w, h], kinds=kinds, strength=strength, max_accents=max_accents, canvas=seen, target=[0, 0, w, h])


def to_canvas(accents, rect, scale):
    """Accents found in an area's pixels (reduced by `scale`) in canvas pixels."""
    x0, y0 = rect[0], rect[1]
    out = []
    for accent in accents:
        item = dict(accent, x=round(x0 + accent['x'] / scale, 2), y=round(y0 + accent['y'] / scale, 2), size=round(accent['size'] / scale, 2))
        if 'length' in item:
            item['length'] = round(item['length'] / scale, 2)
        if 'points' in item:
            item['points'] = [[round(x0 + px / scale, 2), round(y0 + py / scale, 2)] for px, py in item['points']]
        out.append(item)
    return out


class AreaCompare:
    """The plugin side of the full-size checks: read-only session operations."""

    def _area_goal(self, doc, session, spec):
        """The goal on the canvas (finish_pass.GoalOnCanvas), decoded once a goal file and placement: kept on the session."""
        finish = _finish()
        finish.check_goal(spec, session.get('output'), doc.width(), doc.height())
        key = (spec['sha256'], tuple(spec['size']), tuple(spec['source']), tuple(spec['target']))
        cached = session.get('area_goal')
        if not cached or cached[0] != key:
            session['area_goal'] = cached = (key, finish.GoalOnCanvas(finish.read_goal(spec), spec))
        return cached[1]

    def _area_rect(self, doc, spec, rect):
        """The area: `rect` (default the canvas) where the goal sits on the canvas, whole pixels."""
        from .geometry_data import bounds as checked_bounds
        finish = _finish()
        width, height = doc.width(), doc.height()
        if rect is None:
            rect = [0, 0, width, height]
        checked_bounds(rect, width, height)
        area = finish.intersect([int(v) for v in rect], finish.placed(spec))
        area = area and finish.intersect(area, [0, 0, width, height])
        if not area:
            raise ValueError('The area lies outside where the goal sits on the canvas.')
        return area

    def _area_reader(self, doc, session):
        """read(rect) -> the painting's composite there (BGRA uint8), the agent's guide lines left out. Returns (read, done)."""
        from . import canvas_projection
        guides = self._guide_group(doc, session=session)
        hidden = guides is not None and guides.visible()
        if hidden:
            guides.setVisible(False)
        touched = []

        def read(rect):
            canvas_projection.refresh(doc, list(rect)); doc.waitForDone()
            touched.append(list(rect))
            return np.frombuffer(bytes(doc.rootNode().projectionPixelData(*rect)), np.uint8).reshape(rect[3], rect[2], 4)

        def done():
            if hidden:
                guides.setVisible(True)
                for rect in touched:
                    canvas_projection.refresh(doc, rect)
        return read, done

    def _area_operation(self, doc, session, operation, params):
        from .creative_validation import fields
        started = time.monotonic()
        fields(params, {'area_likeness': FIELDS, 'area_accents': ACCENT_FIELDS, 'refine_map': MAP_FIELDS}[operation], ('goal',))
        spec = params['goal']
        goal = self._area_goal(doc, session, spec)
        rect = self._area_rect(doc, spec, params.get('rect'))
        width, height = doc.width(), doc.height()
        read, done = self._area_reader(doc, session)
        try:
            if operation == 'area_accents':
                x, y, w, h = rect
                scale = min(1.0, math.sqrt(AREA_PIXELS / float(w * h)))
                canvas, pixels = read(rect)[..., :3], goal.rect(rect)
                if scale < 1:
                    import cv2
                    size = (max(8, int(round(w * scale))), max(8, int(round(h * scale))))
                    canvas = cv2.resize(np.ascontiguousarray(canvas), size, interpolation=cv2.INTER_AREA)
                    pixels = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
                    scale = size[0] / float(w)
                found = find_on(pixels, canvas, params.get('kinds', ['lights', 'glints', 'darks', 'lines']), params.get('strength', 'medium'),
                                params.get('max_accents', 200))
                return {'status': 'ok', 'rect': rect, 'scale': round(scale, 4), 'accents': to_canvas(found['accents'], rect, scale),
                        'found': found['found'], 'ms': int((time.monotonic() - started) * 1000)}
            cell = params.get('cell')
            if cell is not None and (isinstance(cell, bool) or not isinstance(cell, int) or not 16 <= cell <= 4096):
                raise ValueError('cell is 16-4096 canvas pixels.')
            from .qt_compat import QCoreApplication
            out = measure(read, goal.rect, rect, width, height, cell=cell if operation == 'refine_map' else None,
                          breathe=QCoreApplication.processEvents, soft=operation == 'refine_map' and params.get('soft') is True)
            return dict(out, status='ok', rect=rect, blur=[round(v, 2) for v in blurs(width, height)], ms=int((time.monotonic() - started) * 1000))
        finally:
            done()
