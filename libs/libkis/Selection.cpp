/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "Selection.h"

#include <KoColorSpace.h>
#include <kis_selection.h>
#include <kis_pixel_selection.h>
#include <kis_paint_device.h>
#include <kis_selection_filters.h>
#include <kis_painter.h>
#include <kis_node.h>
#include <kis_clipboard.h>
#include <QByteArray>
#include <kis_tool_utils.h>
#include <kis_paint_layer.h>
#include <kis_image.h>

#include <kis_debug.h>
#include <Node.h>
#include <KisFeatureList.h>
#include <KisFeatureProtection.h>
#include "DocumentHistory.h"

struct Selection::Private {
    Private() {}
    KisSelectionSP selection;
};

Selection::Selection(KisSelectionSP selection, QObject *parent)
    : QObject(parent)
    , d(new Private)
{
    d->selection = selection;
}


Selection::Selection(QObject *parent)
    : QObject(parent)
    , d(new Private)
{
    d->selection = new KisSelection();
}

Selection::~Selection()
{
    delete d;
}

/// An inverted selection (or one that is selected by default) has no bounds to contract or resize.
static bool isUnbounded(const KisSelectionSP &selection)
{
    return selection->pixelSelection()->defaultPixel().opacityU8() != 0;
}

void Selection::clipTo(const QRect &rect)
{
    KisPixelSelectionSP pixels = d->selection->pixelSelection();
    KisPixelSelectionSP keep = new KisPixelSelection(pixels->defaultBounds());
    keep->select(rect);
    pixels->applySelection(keep, SELECTION_INTERSECT);
}

bool Selection::operator==(const Selection &other) const
{
    return (d->selection == other.d->selection);
}

bool Selection::operator!=(const Selection &other) const
{
    return !(operator==(other));
}

Selection *Selection::duplicate() const
{
    return new Selection(d->selection ? new KisSelection(*d->selection)
                         : new KisSelection());
}

int Selection::width() const
{
    if (!d->selection) return 0;
    return d->selection->selectedExactRect().width();
}

int Selection::height() const
{
    if (!d->selection) return 0;
    return d->selection->selectedExactRect().height();
}

int Selection::x() const
{
    if (!d->selection) return 0;
    int xPos = d->selection->x();
    if (d->selection->hasNonEmptyPixelSelection()) {
        xPos = d->selection->selectedExactRect().x();
    }
    return xPos;
}

int Selection::y() const
{
    if (!d->selection) return 0;
    int yPos = d->selection->y();
    if (d->selection->hasNonEmptyPixelSelection()) {
        yPos = d->selection->selectedExactRect().y();
    }
    return yPos;
}

void Selection::move(int x, int y)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->moveTo(QPoint(x, y));
}


void Selection::clear()
{
    if (!d->selection) return;
    d->selection->clear();
}

void Selection::contract(int value)
{
    // Krita Agent: it selected a rectangle (adding it to what was selected, so nothing was ever removed). It now
    // keeps what lies inside the rectangle that is \p value narrower and lower than the selection's bounds, with the
    // same top-left corner, as documented: the shape and the partial values inside are kept, the rest is dropped.
    if (!d->selection || value <= 0) return;
    if (isUnbounded(d->selection)) {
        warnScript << "Selection.contract(): refused, an inverted selection has no bounds";
        return;
    }
    const QRect bounds = d->selection->selectedExactRect();
    if (bounds.isEmpty()) return;
    clipTo(QRect(bounds.x(), bounds.y(), qMax(0, bounds.width() - value), qMax(0, bounds.height() - value)));
}

void Selection::copy(Node *node)
{
    if (!node) return;
    if (!d->selection) return;
    if (node->node()->exactBounds().isEmpty()) return;
    if (!node->node()->hasEditablePaintDevice()) return;

    KisImageSP image = node->node()->image();
    if (!image) return;

    KisPaintDeviceSP dev(new KisPaintDevice(*node->node()->paintDevice()));
    KisToolUtils::trimDeviceForClipboard(image, dev, d->selection);

    KisNodeSP newNode = new KisPaintLayer(image, "selection", OPACITY_OPAQUE_U8, dev);
    KisNodeList nodes{newNode};

    KisImageSP tempImage = KisToolUtils::buildImageForClipboard(image, nodes);
    KisClipboard::instance()->setLayers(nodes, tempImage, d->selection->selectedExactRect());
}

void Selection::cut(Node* node)
{
    if (!node) return;
    if (!d->selection) return;
    if (node->node()->exactBounds().isEmpty()) return;
    if (!node->node()->hasEditablePaintDevice()) return;
    KisPaintDeviceSP dev = node->node()->paintDevice();
    // Krita Agent (krita-fork 6.5): an agent's cut leaves the protected features alone. A cut that is refused for
    // its layer's sake leaves the clipboard as it was, so this comes before the copy.
    KisSelectionSP selection = d->selection;
    if (KisImageSP protectedBy = DocumentHistory::protectionFor(node->node()->image())) {
        if (!KisFeatureProtection::whyNotCanvasAligned(protectedBy, node->node()).isEmpty()) return;
        protectedBy->featureList()->recordKeptOut(KisFeatureProtection::keptOutOf(protectedBy, selection->selectedExactRect(), selection));
        selection = KisFeatureProtection::guardSelection(protectedBy, selection);
    }
    copy(node);
    dev->clearSelection(selection);
    node->node()->setDirty(d->selection->selectedExactRect());
}

void Selection::paste(Node *destination, int x, int y)
{
    if (!destination) return;
    if (!d->selection) return;
    if (!KisClipboard::instance()->hasClip()) return;

    KisDefaultBoundsBaseSP defaultBounds = destination->node()->paintDevice()->defaultBounds();
    KisPaintDeviceSP src = KisClipboard::instance()->clip(defaultBounds, false);
    KisPaintDeviceSP dst = destination->node()->paintDevice();
    if (!dst || !src) return;
    KisSelectionSP selection = d->selection;
    if (KisImageSP protectedBy = DocumentHistory::protectionFor(destination->node()->image())) {
        if (!KisFeatureProtection::whyNotCanvasAligned(protectedBy, destination->node()).isEmpty()) return;
        protectedBy->featureList()->recordKeptOut(KisFeatureProtection::keptOutOf(protectedBy, selection->selectedExactRect(), selection));
        selection = KisFeatureProtection::guardSelection(protectedBy, selection);
    }
    KisPainter::copyAreaOptimized(QPoint(x, y),
                                  src,
                                  dst,
                                  src->exactBounds(),
                                  selection);
    destination->node()->setDirty();
}

void Selection::erode()
{
    if (!d->selection) return;
    KisErodeSelectionFilter esf;
    QRect rc = esf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    esf.process(d->selection->pixelSelection(), rc);
}

void Selection::dilate()
{
    if (!d->selection) return;
    KisDilateSelectionFilter dsf;
    QRect rc = dsf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    dsf.process(d->selection->pixelSelection(), rc);
}

void Selection::border(int xRadius, int yRadius)
{
    if (!d->selection) return;
    KisBorderSelectionFilter sf(xRadius, yRadius, true);
    QRect rc = sf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    sf.process(d->selection->pixelSelection(), rc);
}

void Selection::feather(int radius)
{
    if (!d->selection) return;
    KisFeatherSelectionFilter fsf(radius);
    QRect rc = fsf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    fsf.process(d->selection->pixelSelection(), rc);
}

void Selection::grow(int xradius, int yradius)
{
    if (!d->selection) return;
    KisGrowSelectionFilter gsf(xradius, yradius);
    QRect rc = gsf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    gsf.process(d->selection->pixelSelection(), rc);
}


void Selection::shrink(int xRadius, int yRadius, bool edgeLock)
{
    if (!d->selection) return;
    KisShrinkSelectionFilter sf(xRadius, yRadius, edgeLock);
    QRect rc = sf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    sf.process(d->selection->pixelSelection(), rc);
}

void Selection::smooth()
{
    if (!d->selection) return;
    KisSmoothSelectionFilter sf;
    QRect rc = sf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    sf.process(d->selection->pixelSelection(), rc);
}


void Selection::invert()
{
    if (!d->selection) return;
    KisInvertSelectionFilter sf;
    QRect rc = sf.changeRect(d->selection->selectedExactRect(), d->selection->pixelSelection()->defaultBounds());
    sf.process(d->selection->pixelSelection(), rc);
}

void Selection::resize(int w, int h)
{
    // Krita Agent: it selected a rectangle of the new size, adding it to what was selected. The bounds now become
    // exactly w x h from the same top-left corner: what lies outside is dropped, and where the box grew, the added
    // area is selected in full (an empty selection becomes the whole rectangle).
    if (!d->selection || w < 0 || h < 0) return;
    if (isUnbounded(d->selection)) {
        warnScript << "Selection.resize(): refused, an inverted selection has no bounds";
        return;
    }
    const QRect bounds = d->selection->selectedExactRect();
    const QRect box(bounds.isEmpty() ? QPoint(0, 0) : bounds.topLeft(), QSize(w, h));
    if (bounds.isEmpty()) {
        if (!box.isEmpty()) d->selection->pixelSelection()->select(box);
        return;
    }
    clipTo(box);
    KisPixelSelectionSP pixels = d->selection->pixelSelection();
    const QRegion added = QRegion(box).subtracted(QRegion(bounds));
    for (const QRect &rect : added) {
        pixels->select(rect);
    }
}

void Selection::select(int x, int y, int w, int h, int value)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->select(QRect(x, y, w, h), value);
}

void Selection::selectAll(Node *node, int value)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->select(node->node()->exactBounds(), value);
}

void Selection::replace(Selection *selection)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->applySelection(selection->selection()->pixelSelection(), SELECTION_REPLACE);
}

void Selection::add(Selection *selection)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->applySelection(selection->selection()->pixelSelection(), SELECTION_ADD);
}

void Selection::subtract(Selection *selection)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->applySelection(selection->selection()->pixelSelection(), SELECTION_SUBTRACT);
}

void Selection::intersect(Selection *selection)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->applySelection(selection->selection()->pixelSelection(), SELECTION_INTERSECT);
}

void Selection::symmetricdifference(Selection *selection)
{
    if (!d->selection) return;
    d->selection->pixelSelection()->applySelection(selection->selection()->pixelSelection(), SELECTION_SYMMETRICDIFFERENCE);
}


QByteArray Selection::pixelData(int x, int y, int w, int h) const
{
    QByteArray ba;
    if (!d->selection) return ba;
    KisPaintDeviceSP dev = d->selection->projection();
    quint8 *data = new quint8[w * h];
    dev->readBytes(data, x, y, w, h);
    ba = QByteArray((const char*)data, (int)(w * h));
    delete[] data;
    return ba;
}

void Selection::setPixelData(QByteArray value, int x, int y, int w, int h)
{
    if (!d->selection) return;
    KisPixelSelectionSP dev = d->selection->pixelSelection();
    if (!dev) return;
    dev->writeBytes((const quint8*)value.constData(), x, y, w, h);
}

KisSelectionSP Selection::selection() const
{
    return d->selection;
}


