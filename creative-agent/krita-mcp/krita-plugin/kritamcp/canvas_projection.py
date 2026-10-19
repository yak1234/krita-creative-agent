"""Recompositing and reading the canvas by area: the fork's libkis calls where Krita has them, stock Krita's otherwise.

The fork (Krita master on Qt6, tasks 2.1 and 2.3 of openspec/changes/krita-fork) adds to libkis:
  Document.refreshProjection(QRect)   recomposite only that rect (clipped to the image), then wait
  Document.projection(QRect, float)   the rect read scaled by area averaging, Format_ARGB32 as projection(x, y, w, h)
  Node.setPixelData(...)              marks its own rect dirty, so waitForDone() is enough after it
Stock Krita 5.3.3 has the same method names with other overloads, so `hasattr` cannot tell them apart: the first call
with a QRect is tried, and SIP's TypeError on stock (no overload takes a QRect) is remembered per document class for
the rest of the process (a plugin reload starts over). The setPixelData change came with the region refresh (one fork
commit), so a document class that answered refreshProjection(QRect) is taken to dirty its writes too.

A region refresh prefers, in order:
  1. the fork's refreshProjection(QRect);
  2. on stock, the native helper's refresh_region when Krita loaded a protocol-7 helper (agent_accel.py) and
     HELPER_REGION_REFRESH is on, for a saved document only: the helper finds a document by its file, and '' would mean
     whichever one is active. The helper grows the rect by every effect that spreads a change outside it (filter masks,
     adjustment layers, layer styles, transform masks, clones), so the picture is what a whole refresh gives;
  3. the whole-image refreshProjection(), as before.
Callers pass a rect only where everything that changed lies inside it: a pass's own pixels on a layer whose settings
were already composited. Layer settings (opacity, blending, visibility), adding, moving or removing layers and masks
change the whole layer: those callers keep the whole-image refresh.
"""

_SUPPORTED = {}        # (document class, 'refresh' | 'scaled') -> True on the fork, False on stock
# Before protocol 7 the helper recomposited exactly the rect it was given, not the halo a filter mask or layer style
# spreads around it (the fork's review of the same call). Protocol 7 grows the rect by every layer's change rect, masks
# and styles included, and its self-test checks the result equals a whole refresh (region_refresh_selftest.cpp). An
# older helper is never asked: refresh_region needs protocol 7, so stock falls back to the whole refresh.
# Measured live on New Moscow (6000x4500, protocol 7, 19 October): the grown region is no faster than the whole refresh
# (medians 38, 42, 47 ms against 21-25 ms; once 11 against 27), since every effect in the document grows it and the
# graph walk costs too, so stock keeps the whole refresh. The fork's own region refresh is measured separately.
HELPER_REGION_REFRESH = False


def _qrect(x, y, w, h):
    """A QRect, or None where Qt has none (the plugin's tests without Qt): then only stock Krita's calls are made."""
    try:
        from .qt_compat import QRect
    except (ImportError, AttributeError):
        return None
    return QRect(int(x), int(y), int(w), int(h))


def _tried(doc, feature, call):
    """(True, answer) when the fork's overload answered, (False, None) on stock; learnt once per document class."""
    key = (type(doc), feature)
    if _SUPPORTED.get(key) is False:
        return False, None
    try:
        answer = call()
    except TypeError:                                  # SIP: no overload of that name takes these arguments
        _SUPPORTED[key] = False
        return False, None
    _SUPPORTED[key] = True
    return True, answer


def clip(rect, width, height):
    """rect [x, y, w, h] cut to a width x height canvas; w or h 0 when nothing of it is inside."""
    x, y, w, h = (int(v) for v in rect)
    left, top = max(0, x), max(0, y)
    return left, top, max(0, min(width, x + w) - left), max(0, min(height, y + h) - top)


def _helper_refresh(doc, rect):
    path = doc.fileName() if hasattr(doc, 'fileName') else ''
    if not path:
        return False
    try:
        from . import agent_accel
        refresh_region = agent_accel.refresh_region
    except (ImportError, AttributeError):
        return False
    return refresh_region(path, rect) is not None


def refresh(doc, rect=None):
    """Recomposite `rect` [x, y, w, h] of doc's image, or all of it for None. Returns how: 'fork', 'helper', 'full',
    or 'none' for a rect with nothing inside the canvas (nothing visible changed)."""
    if rect is None:
        doc.refreshProjection()
        return 'full'
    x, y, w, h = clip(rect, doc.width(), doc.height())
    if w <= 0 or h <= 0:
        return 'none'
    area = _qrect(x, y, w, h)
    if area is not None and _tried(doc, 'refresh', lambda: doc.refreshProjection(area))[0]:
        return 'fork'
    if HELPER_REGION_REFRESH and _helper_refresh(doc, (x, y, w, h)):
        return 'helper'
    doc.refreshProjection()
    return 'full'


def pixels_written(doc, rect):
    """After Node.setPixelData of `rect` on a layer whose settings are already composited. On the fork the write marked
    its rect dirty, so waiting is enough ('dirty'); until the fork is known, and on stock, `rect` is recomposited as
    refresh() does."""
    if _SUPPORTED.get((type(doc), 'refresh')):
        doc.waitForDone()
        return 'dirty'
    return refresh(doc, rect)


def read_scaled(doc, rect, scale):
    """rect [x, y, w, h] of the projection scaled by `scale` (below 1) in one read on the fork, without a full-size
    copy: round(w * scale) by round(h * scale), Format_ARGB32. None on stock, or for a null answer: the caller then
    reads full size and scales with Qt as before."""
    area = _qrect(*rect)
    if area is None:
        return None
    found, image = _tried(doc, 'scaled', lambda: doc.projection(area, float(scale)))
    return image if found and image is not None and not image.isNull() else None
