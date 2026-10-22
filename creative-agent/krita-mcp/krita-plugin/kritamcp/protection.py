"""Protected areas: parts of the painting the agent must never change.

Each area is a selection mask inside one locked group the plugin owns, at the top of the layer stack, so the areas
are saved in the .kra and travel with the painting. Their state (pending until the artist keeps an area the agent
proposed, or active), who made them and their bounds live in a document annotation, keyed by the mask's unique id;
an area whose mask the artist deleted by hand is dropped from it. A pending area binds the agent at once: the painter
proposes the moon and paints over the sky in the same turn, before the artist could keep it. Keeping makes it the
artist's; discarding it frees the agent again.

The agent may only propose an area. Keeping, adjusting and removing are panel calls in the same process, never
operations the companion can send.

Locked layers are listed as protected: the agent never edits their pixels or settings. They add nothing to the
protection mask, since a locked, opaque background would otherwise erase every pass on the canvas.
"""
import json

from krita import Selection

from .creative_validation import fields, text

PROTECTION_GROUP = 'Protected areas · Creative Agent'
ANNOTATION = 'creative-agent-protection'
PANEL_ONLY = ('protection_keep', 'protection_remove', 'protection_discard', 'protection_set_state')
# Layers whose look is not their own pixels: protection masks them instead of erasing.
# States the agent keeps out of: what the artist kept, and what the agent itself proposed.
ENFORCED = ('active', 'pending')
MASKED_TYPES = ('filllayer', 'filterlayer', 'generatorlayer', 'clonelayer', 'filelayer', 'vectorlayer')


class ProtectionCraft:
    PROTECTION_GROUP = PROTECTION_GROUP

    # ----- storage -------------------------------------------------------------
    def _protect_group(self, doc, create=False):
        group = next((n for n in doc.rootNode().childNodes() if n.name() == PROTECTION_GROUP and n.type() == 'grouplayer'), None)
        if group is None and create:
            group = doc.createNode(PROTECTION_GROUP, 'grouplayer')
            doc.rootNode().addChildNode(group, None)
            group.setLocked(True)
        return group

    def _protect_records(self, doc):
        """The saved records, without those whose mask is gone. A Krita without document annotations has none."""
        if not hasattr(doc, 'annotation'):
            return {}, {}
        try:
            records = json.loads(bytes(doc.annotation(ANNOTATION)) or b'{}')
        except ValueError:
            records = {}
        # Found by id anywhere in the painting: renaming the group or moving a mask out of it keeps the area.
        masks = {n.uniqueId().toString(): n for n in self._protect_nodes(doc) if n.type() == 'selectionmask'}
        masks = {key: node for key, node in masks.items() if key in records}
        kept = {key: value for key, value in records.items() if key in masks}
        if kept != records:
            self._protect_save(doc, kept)
        return kept, masks

    def _protect_editing(self, doc, editing):
        """Krita will not paint on a mask inside a locked group: Paint over it unlocks the group while it lasts."""
        group = self._protect_group(doc)
        if group is not None: group.setLocked(not editing)

    @staticmethod
    def _protect_check_depth(doc):
        """The pixel work reads 8-bit RGBA; other paintings are refused before anything changes."""
        if (doc.colorModel(), doc.colorDepth()) != ('RGBA', 'U8'):
            raise ValueError('Protected areas work on 8-bit RGBA paintings; this one is %s %s. Convert it with Image > '
                             'Convert Image Color Space, or remove its protected areas.' % (doc.colorModel(), doc.colorDepth()))

    def _protect_save(self, doc, records):
        doc.setAnnotation(ANNOTATION, 'Creative Agent protected areas', json.dumps(records).encode('utf-8'))

    def _protect_nodes(self, doc):
        """Every node in the painting. Its own walk, so the panel can use this mixin without the plugin."""
        found, pending = [], list(doc.rootNode().childNodes())
        while pending:
            node = pending.pop()
            found.append(node); pending.extend(node.childNodes())
        return found

    # ----- reading -------------------------------------------------------------
    def _protect_list(self, doc):
        records, _masks = self._protect_records(doc)
        areas = [dict(record, id=key) for key, record in records.items()]
        _records, masks = self._protect_records(doc)
        holders = {mask.parentNode().uniqueId().toString() for mask in masks.values() if mask.parentNode() is not None}
        locked = [n for n in self._protect_nodes(doc) if n.locked() and n.type() != 'selectionmask'
                  and n.name() != PROTECTION_GROUP and n.uniqueId().toString() not in holders]
        if locked:
            areas.append({'id': 'locked-layers', 'name': 'Locked layers', 'state': 'active', 'by': 'automatic', 'count': len(locked)})
        return areas

    def _protect_active(self, doc):
        """Areas the agent keeps out of, for the painter: id, name and bounds."""
        records, _masks = self._protect_records(doc)
        return [{'id': key, 'name': r['name'], 'bounds': r['bounds']} for key, r in records.items() if r['state'] in ENFORCED]

    def _protect_mask(self, doc, rect):
        """The union of the enforced areas within rect [x, y, w, h], one byte per pixel, or None when nothing there
        is protected."""
        from . import protection_raster
        records, masks = self._protect_records(doc)
        x, y, w, h = rect
        planes = []
        for key, record in records.items():
            bx, by, bw, bh = record['bounds']
            if record['state'] not in ENFORCED or bx >= x + w or by >= y + h or bx + bw <= x or by + bh <= y:
                continue
            planes.append(bytes(masks[key].selection().pixelData(x, y, w, h)))
        if not planes:
            return None
        union = protection_raster.union(planes, w, h)
        return union if union.count(0) < len(union) else None

    # ----- changing --------------------------------------------------------------
    def _protect_add(self, doc, selection, name, by, state, bounds):
        if not hasattr(doc, 'setAnnotation') or not hasattr(doc, 'createSelectionMask'):
            raise ValueError('This version of Krita cannot save protected areas in the painting.')
        self._protect_check_depth(doc)
        mask = doc.createSelectionMask(name)
        mask.setSelection(selection)
        self._protect_group(doc, create=True).addChildNode(mask, None)
        records, _masks = self._protect_records(doc)
        key = mask.uniqueId().toString()
        records[key] = {'name': name, 'state': state, 'by': by, 'bounds': list(bounds)}
        self._protect_save(doc, records)
        return dict(records[key], id=key)

    def _protect_set_state(self, doc, area_id, state):
        records, _masks = self._protect_records(doc)
        if area_id not in records:
            raise ValueError('That protected area is no longer in this painting.')
        records[area_id]['state'] = state
        self._protect_save(doc, records)

    def _protect_mask_node(self, doc, area_id):
        """The selection mask of an area, for the panel's Paint over it and Show."""
        return self._protect_records(doc)[1].get(area_id)

    def _protect_set_bounds(self, doc, area_id, bounds):
        records, _masks = self._protect_records(doc)
        if area_id in records:
            records[area_id]['bounds'] = list(bounds)
            self._protect_save(doc, records)

    def _protect_remove(self, doc, area_id):
        records, masks = self._protect_records(doc)
        if area_id in masks:
            masks[area_id].remove()
        records.pop(area_id, None)
        self._protect_save(doc, records)

    # ----- operations the companion may send ---------------------------------------
    def _protect_operation(self, doc, session, operation, params):
        if operation in PANEL_ONLY:
            raise ValueError('Only the artist can change protection in the panel.')
        if operation == 'protection_list':
            fields(params, ())
            return {'status': 'ok', 'areas': self._protect_list(doc)}
        fields(params, ('name', 'area'), ('name', 'area'))
        name = text(params['name'], 'name', 60).strip()
        self._region_validate_steps(doc, session, params['area'])
        selection = self._region_build(doc, session, params['area'])
        extent = self._region_bounds(doc, selection)
        if extent is None:
            raise ValueError('The area is empty inside the canvas. Nothing was proposed.')
        area = self._protect_add(doc, selection, name, 'agent', 'pending', extent[0])
        return {'status': 'ok', 'area': area,
                'message': 'Shown in red. You keep out of it from now on; the artist keeps or discards it.'}

    # ----- enforcement -----------------------------------------------------------
    def _protect_area_masks(self, doc, rect):
        """(name, mask) for each enforced area overlapping rect, each mask one byte per pixel of rect."""
        records, masks = self._protect_records(doc)
        x, y, w, h = rect
        found = []
        for key, record in records.items():
            bx, by, bw, bh = record['bounds']
            if record['state'] in ENFORCED and bx < x + w and by < y + h and bx + bw > x and by + bh > y:
                found.append((record['name'], bytes(masks[key].selection().pixelData(x, y, w, h))))
        return found

    def _protect_refuse(self, doc, session, operation, params):
        """The artist's own layers may not change where they show inside a protected area: their settings, or a
        toolbox edit of a copy (which hides the original)."""
        target = (params.get('layer_id') if operation in ('adjust_layer', 'set_layer')
                  else params.get('source_layer_id') if operation == 'painting_toolbox' else None)
        if not target or self._craft_owned(session, target):
            return
        active = self._protect_active(doc)
        if not active:
            return
        from . import protection_raster
        node = self._creative_node(doc, target)
        for area in active:
            for name, mask in self._protect_area_masks(doc, area['bounds']):
                if name == area['name'] and protection_raster.visible_inside(bytes(node.pixelData(*area['bounds'])), mask):
                    raise ValueError("That layer shows inside the protected area '%s'." % name)

    @staticmethod
    def _protect_reach(params, operation):
        """[left, top, right, bottom] a paint pass can touch: its strokes' points widened well past the brush (a
        scattering preset throws dabs several diameters out), cut to its region. None when it can reach anywhere."""
        if operation not in ('paint_pass', 'draw_guide') or not params.get('strokes'):
            return None
        xs, ys = [], []
        for stroke in params['strokes']:
            pad = 6 * float(stroke.get('size', 0) if operation == 'paint_pass' else 4) + 16    # a guide line is at most 4 px
            for x, y in [stroke['start']] + [(seg[i], seg[i + 1]) for seg in stroke.get('segments', []) for i in (0, 2, 4)]:
                xs += [x - pad, x + pad]; ys += [y - pad, y + pad]
        reach = [int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1]
        # A pass's region, or the shape it paints inside (element-shapes 1.5, validated before this is used), cuts it.
        limit = params.get('region') or (params.get('inside_shape') or {}).get('bounds')
        if limit:
            reach = [max(reach[0], limit[0]), max(reach[1], limit[1]), min(reach[2], limit[0] + limit[2]), min(reach[3], limit[1] + limit[3])]
        return reach

    def _protect_capture(self, doc, session, operation, params):
        """What enforcement compares against, read once: the rect where the active areas meet what the operation can
        reach, each area's mask there, their union, the projection, and the pixels of any existing agent layer the
        operation names. None when the operation cannot reach an area."""
        active = self._protect_active(doc)
        if not active:
            return None
        self._protect_check_depth(doc)
        left = max(0, min(a['bounds'][0] for a in active)); top = max(0, min(a['bounds'][1] for a in active))
        right = min(doc.width(), max(a['bounds'][0] + a['bounds'][2] for a in active))
        bottom = min(doc.height(), max(a['bounds'][1] + a['bounds'][3] for a in active))
        reach = self._protect_reach(params, operation)
        if reach:
            left, top, right, bottom = max(left, reach[0]), max(top, reach[1]), min(right, reach[2]), min(bottom, reach[3])
        if right <= left or bottom <= top:
            return None
        rect = (left, top, right - left, bottom - top)
        areas = self._protect_area_masks(doc, rect)
        if not areas:
            return None
        from . import protection_raster
        mask = protection_raster.union([m for _name, m in areas], rect[2], rect[3])
        if mask.count(0) == len(mask):
            return None
        doc.waitForDone()                                       # a refresh from the last operation may still be running
        layers = {}
        for key in ('continue_layer_id', 'layer_id', 'target'):
            layer_id = params.get(key)
            if layer_id and self._craft_owned(session, layer_id):
                try:
                    layers[layer_id] = bytes(self._creative_node(doc, layer_id).pixelData(*rect))
                except ValueError:
                    pass
        return {'rect': rect, 'mask': mask, 'areas': areas, 'projection': bytes(doc.pixelData(*rect)), 'layers': layers}

    def _protect_erase(self, doc, session, operation, params, result, captured):
        """Take the protected areas out of the agent layer this operation made or changed. A layer it made is erased
        there; a layer that existed gets its own earlier pixels back there; any other layer type is masked. Returns
        what was kept out, per area."""
        from . import protection_raster
        layer_id = result.get('layer_id') or params.get('layer_id')
        if not layer_id or not self._craft_owned(session, layer_id):
            return []
        try:
            node = self._creative_node(doc, layer_id)
        except ValueError:
            return []
        rect, mask = captured['rect'], captured['mask']
        x, y, w, h = rect
        # Clone, fill and filter layers have no paint device of their own: what they show is their projection.
        pixels = bytes(node.projectionPixelData(*rect) if node.type() in MASKED_TYPES else node.pixelData(*rect))
        earlier = captured['layers'].get(layer_id)
        hits = []
        for name, area in captured['areas']:
            reached = (protection_raster.changed_inside(earlier, pixels, area, w, h) if earlier is not None
                       else protection_raster.visible_inside(pixels, area))
            if reached:
                hits.append({'name': name, 'pixels': reached, 'share': round(reached / max(1, protection_raster.inside_count(area)), 3)})
        if not hits:
            return []
        if node.type() == 'paintlayer':
            fixed = (protection_raster.restore_inside(pixels, earlier, mask, w, h) if earlier is not None
                     else protection_raster.erase_inside(pixels, mask, w, h)[0])
            node.setPixelData(fixed, *rect)
        elif node.type() in MASKED_TYPES:
            keep = Selection()
            keep.select(0, 0, doc.width(), doc.height(), 255)
            keep.setPixelData(protection_raster.invert(mask), *rect)
            transparency = doc.createTransparencyMask('Protected areas')
            transparency.setSelection(keep)
            node.addChildNode(transparency, None)
        return hits

    def _protect_changed(self, doc, captured):
        """The areas whose visible pixels differ from the capture, after a recomposite."""
        from . import protection_raster
        doc.refreshProjection()
        doc.waitForDone()
        rect = captured['rect']
        after = bytes(doc.pixelData(*rect))
        if not protection_raster.changed_inside(captured['projection'], after, captured['mask'], rect[2], rect[3]):
            return []
        return [name for name, area in captured['areas']
                if protection_raster.changed_inside(captured['projection'], after, area, rect[2], rect[3])] or ['a protected area']

    def _protect_enforce(self, doc, session, operation, params, result, captured, prior=None):
        """After the operation: nothing visible inside an active area may differ from before. Returns the fields to
        add to the result: what was kept out, or a protected_change error."""
        if captured is None:
            return {}
        hits = self._protect_erase(doc, session, operation, params, result, captured)
        changed = self._protect_changed(doc, captured)
        if not changed:
            return {'protected': hits} if hits else {}
        names = ', '.join("'%s'" % name for name in changed)
        undone = {'status': 'error', 'error_code': 'protected_change', 'layer_id': None, 'contribution_removed': True,
                  'error': 'This would have changed %s; it was undone.' % names}
        made = result.get('layer_id')
        if made and made not in (params.get('layer_id'), params.get('continue_layer_id')):
            try:
                self._creative_node(doc, made).remove()
            except ValueError:
                pass
            if not self._protect_changed(doc, captured):
                return undone
        elif operation in ('adjust_layer', 'set_layer') and prior is not None:
            node = self._creative_node(doc, params['layer_id'])
            self._craft_restore(node, prior) if operation == 'set_layer' else (node.setOpacity(prior['opacity']), node.setVisible(prior['visible']))
            if not self._protect_changed(doc, captured):
                return undone
        return {'status': 'partial', 'error_code': 'protected_change',
                'error': 'This changed %s. Inspect the painting before continuing.' % names}

    def _protect_review(self, doc, session, params, review):
        """A review (keep or reject) runs outside the painting path: the backstop alone checks it."""
        captured = self._protect_capture(doc, session, 'review_pass', params)
        result = review()
        if captured is None:
            return result
        changed = self._protect_changed(doc, captured)
        if not changed:
            return result
        return dict(result, status='partial', error_code='protected_change',
                    error='This changed %s. Inspect the painting before continuing.' % ', '.join("'%s'" % n for n in changed))
