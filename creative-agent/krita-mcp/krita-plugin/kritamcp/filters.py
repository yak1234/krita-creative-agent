"""Filters as masks, filter layers or filtered copies, on the agent's own layers only.

Every method here runs inside the creative operation journal (creative_tools.py).
The artist's layers are never filtered:

* `mask` (the default): a filter mask on an agent layer or group. Its pixels are
  unchanged; rejecting the pass hides the mask, fading changes its opacity.
* `layer`: a filter layer inside one of the agent's groups. It grades everything
  below it in that group, never the artist's layers outside it.
* `copy`: the filter applied to the pixels of a copy of an agent paint layer, with
  the original hidden, for painting over the filtered result.

A saved selection or inline selection steps (region_craft.py) limit the effect.
Filters run with Krita's batch mode on, so no dialog can stop them.

Krita ignores a filter mask's opacity, but its pixels are a strength map. Each mask's
coverage is saved in the study folder, and fading rewrites the mask as that coverage
times the strength, always from the saved original.
"""
import contextlib
import hashlib
import os
from krita import Krita, Selection
from .creative_validation import fields, text
from . import capabilities

FILTER_FIELDS = ('target', 'filter', 'config', 'mode', 'name', 'selection', 'area', 'stage_id', 'region', 'expected_revision', 'panel')
MODES = ('mask', 'layer', 'copy')
MASK_TARGETS = ('paintlayer', 'grouplayer', 'filllayer', 'clonelayer')


@contextlib.contextmanager
def _no_selection(doc):
    """The document's selection cleared for the block, then put back (also when the block raises).

    In the Krita Agent fork Filter.apply keeps to the document's selection (an artist's or a protection area), as the
    filter dialog does. The copy is filtered whole here, and the area is blended in afterwards (region_raster.blend), so
    the selection must not cut the filter itself."""
    selected = doc.selection()
    if selected is None:
        yield
        return
    doc.setSelection(None)
    try:
        yield
    finally:
        doc.setSelection(selected)


class FilterCraft:
    def _filter_validate(self, doc, session, params):
        fields(params, FILTER_FIELDS, ('target', 'filter'))
        mode = params.get('mode', 'mask')
        if mode not in MODES:
            raise ValueError('mode must be mask, layer or copy')
        capabilities.validate_filter(params['filter'], params.get('config'), self._craft_manifest(doc))
        target = self._creative_node(doc, text(params['target'], 'target', 200))
        if not self._craft_owned(session, params['target']):
            raise ValueError("The artist's layers are never filtered. Apply it to your own layer, or use mode layer "
                             "on one of your groups to grade what is inside it.")
        if target.locked():
            raise ValueError('The target layer is locked.')
        kind = target.type()
        if mode == 'mask' and kind not in MASK_TARGETS:
            raise ValueError('A filter mask goes on a paint, fill, clone or group layer.')
        if mode == 'copy' and kind != 'paintlayer':
            raise ValueError('copy filters the pixels of a paint layer. Use mask for other layers.')
        if mode == 'layer' and self._filter_layer_group(session, target) is None:
            raise ValueError('A filter layer goes inside one of your groups: target the group, or a layer inside it.')
        if 'name' in params:
            text(params['name'], 'name', 120)
        areas = [key for key in ('selection', 'area') if key in params]
        if len(areas) > 1:
            raise ValueError('Limit the filter with selection or area, not both.')
        if 'selection' in params:
            self._region_saved_path(session, params['selection'], must_exist=True)
        elif 'area' in params:
            self._region_validate_steps(doc, session, params['area'])
        if areas and mode == 'copy':
            self._craft_check_rgba(doc, 'A filter limited to an area of a copy')

    def _filter_layer_group(self, session, target):
        """The agent group a filter layer for `target` goes into, or None."""
        group = target if target.type() == 'grouplayer' else target.parentNode()
        if group is None or group.type() != 'grouplayer' or not self._craft_owned(session, group.uniqueId().toString()):
            return None
        return group

    def _filter_krita(self, params):
        found = Krita.instance().filter(params['filter'])
        if found is None:
            raise RuntimeError('Krita has no filter "%s".' % params['filter'])
        found.setConfiguration(capabilities.configured(found.configuration(), params.get('config')))
        return found

    def _filter_apply(self, doc, session, params):
        mode = params.get('mode', 'mask')
        target = self._creative_node(doc, params['target'])
        area = None
        if 'selection' in params:
            area = self._region_load(session, params['selection'])
        elif 'area' in params:
            area = self._region_build(doc, session, params['area'])
        extent = self._region_bounds(doc, area) if area is not None else None
        if area is not None and extent is None:
            return {'status': 'rejected', 'error': 'The area is empty inside the canvas. Nothing was filtered.',
                    'error_code': 'validation_rejected'}
        krita_filter = self._filter_krita(params)
        name = params.get('name') or '%s (%s)' % (params['filter'], mode)
        self._creative_progress(session, 'painting', 'Applying ' + params['filter'])
        batch = doc.batchmode() if hasattr(doc, 'batchmode') else False
        doc.setBatchmode(True)
        try:
            if mode == 'copy':
                result = self._filter_copy(doc, session, target, krita_filter, params.get('name'), area, extent)
            else:
                result = self._filter_node(doc, session, target, krita_filter, name, mode, area,
                                           extent[0] if extent else (0, 0, doc.width(), doc.height()))
            doc.waitForDone()
        finally:
            doc.setBatchmode(batch)
        result.update(filter=params['filter'], mode=mode, target_id=params['target'])
        if extent is not None:
            result['filtered_bounds'] = list(extent[0])
        doc.refreshProjection()
        return result

    def _filter_node(self, doc, session, target, krita_filter, name, mode, area, rect):
        if area is None:
            area = Selection()
            area.select(0, 0, doc.width(), doc.height(), 255)
        if mode == 'mask':
            node = doc.createFilterMask(name, krita_filter, area)
            if node is None or not target.addChildNode(node, None):
                raise RuntimeError('Krita could not add the filter mask.')
            if session.get('output'):
                identifier = node.uniqueId().toString()
                self._region_write(self._filter_coverage_path(session, identifier),
                                   {'mask_id': identifier, 'rect': list(rect)}, area.pixelData(*rect))
        else:
            node = doc.createFilterLayer(name, krita_filter, area)
            group = self._filter_layer_group(session, target)
            if group is target:
                children = target.childNodes()
                placed = node is not None and target.addChildNode(node, children[-1] if children else None)
            else:
                placed = node is not None and group.addChildNode(node, target)
            if not placed:
                raise RuntimeError('Krita could not add the filter layer.')
        identifier = node.uniqueId().toString()
        session['layers'].add(identifier)
        return {'layer_id': identifier, 'layer_type': 'filter_mask' if mode == 'mask' else 'filter_layer'}

    def _filter_coverage_path(self, session, mask_id):
        return os.path.join(session['output'], '.filter-masks', hashlib.sha256(mask_id.encode()).hexdigest()[:24] + '.cov')

    def _filter_fade(self, session, node, strength):
        """Fade a filter mask to `strength` (0..1) through its pixels. False without saved coverage."""
        if not session.get('output'):
            return False
        path = self._filter_coverage_path(session, node.uniqueId().toString())
        if not os.path.exists(path):
            return False
        header, coverage = self._region_read(path)
        scaled = coverage.translate(bytes(round(value * strength) for value in range(256)))
        if node.setPixelData(scaled, *header['rect']) is False:
            raise RuntimeError('Krita rejected the faded filter mask.')
        return True

    def _filter_copy(self, doc, session, target, krita_filter, name, area, extent):
        copy, result = self._craft_edit_copy(doc, session, target, name)
        if extent is None:
            with _no_selection(doc):
                if krita_filter.apply(copy, 0, 0, doc.width(), doc.height()) is False:
                    raise RuntimeError('Krita could not apply the filter.')
        else:
            from . import region_raster
            (x, y, w, h), _pixels = extent
            original = bytes(copy.pixelData(x, y, w, h))
            with _no_selection(doc):
                if krita_filter.apply(copy, x, y, w, h) is False:
                    raise RuntimeError('Krita could not apply the filter.')
            doc.waitForDone()
            blended = region_raster.blend(original, bytes(copy.pixelData(x, y, w, h)), bytes(area.pixelData(x, y, w, h)), w, h)
            if copy.setPixelData(blended, x, y, w, h) is False:
                raise RuntimeError('Krita rejected the filtered pixels.')
        self._craft_finish_copy(doc, session, target, result)
        doc.setActiveNode(copy)
        return result
