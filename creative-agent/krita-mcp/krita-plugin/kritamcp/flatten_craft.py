# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""flatten_passes: some passes of one move flattened into one paint layer (Refine to the goal's layers, the artist
2026-10-25: after one refine step a 6000 x 4500 painting had 146 layers, 21 "Refine 1" + 50 "Refine 1 accents" + 18
"Refine 2" + 45 "Refine 2 accents", and Krita reported 10.1 GiB: "why does it suck at layer management still").

Each finish pass is a group of two baked layers (blend, strokes) and each accents pass a group of up to four (darks,
detail, lights, bloom), every one written over whole work squares, mostly transparent. At the end of a refine round the
companion flattens the round's finish passes into one layer and its accents passes into another: what Krita shows is
the same (every layer inside is a normal-blend paint layer, each group composited isolated at its own opacity, the passes
in their stacking order), the new layer is written only in the 64-px squares that hold paint, and the passes' groups go.

Runs inside the creative operation journal (creative_tools.py) as merge_passes does: one call records one pass in the
move's stage, the flattened passes point to it (`merged_into`) and leave the history, so the move's Undo (rejecting the
stage) hides the flattened layer. Only passes of the same stage, adjacent in one parent, unrejected, shown and of kinds
finish, accents or flatten_passes flatten; anything else is refused before anything changes.
"""
import numpy as np
from .creative_validation import fields, text

FLATTEN_FIELDS = ('pass_ids', 'name', 'stage_id', 'expected_revision')
KINDS = ('finish', 'accents', 'flatten_passes')
MOST = 200                                     # passes one call flattens at most
TILE = 512                                     # composited square by square
WRITE = 64                                     # and written only where a square of this side holds paint


def over(dst, src):
    """`src` over `dst`, both float RGBA 0-1 with straight alpha (BGR order kept), in place into dst."""
    a, b = src[..., 3:4], dst[..., 3:4]
    alpha = a + b * (1 - a)
    dst[..., :3] = np.where(alpha > 0, (src[..., :3] * a + dst[..., :3] * b * (1 - a)) / np.maximum(alpha, 1e-6), 0)
    dst[..., 3:4] = alpha
    return dst


class FlattenCraft:
    def _flatten_nodes(self, doc, session, params):
        """The listed passes' nodes, bottom to top, checked (see the module header); the entries they belong to."""
        ids = params['pass_ids']
        stage = params['stage_id']
        entries = {}
        for entry in session.get('passes', []):
            if entry['id'] in ids:
                entries[entry['id']] = entry
        missing = [i for i in ids if i not in entries]
        if missing:
            raise ValueError('Unknown pass: ' + ', '.join(missing[:3]))
        nodes = {}
        for identifier in ids:
            entry = entries[identifier]
            if entry.get('merged_into') or entry.get('rejected'):
                raise ValueError('Pass %s is no longer on its own layer: nothing was flattened.' % identifier)
            if entry.get('kind') not in KINDS or entry.get('stage_id') != stage:
                raise ValueError('Only finish and accents passes of this move flatten: %s is not one.' % identifier)
            node = self._creative_node(doc, entry['layer_id'])
            if not node.visible() or (hasattr(node, 'blendingMode') and node.blendingMode() not in ('normal', 'pass through')):
                raise ValueError('Pass %s was changed (hidden or blended): nothing was flattened.' % identifier)
            self._flatten_check(node)
            nodes[entry['layer_id']] = node
        parents = {node.parentNode().uniqueId().toString() for node in nodes.values()}
        if len(parents) != 1:
            raise ValueError('The passes are in different groups: nothing was flattened.')
        siblings = next(iter(nodes.values())).parentNode().childNodes()
        at = [i for i, child in enumerate(siblings) if child.uniqueId().toString() in nodes]
        if at[-1] - at[0] + 1 != len(at):
            raise ValueError('Other layers lie between the passes: nothing was flattened.')
        return [siblings[i] for i in at], list(entries.values())

    def _flatten_check(self, node):
        for child in node.childNodes():
            if child.type() == 'grouplayer':
                self._flatten_check(child)
            elif child.type() != 'paintlayer' or (hasattr(child, 'blendingMode') and child.blendingMode() != 'normal') or child.childNodes():
                raise ValueError('A pass holds a layer that does not flatten (%s): nothing was flattened.' % child.name())

    def _flatten_validate(self, doc, session, params):
        fields(params, FLATTEN_FIELDS, ('pass_ids', 'name', 'stage_id'))
        text(params['name'], 'name', 120)
        text(params['stage_id'], 'stage_id', 100)
        ids = params['pass_ids']
        if not isinstance(ids, list) or not 1 <= len(ids) <= MOST or len(set(ids)) != len(ids):
            raise ValueError('pass_ids is a list of 1-%d different pass ids.' % MOST)
        for identifier in ids:
            text(identifier, 'pass id', 200)
        self._creative_passes(session)
        self._flatten_nodes(doc, session, params)
        self._craft_check_rgba(doc, 'Flattening passes')

    def _flatten_pixels(self, node, rect):
        """What Krita shows of `node` alone in canvas rect [x, y, w, h]: float RGBA 0-1, straight alpha."""
        x, y, w, h = rect
        if node.type() == 'grouplayer':
            out = np.zeros((h, w, 4), np.float32)
            for child in node.childNodes():
                if child.visible():
                    over(out, self._flatten_pixels(child, rect))
        else:
            out = np.frombuffer(bytes(node.pixelData(x, y, w, h)), np.uint8).reshape(h, w, 4).astype(np.float32) / 255
        out[..., 3] *= node.opacity() / 255.0
        return out

    def _flatten_apply(self, doc, session, params):
        from .qt_compat import QCoreApplication
        width, height = doc.width(), doc.height()
        nodes, entries = self._flatten_nodes(doc, session, params)
        layer = doc.createNode(params['name'], 'paintlayer')
        if layer is None or not self._craft_insert_below(doc, nodes[0], layer):
            raise RuntimeError('Krita could not add the flattened layer.')
        layer.setBlendingMode('normal')
        bounds = [b for b in (self._flatten_bounds(node, width, height) for node in nodes) if b]
        written = 0
        if bounds:
            x0, y0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
            x1, y1 = max(b[0] + b[2] for b in bounds), max(b[1] + b[3] for b in bounds)
            for ty in range(y0, y1, TILE):
                for tx in range(x0, x1, TILE):
                    rect = [tx, ty, min(TILE, x1 - tx), min(TILE, y1 - ty)]
                    out = np.zeros((rect[3], rect[2], 4), np.float32)
                    for node in nodes:
                        over(out, self._flatten_pixels(node, rect))
                    pixels = np.clip(np.round(out * 255), 0, 255).astype(np.uint8)
                    for sy in range(0, rect[3], WRITE):
                        for sx in range(0, rect[2], WRITE):
                            part = pixels[sy:sy + WRITE, sx:sx + WRITE]
                            if part[..., 3].any():
                                if layer.setPixelData(np.ascontiguousarray(part).tobytes(), tx + sx, ty + sy, part.shape[1], part.shape[0]) is False:
                                    raise RuntimeError('Krita rejected the flattened layer pixels.')
                                written += 1
                    QCoreApplication.processEvents()
        removed = 0
        gone = set()
        for node in nodes:
            stack = [node]
            while stack:
                current = stack.pop()
                gone.add(current.uniqueId().toString()); removed += 1
                stack.extend(current.childNodes())
            node.remove()
        doc.refreshProjection()
        identifier = layer.uniqueId().toString()
        session['layers'] -= gone
        session['layers'].add(identifier)
        operation = session.get('operation_id')
        for entry in entries:
            entry['merged_into'] = operation
        return {'layer_id': identifier, 'layer_type': 'merged', 'flattened_passes': len(nodes), 'removed_layers': removed,
                'written_squares': written, 'merged_pass_ids': [entry['id'] for entry in entries]}

    @staticmethod
    def _flatten_bounds(node, width, height):
        """The node's bounds on the canvas, or the canvas when Krita does not say."""
        bounds = node.bounds() if hasattr(node, 'bounds') else None
        if bounds is None:
            return [0, 0, width, height]
        x, y = max(0, bounds.x()), max(0, bounds.y())
        r, b = min(width, bounds.x() + bounds.width()), min(height, bounds.y() + bounds.height())
        return [x, y, r - x, b - y] if r > x and b > y else None
