# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Krita's own painting tools as agent operations (krita-fork 5.3, the fork only: no stock fallback).

The fork's libkis runs the tools the artist knows as functions on a layer, each one a checked call that returns a bool:
`Node.fill` (the bucket), `Node.encloseAndFill`, `Node.gradient` and `Node.smartPatch`. Here they are four operations in
the style of `fill_region` and `stamp`: a reversible pass on a NEW agent layer.

  bucket_fill       Node.fill: a region found from a point, flooded with a colour (contiguous, similar colours, or all).
  enclose_and_fill  Node.encloseAndFill: the regions inside a drawn area, flooded (the tool's "fill what is inside").
  krita_gradient    Node.gradient: a gradient between two points (every shape Krita has, repeat, dither, blending).
  smart_patch       Node.smartPatch: an area re-made from the paint around it (PatchMatch), at most 512 x 512 pixels.

Every call works on the layer made for it, so rejecting the pass removes it and nothing of the artist's is touched. The fill
tools find their regions on the painting as shown (`sample` "all", the default here: the new layer is empty, so "layer" would
fill everything); smart patch has nothing to copy from on an empty layer, so it first copies the painting's pixels around the
area into the new layer, patches, then clears everything outside the area: the layer holds the repair and nothing else. With
`layer_id` (an agent paint layer) it patches an edited copy of that layer instead, original hidden, as fill_region does.

Checked before anything is queued: the fork's documented option keys and ranges (creative_validation.tool_options), points
inside the canvas and its margin, a smart patch area within the fork's cap (with its numbers), saved selections, the gradient
resource. The area the call may reach is the saved selection or selection steps (`selection` / `area`) cut by the stage
`region`'s mask; with neither it is explicitly the whole canvas, so the artist's own selection never limits an agent call.

The layer, the call (and a smart patch's pixel writes) are one undo step (an agent move). The fork only warns and returns false
when it refuses a call, so a refusal is a definite rejected pass with its layer removed; an error from Krita is the same; the
artist's Undo during the call is waited out and reported as a partial pass with nothing recorded (`_creative_ended_by_krita`,
the stroke job's C1 rule). The result's `tool_call` says which call ran, what it returned and what it did.
"""
import contextlib

import krita as krita_module
from krita import Krita, Selection
from .creative_validation import canvas_pixel, canvas_point, check_patch_area, color as hex_colour, fields, numeric, text, tool_options, whole_number
from .script_steps import one_step
from . import canvas_projection

OPERATIONS = ('bucket_fill', 'enclose_and_fill', 'krita_gradient', 'smart_patch')
LAYER_SETTINGS = ('blend_mode', 'opacity', 'clip_to', 'clip_base')
COMMON = ('name', 'selection', 'area', 'region', 'stage_id', 'panel', 'expected_revision', 'options')
FIELDS = {
    'bucket_fill': COMMON + LAYER_SETTINGS + ('x', 'y', 'color'),
    'enclose_and_fill': COMMON + LAYER_SETTINGS + ('enclose_selection', 'enclose_area', 'color'),
    'krita_gradient': COMMON + LAYER_SETTINGS + ('start', 'end'),
    'smart_patch': COMMON + ('layer_id', 'context'),
}
REQUIRED = {'bucket_fill': ('name', 'x', 'y', 'color'), 'enclose_and_fill': ('name', 'color'),
            'krita_gradient': ('name', 'start', 'end', 'options'), 'smart_patch': ('name',)}
# Krita's method on the Node class that must exist (the fork), the options kind, and the undo step's title.
METHODS = {'bucket_fill': ('fill', 'fill', 'Bucket fill'), 'enclose_and_fill': ('encloseAndFill', 'enclose', 'Enclose and fill'),
           'krita_gradient': ('gradient', 'gradient', 'Gradient'), 'smart_patch': ('smartPatch', 'patch', 'Smart patch')}
PASS_TITLES = {'bucket_fill': 'Bucket fill', 'enclose_and_fill': 'Enclose and fill', 'krita_gradient': 'Gradient', 'smart_patch': 'Smart patch'}
PATCH_CONTEXT = 96          # px of the painting copied around the area for a smart patch to search
MAX_PATCH_CONTEXT = 512


def tool_functions_available():
    """True in our Krita: the Node class has the tool functions (asked of the class, once per call)."""
    node_class = getattr(krita_module, 'Node', None)
    return all(hasattr(node_class, method) for method, _kind, _title in METHODS.values())


class ToolCraft:
    # ----- validation ------------------------------------------------------------------------------------------------------
    def _tool_layer_params(self, params):
        layer = {key: params[key] for key in ('name', 'stage_id', 'panel') + LAYER_SETTINGS if key in params}
        layer['type'] = 'paint'
        return layer

    def _tool_validate_area(self, doc, session, params, operation):
        areas = [key for key in ('selection', 'area') if key in params]
        if operation == 'smart_patch':
            if len(areas) != 1:
                raise ValueError('Give the area to patch: selection (a saved name) or area (selection steps).')
        elif len(areas) > 1:
            raise ValueError('Give at most one of selection (a saved name) or area (selection steps) to limit the call.')
        if 'selection' in params:
            self._region_saved_path(session, params['selection'], must_exist=True)
        elif 'area' in params:
            self._region_validate_steps(doc, session, params['area'])

    def _tool_validate(self, doc, session, operation, params):
        method, kind, title = METHODS[operation]
        fields(params, FIELDS[operation], REQUIRED[operation])
        if not tool_functions_available():
            raise ValueError('%s needs our Krita (the fork): this Krita has no Node.%s.' % (operation, method))
        self._craft_check_rgba(doc, 'A ' + title.lower())
        text(params['name'], 'name', 120)
        self._tool_validate_area(doc, session, params, operation)
        if 'region' in params:
            self._creative_region(params['region'], doc.width(), doc.height())
        options = tool_options(kind, params.get('options'))
        width, height = doc.width(), doc.height()
        if operation == 'bucket_fill':
            canvas_pixel(params['x'], params['y'], 'x', 'y', width, height)
            hex_colour(params['color'])
        elif operation == 'enclose_and_fill':
            enclosing = [key for key in ('enclose_selection', 'enclose_area') if key in params]
            if len(enclosing) != 1:
                raise ValueError('Give the enclosing area: enclose_selection (a saved name) or enclose_area (selection steps).')
            if 'enclose_selection' in params:
                self._region_saved_path(session, params['enclose_selection'], must_exist=True)
            else:
                self._region_validate_steps(doc, session, params['enclose_area'])
            hex_colour(params['color'])
        elif operation == 'krita_gradient':
            margin = max(width, height)         # a gradient may start or end off the canvas, within a canvas length of it
            start, end = (canvas_point(params[key], key, width, height, margin) for key in ('start', 'end'))
            if start == end:
                raise ValueError('start and end must be different points')
            name = options.get('gradient')
            if name is not None and name not in Krita.instance().resources('gradient'):
                raise ValueError('Unknown gradient "%s". krita_capabilities lists the installed gradients.' % name)
        else:
            if 'context' in params:
                whole_number(params['context'], 'context', 8, MAX_PATCH_CONTEXT)
            if 'layer_id' in params:
                node = self._creative_node(doc, text(params['layer_id'], 'layer_id', 200))
                if not self._craft_owned(session, params['layer_id']):
                    raise ValueError('Only layers the agent created can be patched. Leave out layer_id to patch a copy of the painting.')
                if node.type() != 'paintlayer' or node.locked():
                    raise ValueError('Patch an unlocked paint layer, or leave out layer_id.')
        if operation != 'smart_patch':
            self._craft_validate_create(doc, session, self._tool_layer_params(params))
        else:
            self._craft_validate_create(doc, session, dict({key: params[key] for key in ('name', 'stage_id', 'panel') if key in params}, type='paint'))

    # ----- the area a call may reach -------------------------------------------------------------------------------------------
    def _tool_limit(self, doc, session, params):
        """(Selection, rect, base): what the call may change, as the selection to hand Krita, its bounding rect inside the
        canvas, and the painter's own area selection (None without one). The saved selection or steps cut by the stage
        region's mask; neither: the whole canvas, as an explicit selection. rect None when nothing is selected."""
        width, height = doc.width(), doc.height()
        base = None
        if 'selection' in params:
            base = self._region_load(session, params['selection'])
        elif 'area' in params:
            base = self._region_build(doc, session, params['area'])
        stage = None
        if params.get('region'):
            import numpy
            from .stage_mask import mask as stage_mask
            rx, ry, rw, rh = params['region']
            stage = ((rx, ry, rw, rh), stage_mask(params['region'], width, height).astype(numpy.uint16))
        if base is None and stage is None:
            everything = Selection()
            everything.select(0, 0, width, height, 255)
            return everything, (0, 0, width, height), None
        if base is None:
            (rx, ry, rw, rh), grid = stage
            clip = Selection()
            clip.setPixelData(grid.astype('uint8').tobytes(), rx, ry, rw, rh)
            return clip, (rx, ry, rw, rh), None
        extent = self._region_bounds(doc, base)
        if extent is None:
            return None, None, base
        rect = extent[0]
        if stage is None:
            return base, rect, base
        import numpy
        (rx, ry, rw, rh), grid = stage
        left, top, right, bottom = max(rect[0], rx), max(rect[1], ry), min(rect[0] + rect[2], rx + rw), min(rect[1] + rect[3], ry + rh)
        if right <= left or bottom <= top:
            return None, None, base
        w, h = right - left, bottom - top
        area = numpy.frombuffer(bytes(base.pixelData(left, top, w, h)), numpy.uint8).reshape(h, w).astype(numpy.uint16)
        both = (area * grid[top - ry:bottom - ry, left - rx:right - rx] // 255).astype(numpy.uint8)
        if not both.any():
            return None, None, base
        clip = Selection()
        clip.setPixelData(both.tobytes(), left, top, w, h)
        return clip, (left, top, w, h), base

    # ----- one call ---------------------------------------------------------------------------------------------------------
    def _tool_reject(self, doc, session, result, node, message, called=None):
        """The fork refused (or failed): the layer made for the call goes, and the pass is a definite, rejected one."""
        self._creative_discard_layer(doc, session, result, node)
        for key in ('layer_id', 'group_id', 'clip', 'clip_group_id', 'layer_type', 'source_layer_id', 'source_prior'):
            result.pop(key, None)
        result.update(status='rejected', error_code='validation_rejected', error=message)
        if called:
            result['tool_call'] = called
        return result

    @staticmethod
    def _tool_closed(error):
        """The document was closed during a call: its wrapper is gone (PyQt says the C/C++ object has been deleted)."""
        if isinstance(error, RuntimeError) and 'deleted' in str(error):
            return RuntimeError('The document was closed during the call (%s); nothing more was done. Inspect the painting.' % error)
        return None

    def _tool_kept_out(self, doc, result):
        """The protected features Krita kept the last call out of (Document.lastKeptOut, protection 6.5), when this Krita has it."""
        names = []
        if hasattr(doc, 'lastKeptOut'):
            try:
                names = [str(name) for name in doc.lastKeptOut()]
            except Exception:
                names = []
        if names:
            result['kept_out'] = names
        return names

    def _tool_run(self, doc, session, result, node, before, call, what, changed=None):
        """Run one Krita call on `node` and judge it. `before` is (undo index, redo count) from before the layer was made.
        True when it ran and changed something; otherwise the pass has been rejected (False: Krita refused, raised, or changed
        nothing) or the artist's Undo / a closed document is reported (raises). `changed` says whether the layer changed."""
        from .qt_compat import QCoreApplication
        history = hasattr(doc, 'undoIndex') and hasattr(doc, 'undoCount')
        record = {'call': what['call'], 'returned': None}
        try:
            ran = call()
        except Exception as error:
            if self._tool_closed(error):
                raise self._tool_closed(error)
            self._tool_reject(doc, session, result, node, 'Krita raised an error in %s and the layer made for it was removed: %s' % (what['call'], error),
                              dict(record, returned='error', did='Nothing was changed.'))
            return False
        record['returned'] = bool(ran)
        try:
            QCoreApplication.processEvents()                  # a deferred Undo of the artist's lands here, not after the pass is recorded
            kept = self._tool_kept_out(doc, result)
            index = doc.undoIndex() if history else 0
            undone = history and (index < before[0] or doc.undoCount() - index > before[1])
        except RuntimeError as error:
            if self._tool_closed(error):
                raise self._tool_closed(error)
            raise
        if undone:
            self._creative_ended_by_krita(doc, session, result, node, True, history, before, before[0], 'undo')     # raises
        if not ran:
            self._tool_reject(doc, session, result, node,
                              'Krita refused %s (its reason is in Krita\'s log) and nothing was changed. Check the point, colour and options, '
                              'and that the area is not empty.' % what['call'], dict(record, did='Nothing was changed.'))
            return False
        if changed is not None and not changed():
            why = ('It was kept out of the protected %s.' % ', '.join(kept)) if kept else \
                  'Everything was clipped away by the stage region, the area or a protected feature.'
            self._tool_reject(doc, session, result, node, 'Krita ran %s but it changed nothing. %s' % (what['call'], why),
                              dict(record, did='Nothing was changed.'))
            return False
        result['tool_call'] = dict(record, did=what['did'])
        return True

    def _tool_history(self, doc):
        if hasattr(doc, 'undoIndex') and hasattr(doc, 'undoCount'):
            index = doc.undoIndex()
            return index, doc.undoCount() - index
        return 0, 0

    def _tool_apply(self, doc, session, operation, params, result):
        from .qt_compat import QColor
        method, kind, title = METHODS[operation]
        limit, rect, base = self._tool_limit(doc, session, params)
        if limit is None:
            return {'status': 'rejected', 'error': 'The area is empty inside the canvas. Nothing was changed.', 'error_code': 'validation_rejected'}
        options = tool_options(kind, params.get('options'))
        if kind in ('fill', 'enclose'):
            options.setdefault('sample', 'all')
        step = '%s: %s' % (title, params['name'])
        if operation == 'smart_patch':
            return self._tool_patch(doc, session, params, result, limit, rect, options, step)
        enclosing = None
        if operation == 'enclose_and_fill':
            enclosing = (self._region_load(session, params['enclose_selection']) if 'enclose_selection' in params
                         else self._region_build(doc, session, params['enclose_area']))
            enclosed = self._region_bounds(doc, enclosing)
            if enclosed is None:
                return {'status': 'rejected', 'error': 'The enclosing area is empty inside the canvas. Nothing was changed.',
                        'error_code': 'validation_rejected'}
        before = self._tool_history(doc)
        options = dict(options, name=step)
        with one_step(doc, step):
            result.update(self._craft_create(doc, session, self._tool_layer_params(params)))
            node = self._creative_node(doc, result['layer_id'])
            if operation == 'bucket_fill':
                x, y = canvas_pixel(params['x'], params['y'], 'x', 'y', doc.width(), doc.height())
                what = {'call': 'Node.fill', 'did': 'Filled from (%d, %d) with %s: %s region%s, regions found on %s, on the new layer "%s".' % (
                    x, y, params['color'], options.get('mode', 'contiguous'), '' if options.get('mode') != 'similar' else 's of a similar colour',
                    {'all': 'all layers as shown', 'layer': 'this layer', 'labels': 'the labelled layers'}[options['sample']], params['name'])}
                call = lambda: node.fill(x, y, QColor(params['color']), options, limit)
            elif operation == 'enclose_and_fill':
                what = {'call': 'Node.encloseAndFill', 'did': 'Filled the regions inside the enclosing area %s with %s (regions: %s), on the new layer "%s".' % (
                    list(enclosed[0]), params['color'], options.get('regions', 'all'), params['name'])}
                call = lambda: node.encloseAndFill(enclosing, QColor(params['color']), options, limit)
            else:
                from .qt_compat import QPointF
                start, end = params['start'], params['end']
                colours = options.get('colors')
                what = {'call': 'Node.gradient', 'did': 'Painted a %s gradient from (%g, %g) to (%g, %g) with %s, on the new layer "%s".' % (
                    options.get('shape', 'linear'), start[0], start[1], end[0], end[1],
                    '%d colours' % len(colours) if colours else 'the gradient "%s"' % options['gradient'], params['name'])}
                call = lambda: node.gradient(QPointF(float(start[0]), float(start[1])), QPointF(float(end[0]), float(end[1])), options, limit)
            drawn = lambda: node.bounds().width() > 0 and node.bounds().height() > 0
            if not self._tool_run(doc, session, result, node, before, call, what, drawn):
                return {}
        canvas_projection.refresh(doc, list(rect))
        result.update(reached_bounds=list(rect))
        if base is not None:
            self._region_warn_edges(doc, base, rect, result)
        return {}

    def _tool_patch(self, doc, session, params, result, limit, rect, options, step):
        import numpy
        x, y, w, h = rect
        try:
            check_patch_area(w, h)
        except ValueError as refused:
            return {'status': 'rejected', 'error': str(refused), 'error_code': 'validation_rejected'}
        context = int(params.get('context', PATCH_CONTEXT))
        left, top = max(0, x - context), max(0, y - context)
        right, bottom = min(doc.width(), x + w + context), min(doc.height(), y + h + context)
        window = (left, top, right - left, bottom - top)
        before = self._tool_history(doc)
        source = self._creative_node(doc, params['layer_id']) if params.get('layer_id') else None
        patch_options = dict(options, name=step)
        covered = int((numpy.frombuffer(bytes(limit.pixelData(x, y, w, h)), numpy.uint8) > 0).sum())
        what = {'call': 'Node.smartPatch', 'did': 'Patched %d pixels of the area %s from the paint around it (accuracy %d, patch radius %d%s).' % (
            covered, [x, y, w, h], options.get('accuracy', 50), options.get('patchRadius', 4),
            '' if source is not None else ', %d px of the painting around the area searched' % context)}
        with one_step(doc, step):
            if source is not None:
                node, made = self._craft_edit_copy(doc, session, source, params.get('name'))
                result.update(made)
            else:
                result.update(self._craft_create(doc, session, self._tool_layer_params(params)))
                node = self._creative_node(doc, result['layer_id'])
                if node.setPixelData(bytes(doc.pixelData(*window)), *window) is False:
                    return self._tool_reject(doc, session, result, node, 'Krita rejected the painting\'s pixels for the patch layer. Nothing was changed.')
            doc.waitForDone()
            snapshot = bytes(node.pixelData(x, y, w, h))
            patched_something = lambda: (doc.waitForDone(), bytes(node.pixelData(x, y, w, h)) != snapshot)[1]
            if not self._tool_run(doc, session, result, node, before, lambda: node.smartPatch(limit, patch_options), what, patched_something):
                return {}
            if source is not None:
                self._craft_finish_copy(doc, session, source, result)
            else:
                # Only the repair stays on the layer: the copied context goes, and pixels outside the area's selection are clear.
                try:
                    patched = numpy.frombuffer(bytes(node.pixelData(x, y, w, h)), numpy.uint8).reshape(h, w, 4).copy()
                    inside = numpy.frombuffer(bytes(limit.pixelData(x, y, w, h)), numpy.uint8).reshape(h, w) > 0
                    patched[~inside] = 0
                    if (node.setPixelData(bytes(window[2] * window[3] * 4), *window) is False
                            or node.setPixelData(patched.tobytes(), x, y, w, h) is False):
                        raise RuntimeError('Krita rejected the patched pixels.')
                except Exception as error:
                    if self._tool_closed(error):
                        raise self._tool_closed(error)
                    return self._tool_reject(doc, session, result, node, 'The patch could not be cleaned up (%s), so the layer was removed. Nothing was changed.' % error) and {}
            if result.get('kept_out'):
                result['kept_out_note'] = ('The copied context has each protected feature as a hole the patch searches around, so a repair next '
                                           'to one may borrow less from it.')
        canvas_projection.refresh(doc, list(rect))
        result.update(patched_bounds=[x, y, w, h], patched_pixels=covered)
        return {}
