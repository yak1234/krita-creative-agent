"""Native layer craft: layers with blend mode, alpha lock and clipping, and their settings.

Every method here runs inside the creative operation journal (creative_tools.py),
which records intent before mutation and a reversible pass afterwards. The agent
never moves, regroups, renames or repaints the artist's layers:

* A live clip uses Krita's inherit alpha, which clips to everything below the layer
  in its group. It is therefore only offered inside a clip group: a group the agent
  created with `clip_base` that holds the base as its bottom layer.
* Clipping to any other base (the artist's layers, or an agent layer outside a clip
  group) adds a transparency mask made from the base's alpha at that moment.
"""
import hashlib
from krita import Krita, Selection
from .creative_validation import fields, numeric, text
from . import capabilities, layer_style

LAYER_TYPES = ('paint', 'fill', 'group')
NODE_TYPES = {'paint': 'paintlayer', 'group': 'grouplayer'}
CREATE_FIELDS = ('name', 'type', 'blend_mode', 'opacity', 'visible', 'alpha_lock', 'clip_to', 'clip_base',
                 'generator', 'generator_config', 'region', 'stage_id', 'expected_revision', 'panel')
SET_FIELDS = ('layer_id', 'name', 'blend_mode', 'opacity', 'visible', 'alpha_lock', 'clip', 'style',
              'region', 'stage_id', 'expected_revision')
CRAFT_SETTINGS = ('name', 'blend_mode', 'alpha_lock', 'clip', 'style')
STRIP = 256


class LayerCraft:
    # ----- manifest -------------------------------------------------------------
    def _craft_manifest(self, doc, refresh=False):
        cached = getattr(self, '_craft_manifest_cache', None)
        if cached is None or refresh or (doc is not None and not cached.get('generators')):
            cached = self._craft_manifest_cache = capabilities.manifest(doc=doc, refresh=refresh)
        return cached

    def _craft_capabilities(self, doc, params):
        fields(params, ('full', 'refresh'))
        full = self._craft_manifest(doc, refresh=params.get('refresh') is True)
        return {'status': 'ok', 'capabilities': full if params.get('full') is True else capabilities.compact(full)}

    # ----- shared checks --------------------------------------------------------
    def _craft_owned(self, session, identifier):
        return identifier in session['layers']

    def _craft_clip_group(self, session, node):
        """The agent clip group whose bottom visible layer is `node`, or None.

        Hidden layers below the base do not count: a filled copy of the base sits
        above the hidden original and is the base from then on.
        """
        parent = node.parentNode() if hasattr(node, 'parentNode') else None
        if parent is None or parent.type() != 'grouplayer':
            return None
        if parent.uniqueId().toString() not in session.get('clip_groups', set()):
            return None
        identifier = node.uniqueId().toString()
        for child in parent.childNodes():
            if child.uniqueId().toString() == identifier:
                return parent
            if child.visible():
                return None
        return None

    def _craft_common(self, params):
        if 'blend_mode' in params:
            capabilities.validate_blend_mode(params['blend_mode'])
        if 'opacity' in params:
            numeric(params['opacity'], 'opacity', 0, 1)
        for key in ('visible', 'alpha_lock', 'clip_base', 'clip'):
            if key in params and not isinstance(params[key], bool):
                raise ValueError(key + ' must be true or false')
        if 'name' in params:
            text(params['name'], 'name', 120)

    # ----- create_layer ---------------------------------------------------------
    def _craft_validate_create(self, doc, session, params):
        fields(params, CREATE_FIELDS, ('name', 'type'))
        kind = params['type']
        if kind not in LAYER_TYPES:
            raise ValueError('Layer type must be one of: ' + ', '.join(LAYER_TYPES))
        self._craft_common(params)
        if params.get('alpha_lock') and kind != 'paint':
            raise ValueError('Alpha lock applies to paint layers only.')
        if params.get('clip_base') and kind == 'group':
            raise ValueError('A clip base is a paint or fill layer.')
        if params.get('clip_base') and params.get('clip_to'):
            raise ValueError('Choose clip_base or clip_to, not both.')
        if kind == 'fill':
            manifest = self._craft_manifest(doc)
            capabilities.validate_generator(params.get('generator'), params.get('generator_config'), manifest)
        elif 'generator' in params or 'generator_config' in params:
            raise ValueError('generator applies to fill layers only.')
        if params.get('region'):
            self._creative_region(params['region'], doc.width(), doc.height())
            if kind != 'fill':
                raise ValueError('region limits a fill layer; use select or paint tools for other layers.')
        if params.get('clip_to'):
            base = self._creative_node(doc, text(params['clip_to'], 'clip_to', 200))
            if not self._craft_live_clip(session, base):
                self._craft_check_rgba(doc, 'Clipping to this layer', 'Create the base with clip_base for a live clip.')

    def _craft_live_clip(self, session, base):
        return self._craft_owned(session, base.uniqueId().toString()) and self._craft_clip_group(session, base) is not None

    def _craft_check_rgba(self, doc, what, hint=''):
        """Pixel reads and writes here are 8-bit BGRA: refuse other colour models before any change."""
        if doc.colorModel() != 'RGBA' or doc.colorDepth() != 'U8':
            raise ValueError(('%s needs an 8-bit RGBA painting. %s' % (what, hint)).strip())

    def _craft_create(self, doc, session, params):
        kind = params['type']
        name = params['name']
        if kind == 'fill':
            manifest = self._craft_manifest(doc)
            generator = params['generator']
            config = capabilities.info_object(manifest['generators'][generator], params.get('generator_config'))
            area = Selection()
            x, y, w, h = params.get('region') or [0, 0, doc.width(), doc.height()]
            area.select(x, y, w, h, 255)
            node = doc.createFillLayer(name, generator, config, area)
        else:
            node = doc.createNode(name, NODE_TYPES[kind])
        if node is None:
            raise RuntimeError('Krita could not create the %s layer.' % kind)
        result = {'layer_id': node.uniqueId().toString(), 'layer_type': kind}
        base = self._creative_node(doc, params['clip_to']) if params.get('clip_to') else None
        if base is not None and self._craft_live_clip(session, base):
            group = base.parentNode()
            children = group.childNodes()
            if not group.addChildNode(node, children[-1]):
                raise RuntimeError('Could not add the layer to its clip group.')
            node.setInheritAlpha(True)
            result['clip'] = {'mode': 'live', 'base_id': base.uniqueId().toString(), 'group_id': group.uniqueId().toString()}
        else:
            parent, above = self._craft_container(doc, session, params)
            below = params.get('_below')
            insert = (lambda new: self._craft_insert_below(doc, below, new)) if below is not None else (lambda new: parent.addChildNode(new, above))
            if params.get('clip_base'):
                group = doc.createNode('Creative Agent · ' + name, 'grouplayer')
                if group is None or not insert(group):
                    raise RuntimeError('Could not create the clip group.')
                group.setBlendingMode('normal')
                if not group.addChildNode(node, None):
                    raise RuntimeError('Could not add the base to its clip group.')
                identifier = group.uniqueId().toString()
                session.setdefault('clip_groups', set()).add(identifier)
                session['layers'].add(identifier)
                result['clip_group_id'] = identifier
            elif not insert(node):
                raise RuntimeError('Could not add the layer to the painting.')
            if base is not None:
                result['clip'] = self._craft_mask_clip(doc, node, base)
        self._craft_apply(node, params)
        if params.get('stage_id'):
            # The pass belongs to its stage group, so later stage work reuses that group.
            result['group_id'] = self._craft_top_group(doc, node, self._comic_container(doc, session, params))
        session['layers'].add(result['layer_id'])
        doc.setActiveNode(node)
        doc.refreshProjection()
        return result

    def _craft_container(self, doc, session, params):
        """Where a new layer goes: below a given layer, the current stage group (inside its comic panel), or the top."""
        if params.get('_below') is not None:
            return self._craft_below(params['_below'])
        panel = self._comic_container(doc, session, params)
        if params.get('stage_id'):
            group = self._creative_stage_group(doc, session, params['stage_id'], panel)
            children = group.childNodes()
            return group, children[-1] if children else None
        root = panel if panel is not None else doc.rootNode()
        children = root.childNodes()
        return root, children[-1] if children else None

    def _craft_below(self, node):
        """Directly below `node`, in its parent: (parent, sibling to add above, or None)."""
        parent = node.parentNode()
        identifier = node.uniqueId().toString()
        below = None
        for child in parent.childNodes():
            if child.uniqueId().toString() == identifier:
                return parent, below
            below = child
        raise RuntimeError('The layer moved during the operation.')

    def _craft_insert_below(self, doc, node, new):
        """Add `new` directly below `node` in its parent.

        Krita's addChildNode places a layer above a sibling, or on top when given none, so a layer
        cannot be added under the bottom one directly: it goes above `node` and is then lowered
        one step with Krita's own Move Layer Down. Only `new` (the agent's layer) moves.
        """
        parent, below = self._craft_below(node)
        if below is not None:
            return parent.addChildNode(new, below)
        if not parent.addChildNode(new, node):
            return False
        self._craft_lower(doc, new)
        order = [child.uniqueId().toString() for child in parent.childNodes()]
        return order.index(new.uniqueId().toString()) < order.index(node.uniqueId().toString())

    def _craft_lower(self, doc, node):
        """Move `node` one step down among its siblings (Krita's Move Layer Down on the active layer)."""
        doc.setActiveNode(node)
        doc.waitForDone()
        action = Krita.instance().action('move_layer_down')
        if action is not None:
            action.trigger()
            doc.waitForDone()

    def _craft_top_group(self, doc, node, root=None):
        """The group directly under `root` (the painting, or a comic panel) that holds `node`."""
        root_id = (root if root is not None else doc.rootNode()).uniqueId().toString()
        top = node
        while top.parentNode() is not None and top.parentNode().uniqueId().toString() != root_id:
            top = top.parentNode()
        return top.uniqueId().toString() if top is not node else None

    def _craft_mask_clip(self, doc, node, base):
        """Clip `node` to `base` with a transparency mask made from the base's alpha now."""
        area, digest = self._craft_alpha_selection(doc, base)
        mask = doc.createTransparencyMask('Clip to ' + base.name())
        if mask is None:
            raise RuntimeError('Could not create the clipping mask.')
        mask.setSelection(area)
        if not node.addChildNode(mask, None):
            raise RuntimeError('Could not attach the clipping mask.')
        return {'mode': 'mask', 'base_id': base.uniqueId().toString(), 'base_alpha': digest,
                'mask_id': mask.uniqueId().toString()}

    def _craft_alpha_selection(self, doc, base):
        """A selection of `base`'s alpha now, read in strips, and a digest of that alpha."""
        self._craft_check_rgba(doc, 'Clipping to this layer', 'Create the base with clip_base for a live clip.')
        doc.waitForDone()
        width, height = doc.width(), doc.height()
        area = Selection()
        digest = hashlib.sha256()
        for y in range(0, height, STRIP):
            rows = min(STRIP, height - y)
            alpha = bytes(base.projectionPixelData(0, y, width, rows))[3::4]   # BGRA, 8-bit
            digest.update(alpha)
            area.setPixelData(alpha, 0, y, width, rows)
        return area, digest.hexdigest()

    def _craft_edit_copy(self, doc, session, source, name=None):
        """A copy of an agent layer for a reversible edit, directly above it.

        Edit the copy, then call _craft_finish_copy to hide the original, so rejecting
        the pass hides the copy and shows the original again.
        """
        result = {'source_layer_id': source.uniqueId().toString(), 'source_prior': self._creative_layer_state(source, doc)}
        doc.waitForDone()
        copy = source.clone()
        if copy is None:
            raise RuntimeError('Krita could not copy the layer.')
        copy.setName(name or source.name())
        if not source.parentNode().addChildNode(copy, source):
            raise RuntimeError('Could not add the copy.')
        identifier = copy.uniqueId().toString()
        session['layers'].add(identifier)
        result.update(layer_id=identifier, layer_type='paint')
        return copy, result

    def _craft_finish_copy(self, doc, session, source, result):
        """Hide the original; its own passes now end in that hidden state."""
        source.setVisible(False)
        result['source_after'] = self._creative_settle(doc, session, source)

    def _craft_apply(self, node, params):
        if 'blend_mode' in params:
            node.setBlendingMode(params['blend_mode'])
        if 'opacity' in params:
            node.setOpacity(round(params['opacity'] * 255))
        if 'visible' in params:
            node.setVisible(params['visible'])
        if 'alpha_lock' in params:
            node.setAlphaLocked(params['alpha_lock'])
        if 'clip' in params:
            node.setInheritAlpha(params['clip'])
        if 'name' in params:
            node.setName(params['name'])
        if 'style' in params:
            self._craft_style(node, layer_style.asl(params['style']))

    def _craft_style(self, node, asl):
        if node.setLayerStyleFromAsl(asl) is False:
            raise RuntimeError('Krita rejected the layer style.')

    # ----- set_layer ------------------------------------------------------------
    def _craft_validate_set(self, doc, session, params):
        fields(params, SET_FIELDS, ('layer_id',))
        self._craft_common(params)
        settings = [key for key in ('name', 'blend_mode', 'opacity', 'visible', 'alpha_lock', 'clip', 'style') if key in params]
        if not settings:
            raise ValueError('Supply at least one setting: name, blend_mode, opacity, visible, alpha_lock, clip or style.')
        # Opacity and visibility work on any unlocked layer, as adjust_layer always has.
        self._creative_validate_adjustment(doc, session, params)
        node = self._creative_node(doc, params['layer_id'])
        craft = [key for key in CRAFT_SETTINGS if key in params]
        if craft and not self._craft_owned(session, params['layer_id']):
            raise ValueError('Only layers the agent created can change %s. Adjust opacity or visibility instead, '
                             'or create a new layer above this one.' % ', '.join(craft))
        if 'alpha_lock' in params and node.type() != 'paintlayer':
            raise ValueError('Alpha lock applies to paint layers only.')
        if 'style' in params:
            if not node.type().endswith('layer'):
                raise ValueError('A layer style goes on a layer, not a mask.')
            layer_style.validate(params['style'])
        if params.get('clip'):
            parent = node.parentNode()
            if (parent is None or parent.uniqueId().toString() not in session.get('clip_groups', set())
                    or self._craft_clip_group(session, node) is not None):
                raise ValueError('A layer clips live only above the base of a clip group. Use create_layer with clip_to instead.')

    def _craft_settings(self, node):
        return {'opacity': node.opacity(), 'visible': node.visible(), 'blend_mode': node.blendingMode(),
                'alpha_lock': bool(node.alphaLocked()) if node.type() == 'paintlayer' else None,
                'clip': bool(node.inheritAlpha()), 'name': node.name()}

    def _craft_set(self, doc, session, params):
        node = self._creative_node(doc, params['layer_id'])
        prior = self._craft_settings(node)
        if 'style' in params:
            prior['style'] = node.layerStyleToAsl()       # '' when the layer had no style
        self._craft_apply(node, params)
        doc.refreshProjection()
        return prior

    def _craft_restore(self, node, prior):
        """Undo a set_layer pass: put back every recorded setting."""
        node.setOpacity(prior['opacity'])
        node.setVisible(prior['visible'])
        if prior.get('blend_mode') is not None:
            node.setBlendingMode(prior['blend_mode'])
        if prior.get('alpha_lock') is not None:
            node.setAlphaLocked(prior['alpha_lock'])
        if prior.get('clip') is not None:
            node.setInheritAlpha(prior['clip'])
        if prior.get('name') is not None:
            node.setName(prior['name'])
        if 'style' in prior:
            self._craft_style(node, prior['style'] or layer_style.cleared())
