"""Flat colours from line art with Krita's colorize mask (lazy brush), instead of strokes.

Runs inside the creative operation journal (creative_tools.py). The line art is only
read: its pixels are copied into a helper layer the agent owns, directly below it,
and the colorize mask goes on that copy. Each seed is a small key stroke of its
colour; Krita grows the colours up to the lines. The computed colours are then
copied into a new flat layer the agent owns (a clip base by default, so shading can
clip to it), and the helper is hidden. It keeps its mask and key strokes, so the
artist can open it in Krita and refine the flats by hand.

To read the colours without the lines, the helper's pixels are cleared for a moment
and put back: Krita keeps the computed colours until the mask is updated again.
"""
from krita import ManagedColor
from .qt_compat import QCoreApplication, QElapsedTimer
from .qt_compat import QColor
from .creative_validation import color as hex_colour, fields, numeric, text

COLORIZE_FIELDS = ('line_layer', 'seeds', 'name', 'clip_base', 'edge_detection', 'cleanup',
                   'stage_id', 'region', 'expected_revision')
SEED_FIELDS = ('x', 'y', 'color', 'radius')
SEED_LIMIT = 48
COLOUR_LIMIT = 24
STRIP = 256
WAIT_MS = 30000


def seed_dot(cx, cy, radius, width, height):
    """An 8-bit alpha disc at (cx, cy), cropped to the canvas, as (bytes, (x, y, w, h))."""
    x0, y0 = max(cx - radius, 0), max(cy - radius, 0)
    x1, y1 = min(cx + radius, width - 1), min(cy + radius, height - 1)
    return bytes(255 if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius else 0
                 for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)), (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def seed_colours(seeds):
    """Distinct seed colours in order, and the index of 'transparent' (-1 when absent)."""
    colours = []
    for seed in seeds:
        wanted = seed['color'].lower()
        if wanted not in colours:
            colours.append(wanted)
    return colours, (colours.index('transparent') if 'transparent' in colours else -1)


def stand_in(colours):
    """A colour no seed uses, keyed for the transparent region."""
    used = {c for c in colours if c != 'transparent'}
    value = 1
    while '#%06x' % value in used:
        value += 1
    return '#%06x' % value


class ColorizeCraft:
    def _colorize_validate(self, doc, session, params):
        fields(params, COLORIZE_FIELDS, ('line_layer', 'seeds'))
        self._craft_check_rgba(doc, 'colorize_flats')
        self._creative_node(doc, text(params['line_layer'], 'line_layer', 200))
        seeds = params['seeds']
        if not isinstance(seeds, list) or not 2 <= len(seeds) <= SEED_LIMIT:
            raise ValueError('Give 2-%d seeds, one or more inside each region to colour.' % SEED_LIMIT)
        for index, seed in enumerate(seeds):
            label = 'Seed %d: ' % (index + 1)
            try:
                fields(seed, SEED_FIELDS, ('x', 'y', 'color'))
                numeric(seed['x'], 'x', 0, doc.width() - 1)
                numeric(seed['y'], 'y', 0, doc.height() - 1)
                if seed['color'] != 'transparent':
                    hex_colour(seed['color'])
                if 'radius' in seed and (not isinstance(seed['radius'], int) or not 1 <= seed['radius'] <= 24):
                    raise ValueError('radius must be a whole number of pixels from 1 to 24')
            except ValueError as error:
                raise ValueError(label + str(error)) from None
        colours, transparent = seed_colours(seeds)
        if len(colours) > COLOUR_LIMIT:
            raise ValueError('Use at most %d different seed colours.' % COLOUR_LIMIT)
        if len(colours) - (transparent >= 0) < 1:
            raise ValueError('Give at least one seed with a colour.')
        for key in ('clip_base', 'edge_detection'):
            if key in params and not isinstance(params[key], bool):
                raise ValueError(key + ' must be true or false')
        if 'cleanup' in params:
            numeric(params['cleanup'], 'cleanup', 0, 1)
        if 'name' in params:
            text(params['name'], 'name', 120)

    def _colorize_strips(self, width, height):
        for y in range(0, height, STRIP):
            yield y, min(STRIP, height - y)

    def _colorize_apply(self, doc, session, params):
        line = self._creative_node(doc, params['line_layer'])
        width, height = doc.width(), doc.height()
        name = params.get('name') or 'Flats'
        self._creative_progress(session, 'painting', 'Colorizing flats')
        doc.waitForDone()
        line_pixels = [(y, rows, bytes(line.projectionPixelData(0, y, width, rows)))
                       for y, rows in self._colorize_strips(width, height)]

        helper = doc.createNode('Colorize helper · ' + name, 'paintlayer')
        if helper is None or not self._craft_insert_below(doc, line, helper):
            raise RuntimeError('Krita could not add the colorize helper layer.')
        helper_id = helper.uniqueId().toString()
        session['layers'].add(helper_id)
        for y, rows, data in line_pixels:
            helper.setPixelData(data, 0, y, width, rows)

        mask = doc.createColorizeMask('Colorize')
        if mask is None or not helper.addChildNode(mask, None):
            raise RuntimeError('Krita could not add the colorize mask.')
        colours, transparent = seed_colours(params['seeds'])
        keyed = [stand_in(colours) if c == 'transparent' else c for c in colours]
        managed = [ManagedColor.fromQColor(QColor(c)) for c in keyed]
        mask.initializeKeyStrokeColors(managed, transparent)
        for seed in params['seeds']:
            dot, rect = seed_dot(round(seed['x']), round(seed['y']), seed.get('radius', 3), width, height)
            colour = managed[colours.index(seed['color'].lower())]
            if mask.setKeyStrokePixelData(dot, colour, *rect) is False:
                raise RuntimeError('Krita rejected a seed.')
        mask.setUseEdgeDetection(params.get('edge_detection', False))
        mask.setCleanUpAmount(float(params.get('cleanup', 0.7)))
        mask.setLimitToDeviceBounds(False)
        mask.updateMask(True)
        self._colorize_wait(doc, helper, line_pixels, width)
        mask.setEditKeyStrokes(False)
        mask.setShowOutput(True)

        flats = self._colorize_read(doc, helper, line_pixels, width)
        result = self._craft_create(doc, session, {'name': name, 'type': 'paint', 'clip_base': params.get('clip_base', True),
                                                   'stage_id': params.get('stage_id'), '_below': line})
        target = self._creative_node(doc, result['layer_id'])
        covered = 0
        for (y, rows, _line), data in zip(line_pixels, flats):
            if target.setPixelData(data, 0, y, width, rows) is False:
                raise RuntimeError('Krita rejected the flat colours.')
            covered += sum(1 for alpha in data[3::4] if alpha)
        helper.setVisible(False)
        doc.setActiveNode(target)
        doc.refreshProjection()
        result.update(helper_layer_id=helper_id, colors=len(colours) - (transparent >= 0), filled_pixels=covered)
        return result

    def _colorize_wait(self, doc, helper, line_pixels, width):
        """Wait for Krita to finish the mask.

        Where the line art has transparent pixels, colour shows through them once the
        mask is done, so wait for that. Opaque line art hides the colours; there the
        image being idle is the only signal, and _colorize_read checks the result.
        """
        line_open = sum(data[3::4].count(0) for _y, _rows, data in line_pixels)
        timer = QElapsedTimer()
        timer.start()
        while True:
            QCoreApplication.processEvents()
            doc.waitForDone()
            if line_open == 0:
                return
            doc.refreshProjection()
            open_now = sum(bytes(helper.projectionPixelData(0, y, width, rows))[3::4].count(0)
                           for y, rows, _data in line_pixels)
            if open_now < line_open:
                return
            if timer.elapsed() > WAIT_MS:
                raise RuntimeError('Krita did not finish colorizing in time. Check that each region has a seed.')

    def _colorize_read(self, doc, helper, line_pixels, width):
        """The computed colours without the lines: clear the helper, read, put the lines back."""
        for y, rows, data in line_pixels:
            helper.setPixelData(bytes(len(data)), 0, y, width, rows)
        doc.refreshProjection()
        doc.waitForDone()
        flats = [bytes(helper.projectionPixelData(0, y, width, rows)) for y, rows, _data in line_pixels]
        for y, rows, data in line_pixels:
            helper.setPixelData(data, 0, y, width, rows)
        if not any(any(strip[3::4]) for strip in flats):
            raise RuntimeError('Krita computed no colours. Check that the seeds sit inside closed regions.')
        return flats
