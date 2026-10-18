"""Krita's own features the agent drives by name: a vetted list of Krita's menu actions.

Runs inside the creative operation journal (creative_tools.py). An action is on the list
only after the audit (krita_actions_audit, run by scripts/audit-krita-actions.mjs) showed on
the installed Krita that it opens no dialog, leaves Krita responsive and is undone. The list
is data, per Krita version, in krita_actions.json; an unaudited version offers no actions.

Pixel actions change a copy of an agent layer (reject shows the original again). Selection
actions read any layer, save the result as a named selection, and leave the artist's own
selection exactly as it was.
"""
import json
import os
import re
from krita import Krita, Selection
from .creative_validation import fields, numeric, text
from .creative_document_identity import document_id, open_documents

ACTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'krita_actions.json')
CLONE_FIELDS = ('source', 'name', 'blend_mode', 'opacity', 'clip_to', 'offset', 'stage_id', 'region', 'expected_revision')
SPLIT_FIELDS = ('source', 'colors', 'region', 'min_area', 'as_layers', 'name_prefix', 'expected_revision', 'stage_id')
PREFIX = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _-]{0,29}$')
ACTION_FIELDS = ('action', 'target', 'selection', 'save_as', 'name', 'expected_revision', 'stage_id', 'region')
AUDIT_CHECKS_MS = (300, 1500)


def load_actions(path=None):
    try:
        with open(path or ACTIONS_PATH) as stream:
            table = json.load(stream)
    except (OSError, ValueError):
        return {}
    return table if isinstance(table, dict) else {}


def compact_actions(actions):
    """What the agent sees of each action: its id, what it does, what it changes and what it needs."""
    return [{key: entry[key] for key in ('id', 'label', 'kind', 'needs') if key in entry} for entry in actions]


class NativeCraft:
    # ----- clone layers -------------------------------------------------------------
    def _native_clone_params(self, params):
        """The clone as create_layer would place it: in the stage, blended, clipped."""
        return dict({key: params[key] for key in ('name', 'blend_mode', 'opacity', 'clip_to', 'stage_id') if key in params}, type='paint')

    def _native_validate_clone(self, doc, session, params):
        fields(params, CLONE_FIELDS, ('source', 'name'))
        source = self._creative_node(doc, text(params['source'], 'source', 200))
        if self._native_holds_agent_layers(session, source):
            # A clone goes into one of the agent's groups (a stage, a clip group, a panel): a group that holds them
            # could end up containing its own clone, a cycle Krita's own UI forbids.
            raise ValueError('A clone cannot go inside the group it copies. Clone a layer inside the group instead.')
        if 'offset' in params:
            self._transform_pair(params['offset'], 'offset', -100000, 100000)
        self._craft_validate_create(doc, session, self._native_clone_params(params))

    def _native_holds_agent_layers(self, session, node):
        """Whether a group is, or contains, one of the agent's own layers or groups."""
        if node.type() != 'grouplayer':
            return False
        pending = [node]
        while pending:
            current = pending.pop()
            if current.uniqueId().toString() in session['layers']:
                return True
            pending.extend(child for child in current.childNodes() if child.type() == 'grouplayer')
        return False

    def _native_clone(self, doc, session, params):
        """A clone layer of any layer; the source is only read. An offset is a transform mask on the clone."""
        result = self._craft_create(doc, session, dict(self._native_clone_params(params), type='clone', source=params['source']))
        result.update(layer_type='clonelayer', clone_of=params['source'])
        parent = self._creative_node(doc, result['layer_id']).parentNode()
        while parent is not None:                          # backstop: never inside its own source
            if parent.uniqueId().toString() == params['source']:
                self._creative_node(doc, result['layer_id']).remove()
                raise RuntimeError('The clone landed inside the group it copies; it was removed.')
            parent = parent.parentNode()
        if params.get('offset'):
            self._transform_apply(doc, session, {'layer_id': result['layer_id'], 'move': params['offset'], 'name': 'Offset'})
            result['offset'] = params['offset']
        return result

    # ----- split by colour -----------------------------------------------------------
    def _native_validate_split(self, doc, session, params):
        fields(params, SPLIT_FIELDS, ('source',))
        if params['source'] != 'visible':
            source = self._creative_node(doc, text(params['source'], 'source', 200))
            # A layer can have its own colour space: its pixel buffer would not be 8-bit BGRA.
            if hasattr(source, 'colorModel') and (source.colorModel() != 'RGBA' or source.colorDepth() != 'U8'):
                raise ValueError('Split by colour needs an 8-bit RGBA layer; this layer has its own colour space.')
        colors = params.get('colors', 8)
        if isinstance(colors, bool) or not isinstance(colors, int) or not 2 <= colors <= 24:
            raise ValueError('colors must be a whole number from 2 to 24')
        if 'region' in params:
            self._creative_region(params['region'], doc.width(), doc.height())
        if 'min_area' in params:
            numeric(params['min_area'], 'min_area', 0, doc.width() * doc.height())
        if 'as_layers' in params and not isinstance(params['as_layers'], bool):
            raise ValueError('as_layers must be true or false')
        if 'name_prefix' in params and not (isinstance(params['name_prefix'], str) and PREFIX.match(params['name_prefix'])):
            raise ValueError('name_prefix is 1-30 letters, digits, spaces, - or _.')
        self._craft_check_rgba(doc, 'Split by colour')
        self._region_saved_path(session, 'Split')                  # a study folder for the selections

    def _native_split(self, doc, session, params):
        """The painting's main colour regions as saved selections, largest first; with as_layers also one agent layer
        per colour, in one group, as one pass."""
        from . import color_split
        from .region_craft import STRIP
        self._native_validate_split(doc, session, params)
        x, y, w, h = params.get('region') or (0, 0, doc.width(), doc.height())
        node = doc.rootNode() if params['source'] == 'visible' else self._creative_node(doc, params['source'])
        doc.waitForDone()
        bgra = b''.join(bytes(node.projectionPixelData(x, top, w, min(STRIP, y + h - top))) for top in range(y, y + h, STRIP))
        colours = color_split.palette(bgra, w, h, params.get('colors', 8))
        indices = color_split.assign(bgra, w, h, colours)
        # One mask at a time, keeping only each region's size and bounds; masks are rebuilt when saved.
        minimum = params.get('min_area', round(w * h * 0.002))             # specks: 0.2% of the area split
        found = []
        for index, colour in enumerate(colours):
            extent = color_split.extent(color_split.mask(indices, index), w, h)
            if extent is not None and extent[1] >= max(1, minimum):
                found.append((extent[1], colour, index, extent[0]))
        found.sort(key=lambda item: -item[0])
        prefix, canvas = params.get('name_prefix', 'Split'), doc.width() * doc.height()
        selections, layers = [], []
        for number, (pixels, colour, index, bounds) in enumerate(found, 1):
            hexa = '%02x%02x%02x' % colour
            name = '%s %d %s' % (prefix, number, hexa)
            area = color_split.crop(color_split.mask(indices, index), w, bounds)
            bx, by, bw, bh = bounds
            rect = (x + bx, y + by, bw, bh)
            selection = Selection()
            selection.setPixelData(area, *rect)
            self._region_save(doc, session, name, selection, rect)
            selections.append({'name': name, 'color': '#' + hexa, 'share': round(pixels / canvas, 4), 'bounds': list(rect)})
            layers.append((name, index, bounds, rect))
        result = {'status': 'ok', 'selections': selections}
        if params.get('as_layers'):
            result.update(self._craft_create(doc, session, dict({'name': prefix, 'type': 'group'},
                                                                 **({'stage_id': params['stage_id']} if params.get('stage_id') else {}))))
            group = self._creative_node(doc, result['layer_id'])
            for name, index, bounds, rect in layers:
                layer = doc.createNode(name, 'paintlayer')
                if layer is None or not group.addChildNode(layer, None):
                    raise RuntimeError('Could not add the colour layer.')
                # Only the region's bounds: a full-canvas write would allocate every tile of every layer.
                pixels = color_split.cut(color_split.crop(bgra, w, bounds, 4), color_split.crop(color_split.mask(indices, index), w, bounds))
                if layer.setPixelData(pixels, *rect) is False:
                    raise RuntimeError('Krita rejected the colour layer pixels.')
                session['layers'].add(layer.uniqueId().toString())
            doc.refreshProjection()
        return result

    # ----- vetted actions ----------------------------------------------------------
    def _native_actions(self, version):
        entries = load_actions(ACTIONS_PATH).get(version)
        return [entry for entry in entries if isinstance(entry, dict) and entry.get('id')] if isinstance(entries, list) else []

    def _native_action_entry(self, params):
        identifier = text(params.get('action'), 'action', 80)
        version = Krita.instance().version()
        actions = self._native_actions(version)
        if not actions:
            raise ValueError('The installed Krita (%s) has not been audited, so no Krita actions are available.' % version)
        entry = next((a for a in actions if a['id'] == identifier), None)
        if entry is None:
            raise ValueError('Unknown Krita action "%s". Available: %s' % (identifier, ', '.join(a['id'] for a in actions)))
        return entry

    def _native_action_kind(self, params):
        return self._native_action_entry(params).get('kind', 'pixels')

    def _native_validate_action(self, doc, session, params):
        fields(params, ACTION_FIELDS, ('action', 'target'))
        entry = self._native_action_entry(params)
        node = self._creative_node(doc, text(params['target'], 'target', 200))
        if entry.get('kind') == 'selection':
            self._region_saved_path(session, text(params.get('save_as'), 'save_as', 40))
        else:
            if not self._craft_owned(session, params['target']):
                raise ValueError("The artist's layers are never changed by an action. Target one of your own layers.")
            if node.type() != 'paintlayer':
                raise ValueError('A pixel action goes on one of your paint layers.')
            if node.locked():
                raise ValueError('The layer is locked.')
        self._native_check_view(doc, node)
        if 'selection' in entry.get('needs', ()) and not params.get('selection'):
            raise ValueError('%s needs a saved selection: give selection.' % entry['id'])
        if params.get('selection'):
            self._region_saved_path(session, params['selection'], must_exist=True)
        if 'name' in params:
            text(params['name'], 'name', 120)
        return entry, node

    def _native_check_view(self, doc, node):
        """Krita's menu commands act on the active view's document and layer, not on `doc`: refuse unless they are
        this painting and `node`. Leaves the artist's active layer as it was."""
        if document_id(Krita.instance().activeDocument()) != document_id(doc):
            raise ValueError('Krita shows another document, where its commands would act. Switch back to the painting first.')
        active = doc.activeNode()
        try:
            doc.setActiveNode(node)
            current = doc.activeNode()
            if current is None or current.uniqueId().toString() != node.uniqueId().toString():
                raise ValueError('Krita could not make that layer active, so the command would act on another layer. Nothing was changed.')
        finally:
            if active is not None:
                doc.setActiveNode(active)

    def _native_trigger(self, doc, session, entry, node, params):
        """Run one action with `node` active and the input selection set; the artist's selection and active layer
        come back afterwards. Returns the selection Krita left."""
        action = Krita.instance().action(entry['id'])
        if action is None:
            raise RuntimeError('This Krita has no action "%s".' % entry['id'])
        self._native_check_view(doc, node)
        artist, active = doc.selection(), doc.activeNode()
        doc.setActiveNode(node)
        doc.setSelection(self._region_load(session, params['selection']) if params.get('selection') else None)
        try:
            action.trigger()
            doc.waitForDone()
            return doc.selection()
        finally:
            doc.setSelection(artist)
            if active is not None:
                doc.setActiveNode(active)

    def _native_action(self, doc, session, params):
        """A pixel action: Krita's command on a copy of the agent layer, the original hidden."""
        entry, source = self._native_validate_action(doc, session, params)
        copy, result = self._craft_edit_copy(doc, session, source, params.get('name'))
        try:
            self._native_trigger(doc, session, entry, copy, params)
        except Exception:
            copy.remove()                                  # nothing ran on the copy: take it out again
            session['layers'].discard(result['layer_id'])
            raise
        doc.refreshProjection()
        self._craft_finish_copy(doc, session, source, result)
        result.update(action=entry['id'], action_label=entry.get('label') or entry['id'])
        return result

    def _native_select_action(self, doc, session, params):
        """A selection action: not a canvas change, so no pass; the result is saved as a named selection."""
        entry, node = self._native_validate_action(doc, session, params)
        selection = self._native_trigger(doc, session, entry, node, params)
        extent = self._region_bounds(doc, selection) if selection is not None else None
        if extent is None:
            raise ValueError('%s selected nothing. Nothing was saved.' % entry['id'])
        rect, pixels = extent
        self._region_save(doc, session, params['save_as'], selection, rect)
        return {'status': 'ok', 'action': entry['id'], 'name': params['save_as'].strip(), 'bounds': list(rect), 'selected_pixels': pixels}

    # ----- audit ------------------------------------------------------------------
    def _native_audit(self, params):
        """Try each candidate on a throwaway document: a dialog, a change and an undo, per action."""
        fields(params, ('candidates',), ('candidates',))
        candidates = params['candidates']
        if not isinstance(candidates, list) or not 0 < len(candidates) <= 64:
            raise ValueError('candidates must be a list of 1-64 action ids')
        for candidate in candidates:
            text(candidate, 'candidate', 80)
        # Commands and undo act on the active view: with no painting open, the only document is the audit's own.
        if open_documents():
            raise ValueError('Close every painting before the action audit, so its commands cannot reach one.')
        from PyQt5.QtCore import QCoreApplication, QElapsedTimer, QTimer
        from . import audit_dialogs
        app = Krita.instance()
        doc = app.createDocument(256, 256, 'Action audit', 'RGBA', 'U8', '', 300.0)
        window = app.activeWindow()
        if window is not None:
            window.addView(doc)
        results = []
        try:
            for identifier in candidates:
                action = app.action(identifier)
                if action is None:
                    results.append({'id': identifier, 'status': 'missing', 'changed': False, 'undone': False})
                    continue
                layer = self._native_audit_layer(doc)
                before = self._native_audit_state(doc, layer)
                known = audit_dialogs.visible_windows()
                found = []
                def close_dialogs():
                    for widget in audit_dialogs.new_dialogs(known):
                        found.append(audit_dialogs.describe(widget))
                        widget.close()
                for delay in AUDIT_CHECKS_MS:
                    QTimer.singleShot(delay, close_dialogs)
                if document_id(app.activeDocument()) != document_id(doc):
                    results.append({'id': identifier, 'status': 'error', 'error': 'the audit document is not active', 'changed': False, 'undone': False})
                    break                                  # stop: a command could reach another document
                try:
                    action.trigger()
                    timer = QElapsedTimer(); timer.start()
                    while timer.elapsed() < AUDIT_CHECKS_MS[-1] + 200:
                        QCoreApplication.processEvents()
                    doc.waitForDone()
                    changed = self._native_audit_state(doc, layer) != before
                    undo = app.action('edit_undo')
                    if changed and undo is not None and document_id(app.activeDocument()) == document_id(doc):
                        undo.trigger(); doc.waitForDone()
                    undone = self._native_audit_state(doc, layer) == before
                    results.append({'id': identifier, 'status': 'dialog' if found else 'ok', 'changed': changed, 'undone': undone, 'dialogs': found})
                except Exception as error:
                    results.append({'id': identifier, 'status': 'error', 'error': str(error), 'changed': False, 'undone': False})
        finally:
            doc.setModified(False)
            doc.close()
        return {'status': 'ok', 'version': app.version(), 'results': results}

    def _native_audit_layer(self, doc):
        """A fresh layer painted on its left half and a selection over the top half: different areas, so selection
        commands (select opaque and its add, subtract and intersect forms) have something to change."""
        root = doc.rootNode()
        for child in root.childNodes():
            child.remove()
        layer = doc.createNode('Audit', 'paintlayer')
        root.addChildNode(layer, None)
        layer.setPixelData(bytes([40, 80, 200, 255]) * (128 * 256), 0, 0, 128, 256)
        area = Selection()
        area.select(0, 0, 256, 128, 255)
        doc.setSelection(area)
        doc.setActiveNode(layer)
        doc.waitForDone()
        return layer

    def _native_audit_state(self, doc, layer):
        selection = doc.selection()
        try:
            pixels = bytes(layer.pixelData(0, 0, 256, 256))
        except Exception:
            pixels = None
        return (pixels, [n.name() for n in doc.rootNode().childNodes()],
                bytes(selection.pixelData(0, 0, 256, 256)) if selection is not None else None)
