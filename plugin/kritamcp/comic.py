"""Comic pages: the page of panels, panel-scoped painting, and lettering.

Runs inside the creative operation journal (creative_tools.py). The page is the agent's own:

    Comic page                (group)
    ├─ Lettering              (group)            letter() adds one "text · …" vector layer per call
    ├─ Panel borders          (vector layer, locked)  stroke-only rectangles, above all panel art
    ├─ Panel 1 … Panel n      (groups)           each clipped by a "Panel shape" transparency mask
    └─ Page                   (fill layer)       the page colour behind the gutters

The panel model is stored on the comic_page pass, so a resumed chat rebuilds it from its passes.
Krita's comics tools find lettering by "text" in a vector layer's name.
"""
from krita import Selection
from . import capabilities, comic_layout, lettering
from .creative_validation import color, fields, numeric, text

PAGE_FIELDS = comic_layout.LAYOUT_FIELDS + ('name', 'stage_id', 'expected_revision')
LETTER_FIELDS = ('panel', 'kind', 'text', 'at', 'width', 'tail_to', 'font', 'size', 'fill', 'ink', 'name', 'stage_id', 'expected_revision')
DEFAULT_FONT = 'sans-serif'


class ComicCraft:
    # ----- the panel model ------------------------------------------------------
    def _comic_entry(self, session):
        """The unrejected comic_page pass, or None."""
        return next((entry for entry in reversed(session.get('passes', []))
                     if entry.get('kind') == 'comic_page' and entry.get('comic') and not entry.get('rejected')), None)

    def _comic_model(self, session):
        entry = self._comic_entry(session)
        return entry['comic'] if entry else None

    def _comic_panel(self, doc, session, panel_id):
        """(panel, its group node) for `panel_id`; raises ValueError if there is no such panel."""
        model = self._comic_model(session)
        if model is None:
            raise ValueError('There is no comic page yet. Panels exist once the page is built.')
        panel = next((p for p in model['panels'] if p['id'] == panel_id), None)
        if panel is None:
            raise ValueError('Unknown panel %s. This page has %s.' % (panel_id, ', '.join(p['id'] for p in model['panels'])))
        return panel, self._creative_node(doc, panel['group_id'])

    def _comic_inside(self, doc, node, ancestor):
        wanted = ancestor.uniqueId().toString()
        parent = node.parentNode()
        while parent is not None:
            if parent.uniqueId().toString() == wanted:
                return True
            parent = parent.parentNode()
        return False

    def _comic_validate_scope(self, doc, session, operation, params):
        """`panel` on a painting operation: the panel exists and related layers are inside it."""
        if 'panel' not in params:
            return
        _panel, group = self._comic_panel(doc, session, text(params['panel'], 'panel', 8))
        related = [params.get(key) for key in ('clip_to', 'layer_id', 'target', 'continue_layer_id') if params.get(key)]
        for identifier in related:
            if not self._comic_inside(doc, self._creative_node(doc, identifier), group):
                raise ValueError('That layer is not inside panel %s. Name a layer in the same panel, or leave out panel.' % params['panel'])

    def _comic_container(self, doc, session, params):
        """The group new paint goes into for `panel`, or None without one."""
        return self._comic_panel(doc, session, params['panel'])[1] if params.get('panel') else None

    def _comic_reject_guard(self, doc, session, affected):
        """Rejecting the page would hide panel work that is still kept: refuse it."""
        pages = [entry for entry in affected if entry.get('kind') == 'comic_page' and not entry.get('rejected')]
        if not pages:
            return
        rejecting = {entry['id'] for entry in affected}
        for page in pages:
            page_node = self._creative_node(doc, page['layer_id'])
            for entry in session.get('passes', []):
                if entry['id'] in rejecting or entry.get('rejected') or not entry.get('layer_id'):
                    continue
                try:
                    node = self._creative_node(doc, entry['layer_id'])
                except Exception:
                    continue
                if self._comic_inside(doc, node, page_node):
                    raise ValueError('The page still holds kept panel work. Reject the panel work first, or start a new chat.')

    # ----- comic_page -------------------------------------------------------------
    def _comic_validate_page(self, doc, session, params):
        fields(params, PAGE_FIELDS)
        if self._comic_model(session) is not None:
            raise ValueError('This chat already has a comic page. Reject it first to lay out a new one.')
        layout = {key: params[key] for key in comic_layout.LAYOUT_FIELDS if key in params}
        comic_layout.panels(layout, doc.width(), doc.height())
        if 'name' in params:
            text(params['name'], 'name', 120)

    def _comic_page(self, doc, session, params):
        requested = {key: params[key] for key in comic_layout.LAYOUT_FIELDS if key in params}
        layout = comic_layout.resolve(requested)
        panels = comic_layout.panels(requested, doc.width(), doc.height())
        root = doc.rootNode()
        children = root.childNodes()
        page = doc.createNode(params.get('name') or 'Comic page', 'grouplayer')
        if page is None or not root.addChildNode(page, children[-1] if children else None):
            raise RuntimeError('Could not create the comic page.')
        owned = [page]
        manifest = self._craft_manifest(doc)
        config = capabilities.info_object(manifest['generators']['color'], {'color': layout['page_color']})
        whole = Selection()
        whole.select(0, 0, doc.width(), doc.height(), 255)
        backdrop = doc.createFillLayer('Page', 'color', config, whole)
        below = None
        if backdrop is not None and page.addChildNode(backdrop, None):
            owned.append(backdrop); below = backdrop
        for panel in panels:
            group = doc.createNode('Panel %d' % panel['order'], 'grouplayer')
            if group is None or not page.addChildNode(group, below):
                raise RuntimeError('Could not create %s.' % panel['id'])
            mask = doc.createTransparencyMask('Panel shape')
            area = Selection()
            area.select(*panel['bounds'], 255)
            mask.setSelection(area)
            if not group.addChildNode(mask, None):
                raise RuntimeError('Could not clip %s to its shape.' % panel['id'])
            owned += [group, mask]
            panel['group_id'] = group.uniqueId().toString()
            below = group
        borders = doc.createVectorLayer('Panel borders')
        if borders is None or not page.addChildNode(borders, below):
            raise RuntimeError('Could not create the panel borders.')
        rects = ''.join('<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="miter"/>'
                        % (tuple(p['bounds']) + (layout['border_color'], layout['border'])) for p in panels)
        if layout['border']:
            borders.addShapesFromSvg(lettering.document(rects, doc.width(), doc.height()))
        lettering_group = doc.createNode('Lettering', 'grouplayer')
        if lettering_group is None or not page.addChildNode(lettering_group, borders):
            raise RuntimeError('Could not create the lettering group.')
        owned += [borders, lettering_group]
        borders.setLocked(True)
        for node in owned:
            session['layers'].add(node.uniqueId().toString())
        doc.refreshProjection()
        model = {'page_id': page.uniqueId().toString(), 'borders_id': borders.uniqueId().toString(),
                 'lettering_id': lettering_group.uniqueId().toString(), 'reading': layout['reading'],
                 'layout': {key: layout[key] for key in comic_layout.LAYOUT_FIELDS if key in layout}, 'panels': panels}
        return {'layer_id': model['page_id'], 'layer_type': 'comic_page', 'comic': model}

    # ----- letter -----------------------------------------------------------------
    def _comic_fonts(self):
        try:
            from PyQt5.QtGui import QFontDatabase
            return set(QFontDatabase().families())
        except Exception:
            return None

    def _comic_measure(self, font, size):
        from PyQt5.QtGui import QFont, QFontMetricsF
        qfont = QFont(font)
        qfont.setPixelSize(int(size))
        metrics = QFontMetricsF(qfont)
        return lambda line: metrics.horizontalAdvance(line) if hasattr(metrics, 'horizontalAdvance') else metrics.width(line)

    def _comic_point(self, value, label, panel):
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(label + ' must be [x, y] in page pixels')
        x, y, w, h = panel['bounds']
        numeric(value[0], label + ' x', x, x + w)
        numeric(value[1], label + ' y', y, y + h)

    def _comic_validate_letter(self, doc, session, params):
        fields(params, LETTER_FIELDS, ('panel', 'kind', 'text', 'at'))
        panel, _group = self._comic_panel(doc, session, text(params['panel'], 'panel', 8))
        if params['kind'] not in lettering.KINDS:
            raise ValueError('kind must be one of: ' + ', '.join(lettering.KINDS))
        text(params['text'], 'text', 400)
        self._comic_point(params['at'], 'at', panel)
        if 'tail_to' in params:
            if params['kind'] not in ('speech', 'thought'):
                raise ValueError('tail_to is for speech and thought balloons.')
            if not isinstance(params['tail_to'], list) or len(params['tail_to']) != 2:
                raise ValueError('tail_to must be [x, y] in page pixels')
            self._comic_point(params['tail_to'], 'tail_to', panel)
        if 'width' in params:
            numeric(params['width'], 'width', 60, panel['bounds'][2])
        if 'size' in params:
            numeric(params['size'], 'size', 8, 200)
        if 'font' in params:
            text(params['font'], 'font', 120)
        for key in ('fill', 'ink'):
            if key in params:
                color(params[key])
        if 'name' in params:
            text(params['name'], 'name', 120)

    def _comic_letter(self, doc, session, params):
        model = self._comic_model(session)
        panel, _group = self._comic_panel(doc, session, params['panel'])
        font, note = params.get('font', DEFAULT_FONT), None
        installed = self._comic_fonts()
        if params.get('font') and installed is not None and font not in installed:
            note = 'Font "%s" is not installed; used the default font.' % font
            font = DEFAULT_FONT
        size = params.get('size', 28)
        kind = params['kind']
        width = params.get('width') or min(panel['bounds'][2] * (0.45 if kind == 'caption' else 0.4), 520)
        markup, bounds, lines = lettering.balloon(
            kind, params['text'].strip(), params['at'], width, self._comic_measure(font, size), font=font, size=size,
            fill=params.get('fill', '#f3e7c9' if kind == 'caption' else '#ffffff'), ink=params.get('ink', '#000000'),
            tail_to=params.get('tail_to'))
        layer = doc.createVectorLayer(params.get('name') or 'text · %s %s' % (kind, panel['id']))
        group = self._creative_node(doc, model['lettering_id'])
        children = group.childNodes()
        if layer is None or not group.addChildNode(layer, children[-1] if children else None):
            raise RuntimeError('Could not add the lettering layer.')
        layer.addShapesFromSvg(lettering.document(markup, doc.width(), doc.height()))
        doc.refreshProjection()
        session['layers'].add(layer.uniqueId().toString())
        result = {'layer_id': layer.uniqueId().toString(), 'layer_type': 'lettering', 'panel': panel['id'],
                  'lettering': {'kind': kind, 'bounds': bounds, 'lines': lines, 'font': font}}
        if note:
            result['note'] = note
        return result
