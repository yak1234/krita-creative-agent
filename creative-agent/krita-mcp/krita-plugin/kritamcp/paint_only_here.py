# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Paint only here (openspec element-scoped-painting, goals 1, 5 and 6; the artist, 2026-10-23).

The artist selects an area in Krita with any selection tool and presses Paint only here in the panel. While the area is
set, the agent may paint inside it only, and that is guaranteed, not advised: everything outside the area becomes one
protected feature of the fork (krita-fork 6.5), so Krita's own write paths (stroke jobs, fills, raw pixel writes, filters)
keep every agent write out of it, as they do for a feature the artist protects. The feature is the system's, not the
artist's: a transient feature (Document.setTransientFeature, kind "paint-only-here"), set and removed outside the undo
history (the artist's Undo and Redo never meet it, and setting it never clears their Redo) and never saved in a .kra;
hidden from the Protected list and from the painter's feature names (feature_guard); removed when the area is cleared or
the chat ends.

  * Exact at the edge: every pixel the selection leaves out is protected whole.
  * Soft inside it: the area's edge is softened over FEATHER pixels inside the selection (shrunk, feathered, never past it),
    so a scoped transfer fades out there instead of leaving a hard cut line. A stroke job is clipped by the soft band; a
    raw pixel write is kept out of every protected pixel, so it stays the few pixels inside.

One area per document at a time (a new one replaces it). The areas live in this process (AREAS, shared by the panel and the
bridge) and in the chat (the companion keeps the mask file in the chat folder's .shapes, so a resumed chat restores it).
ensure() puts the protection back right before an agent write when the document lost it (reverted, reopened, a plugin
reload); drop_stale() removes a protection no area holds.
"""
import os
import re
import struct
import zlib

SYSTEM_KIND = 'paint-only-here'
SYSTEM_NAME = 'Outside the Paint only here area'
FEATHER = 3
# "paint only in my selection", "paint the sky only inside the selection", "work only within this selection": one sentence.
PHRASE = re.compile(r'\b(paint|work|draw)\w*\b[^.?!]*\bonly\b[^.?!]*\b(in|inside|within)\s+(my|the|this)\s+selection\b', re.IGNORECASE)
FORK_ONLY = ('Paint only here needs our Krita (the fork) with transient features, which keeps the agent out of the rest of '
             'the painting without touching your Undo.')
# The companion's copy of an area's mask: the chat folder's .shapes/paint-only-<24 hex>.png (paint-only-here.ts adoptArea).
MASK_FILE = re.compile(r'^paint-only-[0-9a-f]{24}\.png$')
FOLDER_ONLY = "Paint only here reads its mask only from a chat folder's .shapes."

NO_SELECTION = 'Select the area first: draw around it with the Freehand Selection tool, then press Paint only here.'


def wants_area(text):
    """Whether a message asks to paint only inside the artist's selection."""
    return bool(PHRASE.search(text or ''))


def is_system_feature(feature):
    """The protection Paint only here owns: never listed for the artist or the painter."""
    try:
        return feature.kind() == SYSTEM_KIND
    except (AttributeError, RuntimeError):
        return False


def selection_bounds(selection, doc):
    """[x, y, w, h] of a selection cut to the canvas, or None when nothing is selected there."""
    if selection is None:
        return None
    left, top = max(0, selection.x()), max(0, selection.y())
    right, bottom = min(doc.width(), selection.x() + selection.width()), min(doc.height(), selection.y() + selection.height())
    return None if right <= left or bottom <= top else [left, top, right - left, bottom - top]


def outside_mask(doc, selection, make_selection, feather=FEATHER):
    """The protected mask: the whole canvas minus the area, the area's inner edge softened over `feather` pixels. The soft
    area is the selection shrunk, feathered and cut to the selection again, so the protection is whole wherever the
    selection is not. A selection thinner than the edge keeps its own pixels."""
    soft = selection.duplicate()
    if feather > 0:
        soft.shrink(feather, feather, False)
        soft.feather(feather)
        soft.intersect(selection)
        if soft.width() <= 0 or soft.height() <= 0:
            soft = selection.duplicate()
    outside = make_selection()
    outside.select(0, 0, doc.width(), doc.height(), 255)
    outside.subtract(soft)
    return outside


def encode_png(width, height, plane):
    """A grey 8-bit PNG, every row filter 0 (what shape_mask.read_png and the companion's decodePlane read fastest)."""
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    raw = b''.join(b'\x00' + plane[row * width:(row + 1) * width] for row in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def write_mask(area, path):
    """The area's mask (its bounds, one byte a pixel) as a PNG for the companion. Returns the path."""
    with open(path, 'wb') as handle:
        handle.write(encode_png(area['bounds'][2], area['bounds'][3], area['mask']))
    return path


def _same(left, right):
    try:
        return left is right or bool(left == right)
    except (RuntimeError, ReferenceError, TypeError):
        return False


class PaintOnlyHere:
    """The Paint only here areas of the open documents, and their protection in each."""

    def __init__(self, make_selection=None):
        self._areas = []                                  # [(document, {'bounds', 'mask', 'name'})]
        self._make = make_selection

    def _selection(self):
        if self._make is None:
            from krita import Selection
            self._make = Selection
        return self._make()

    @staticmethod
    def ready(doc):
        return all(hasattr(doc, name) for name in ('setTransientFeature', 'removeTransientFeature', 'feature'))

    def area(self, doc):
        return next((area for known, area in self._areas if _same(known, doc)), None)

    def present(self, doc):
        """Whether the document has the protection now."""
        feature = doc.feature(SYSTEM_NAME) if self.ready(doc) else None
        return feature is not None and is_system_feature(feature) and bool(feature.isProtected())

    def capture(self, doc, selection, name=None):
        """The artist's selection (its pixels, not its bounds) becomes the document's area, replacing any earlier one."""
        if not self.ready(doc):
            raise ValueError(FORK_ONLY)
        bounds = selection_bounds(selection, doc) if selection is not None else None
        mask = bytes(selection.pixelData(*bounds)) if bounds else b''
        if mask.count(0) == len(mask):                      # nothing selected (count runs in C, no copy)
            raise ValueError(NO_SELECTION)
        area = {'bounds': bounds, 'mask': mask, 'name': (str(name).strip()[:60] or None) if name else None}
        self._apply(doc, selection)
        self._areas = [(known, kept) for known, kept in self._areas if not _same(known, doc)] + [(doc, area)]
        return area

    def restore(self, doc, spec):
        """A resumed chat's area ({bounds, mask_path, name}, the companion's copy of the mask) back on the document."""
        from .shape_mask import read_png
        bounds = [int(v) for v in spec['bounds']]
        path = spec['mask_path']
        if (not isinstance(path, str) or not os.path.isabs(path) or not MASK_FILE.match(os.path.basename(path))
                or os.path.basename(os.path.dirname(path)) != '.shapes' or os.path.islink(path)):
            raise ValueError(FOLDER_ONLY)
        with open(path, 'rb') as handle:
            _w, _h, plane = read_png(handle.read(), bounds[2:])
        return self.capture(doc, self._from_mask(bounds, plane), spec.get('name'))

    def _from_mask(self, bounds, mask):
        selection = self._selection()
        selection.setPixelData(mask, *bounds)
        return selection

    def _apply(self, doc, selection):
        # Set in place (a transient feature of that name is replaced), outside the undo history.
        if doc.setTransientFeature(SYSTEM_NAME, SYSTEM_KIND, outside_mask(doc, selection, self._selection), True) is None:
            raise ValueError("Krita would not keep the agent out of the rest of the painting: a feature called '%s' already exists. "
                             'Rename it, then press Paint only here again.' % SYSTEM_NAME)

    def _remove(self, doc):
        feature = doc.feature(SYSTEM_NAME)
        return feature is not None and is_system_feature(feature) and bool(doc.removeTransientFeature(SYSTEM_NAME))

    def clear(self, doc):
        """The area is cleared (the chip's ✕, or the chat ended): the protection goes."""
        self._areas = [(known, area) for known, area in self._areas if not _same(known, doc)]
        return self._remove(doc) if self.ready(doc) else False

    def clear_all(self):
        """The chat ended: the area goes from every document that has one, open or not active."""
        areas, self._areas = self._areas, []
        for doc, _area in areas:
            try:
                if self.ready(doc): self._remove(doc)
            except (RuntimeError, ReferenceError, AttributeError):
                pass                                      # a document Krita has closed

    def ensure(self, doc):
        """Right before an agent write (the bridge, never the panel's poll): the document's area is protected, put back if the
        document lost it. True when it was put back."""
        area = self.area(doc)
        if area is None or not self.ready(doc) or self.present(doc):
            return False
        self._apply(doc, self._from_mask(area['bounds'], area['mask']))
        return True

    def drop_stale(self, doc):
        """A protection left in a document no area holds (an earlier chat, a Krita that closed mid-chat) goes."""
        if self.area(doc) is not None or not self.ready(doc):
            return False
        return self._remove(doc)


# The panel and the bridge run in Krita's one process: one registry.
AREAS = PaintOnlyHere()
