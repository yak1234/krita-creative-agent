/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestNodeAgentTools.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include "AgentCraftTestUtils.h"

#include <QColor>
#include <QVariantList>
#include <QVariantMap>

#include <Document.h>
#include <Node.h>
#include <Selection.h>

#include <KisResourceModel.h>
#include <KisResourceTypes.h>
#include <KoColor.h>
#include <KoAbstractGradient.h>
#include <KoCanvasResourcesIds.h>
#include <KoLocalStrokeCanvasResources.h>
#include <kis_group_layer.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_command_utils.h>
#include <kis_processing_applicator.h>
#include <kis_stroke_strategy_undo_command_based.h>
#include <kis_transaction.h>
#include <processing/KisToolFunctions.h>

#include <QElapsedTimer>
#include <QSignalSpy>
#include <QThread>

#include <atomic>
#include <functional>
#include <limits>

using namespace AgentCraftTest;

namespace {

/// A document with a transparent paint layer "paint" on an opaque white "background", and libkis wrappers.
struct ToolDocument : public UndoableDocument {
    KisPaintLayerSP background;
    KisPaintLayerSP paint;
    QScopedPointer<Node> paintNode;

    explicit ToolDocument(const QSize &size = QSize(120, 100))
        : UndoableDocument(size)
    {
        const KoColorSpace *cs = image->colorSpace();
        background = new KisPaintLayer(image, "background", OPACITY_OPAQUE_U8);
        background->paintDevice()->fill(image->bounds(), KoColor(Qt::white, cs));
        image->addNode(background);
        paint = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        image->addNode(paint);
        paintNode.reset(Node::createNode(image, paint));
        render();
    }

    QColor at(KisPaintLayerSP layer, int x, int y) const
    {
        QColor color;
        layer->paintDevice()->pixel(x, y, &color);
        return color;
    }

    QColor at(int x, int y) const
    {
        return at(paint, x, y);
    }

    /// The number of pixels of the paint layer whose alpha is above zero.
    int paintedPixels() const
    {
        int count = 0;
        for (int y = 0; y < image->height(); y++) {
            for (int x = 0; x < image->width(); x++) {
                if (at(x, y).alpha() > 0) count++;
            }
        }
        return count;
    }

    QByteArray bytes(KisPaintLayerSP layer) const
    {
        QByteArray data(image->width() * image->height() * layer->paintDevice()->pixelSize(), 0);
        layer->paintDevice()->readBytes(reinterpret_cast<quint8 *>(data.data()), image->bounds());
        return data;
    }
};

/// Draws the outline of \p rect, \p width pixels wide, in \p color on \p layer.
void outline(KisPaintLayerSP layer, const QRect &rect, const QColor &color, int width = 2)
{
    const KoColor c(color, layer->paintDevice()->colorSpace());
    KisPaintDeviceSP device = layer->paintDevice();
    device->fill(QRect(rect.left(), rect.top(), rect.width(), width), c);
    device->fill(QRect(rect.left(), rect.bottom() - width + 1, rect.width(), width), c);
    device->fill(QRect(rect.left(), rect.top(), width, rect.height()), c);
    device->fill(QRect(rect.right() - width + 1, rect.top(), width, rect.height()), c);
}

bool near(const QColor &a, const QColor &b, int tolerance)
{
    return qAbs(a.red() - b.red()) <= tolerance && qAbs(a.green() - b.green()) <= tolerance
        && qAbs(a.blue() - b.blue()) <= tolerance && qAbs(a.alpha() - b.alpha()) <= tolerance;
}

QString describe(const QColor &c)
{
    return QString("rgba(%1,%2,%3,%4)").arg(c.red()).arg(c.green()).arg(c.blue()).arg(c.alpha());
}

#define QVERIFY_NEAR(actual, expected, tolerance)                                                                    \
    QVERIFY2(near((actual), (expected), (tolerance)),                                                               \
             qPrintable(QString("%1 is %2, expected %3").arg(#actual, describe(actual), describe(expected))))

} // namespace

void TestNodeAgentTools::testFillStopsAtContour()
{
    ToolDocument d;
    outline(d.paint, QRect(20, 20, 60, 50), Qt::black);
    d.render();
    const int undoBefore = d.undoCount();

    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red)));
    d.settle();

    QVERIFY_NEAR(d.at(50, 45), QColor(Qt::red), 0);
    QVERIFY_NEAR(d.at(23, 23), QColor(Qt::red), 0);   // inside, by the contour
    QVERIFY_NEAR(d.at(20, 20), QColor(Qt::black), 0); // the contour itself
    QCOMPARE(d.at(10, 10).alpha(), 0);                // outside
    QCOMPARE(d.at(100, 90).alpha(), 0);

    // One named step, and undoing it restores the layer.
    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Flood Fill"));
    d.undo();
    QCOMPARE(d.at(50, 45).alpha(), 0);
    QVERIFY_NEAR(d.at(20, 20), QColor(Qt::black), 0);

    // The step can be named.
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::blue), {{"name", "Fill the box"}}));
    d.settle();
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Fill the box"));
}

void TestNodeAgentTools::testFillThresholdChangesTheArea()
{
    // Left half one grey, right half a slightly lighter grey.
    ToolDocument d;
    const KoColorSpace *cs = d.image->colorSpace();
    d.paint->paintDevice()->fill(QRect(0, 0, 60, 100), KoColor(QColor(100, 100, 100), cs));
    d.paint->paintDevice()->fill(QRect(60, 0, 60, 100), KoColor(QColor(130, 130, 130), cs));
    d.render();

    // A low threshold stops at the step between the greys.
    QVERIFY(d.paintNode->fill(10, 50, QColor(Qt::red), {{"threshold", 2}}));
    d.settle();
    QVERIFY_NEAR(d.at(10, 50), QColor(Qt::red), 0);
    QVERIFY_NEAR(d.at(90, 50), QColor(130, 130, 130), 0);
    d.undo();
    QVERIFY_NEAR(d.at(10, 50), QColor(100, 100, 100), 0);

    // A high one crosses it.
    QVERIFY(d.paintNode->fill(10, 50, QColor(Qt::red), {{"threshold", 60}}));
    d.settle();
    QVERIFY_NEAR(d.at(10, 50), QColor(Qt::red), 0);
    QVERIFY_NEAR(d.at(90, 50), QColor(Qt::red), 0);
}

void TestNodeAgentTools::testFillSamplesAllLayers()
{
    // The contour is on another layer; the fill goes into the empty paint layer.
    ToolDocument d;
    KisPaintLayerSP lines = new KisPaintLayer(d.image, "lines", OPACITY_OPAQUE_U8);
    d.image->addNode(lines);
    outline(lines, QRect(20, 20, 60, 50), Qt::black);
    d.render();

    // Sampling this layer: it is empty, so the whole layer fills.
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red), {{"sample", "layer"}}));
    d.settle();
    QCOMPARE(d.paintedPixels(), d.image->width() * d.image->height());
    d.undo();
    QCOMPARE(d.paintedPixels(), 0);

    // Sampling all layers: the fill stops at the other layer's contour.
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red), {{"sample", "all"}}));
    d.settle();
    QVERIFY_NEAR(d.at(50, 45), QColor(Qt::red), 0);
    QCOMPARE(d.at(10, 10).alpha(), 0);
    QCOMPARE(d.at(20, 20).alpha(), 0); // under the contour

    // Sampling colour-labelled layers: only the labelled lines count.
    d.undo();
    lines->setColorLabelIndex(3);
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::green), {{"sample", "labels"}, {"labels", QVariantList{QVariant(3)}}}));
    d.settle();
    QVERIFY_NEAR(d.at(50, 45), QColor(Qt::green), 0);
    QCOMPARE(d.at(10, 10).alpha(), 0);
}

void TestNodeAgentTools::testFillSimilarColours()
{
    // Two separate black boxes; filling similar colours reaches both, contiguous only one.
    ToolDocument d;
    const KoColorSpace *cs = d.image->colorSpace();
    d.paint->paintDevice()->fill(QRect(10, 10, 20, 20), KoColor(Qt::black, cs));
    d.paint->paintDevice()->fill(QRect(70, 50, 20, 20), KoColor(Qt::black, cs));
    d.render();

    QVERIFY(d.paintNode->fill(15, 15, QColor(Qt::red)));
    d.settle();
    QVERIFY_NEAR(d.at(15, 15), QColor(Qt::red), 0);
    QVERIFY_NEAR(d.at(75, 55), QColor(Qt::black), 0);
    d.undo();

    QVERIFY(d.paintNode->fill(15, 15, QColor(Qt::red), {{"mode", "similar"}}));
    d.settle();
    QVERIFY_NEAR(d.at(15, 15), QColor(Qt::red), 0);
    QVERIFY_NEAR(d.at(75, 55), QColor(Qt::red), 0);
    QCOMPARE(d.at(50, 40).alpha(), 0);
}

void TestNodeAgentTools::testFillInsideSelectionOnly()
{
    ToolDocument d;
    Selection area;
    area.select(10, 10, 30, 20, 255);

    // A contiguous fill of the empty layer stays inside the given selection.
    QVERIFY(d.paintNode->fill(15, 15, QColor(Qt::red), QVariantMap(), &area));
    d.settle();
    QVERIFY_NEAR(d.at(15, 15), QColor(Qt::red), 0);
    QVERIFY_NEAR(d.at(39, 29), QColor(Qt::red), 0);
    QCOMPARE(d.at(41, 15).alpha(), 0);
    QCOMPARE(d.paintedPixels(), 30 * 20);
    d.undo();

    // Filling the selection fills all of it, wherever the point is.
    QVERIFY(d.paintNode->fill(100, 90, QColor(Qt::blue), {{"mode", "selection"}}, &area));
    d.settle();
    QCOMPARE(d.paintedPixels(), 30 * 20);
    QVERIFY_NEAR(d.at(20, 20), QColor(Qt::blue), 0);
}

void TestNodeAgentTools::testEncloseAndFillFillsEnclosedRegions()
{
    // Two closed boxes; the enclosing area covers only the left one.
    ToolDocument d;
    outline(d.paint, QRect(10, 20, 30, 30), Qt::black);
    outline(d.paint, QRect(70, 20, 30, 30), Qt::black);
    d.render();
    const int undoBefore = d.undoCount();

    Selection area;
    area.select(5, 15, 45, 45, 255);
    QVERIFY(d.paintNode->encloseAndFill(&area, QColor(Qt::red),
                                        {{"regions", "transparent"}, {"includeContourRegions", false}}));
    d.settle();

    QVERIFY_NEAR(d.at(25, 35), QColor(Qt::red), 0);   // inside the enclosed box
    QVERIFY_NEAR(d.at(10, 20), QColor(Qt::black), 0); // its contour
    QCOMPARE(d.at(85, 35).alpha(), 0);                // the other box, outside the area
    QCOMPARE(d.at(5, 5).alpha(), 0);                  // outside both
    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Enclose and Fill"));

    d.undo();
    QCOMPARE(d.at(25, 35).alpha(), 0);
}

void TestNodeAgentTools::testLinearGradientEndpoints()
{
    ToolDocument d;
    const int undoBefore = d.undoCount();
    const QVariantList colors({QColor(Qt::red), QColor(Qt::blue)});

    QVERIFY(d.paintNode->gradient(QPointF(10, 50), QPointF(109, 50), {{"colors", colors}}));
    d.settle();

    // Before the start, the start colour; after the end, the end colour; halfway, the mix.
    QVERIFY_NEAR(d.at(0, 10), QColor(Qt::red), 2);
    QVERIFY_NEAR(d.at(10, 90), QColor(Qt::red), 3);
    QVERIFY_NEAR(d.at(119, 0), QColor(Qt::blue), 2);
    const QColor middle = d.at(60, 50);
    QVERIFY2(middle.red() > 90 && middle.red() < 165 && middle.blue() > 90 && middle.blue() < 165,
             qPrintable(describe(middle)));
    QCOMPARE(middle.green(), 0);
    QCOMPARE(d.at(60, 50), d.at(60, 0)); // a linear gradient is the same along a column

    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Gradient"));
    d.undo();
    QCOMPARE(d.paintedPixels(), 0);

    // Reversed, the ends swap.
    QVERIFY(d.paintNode->gradient(QPointF(10, 50), QPointF(109, 50), {{"colors", colors}, {"reverse", true}}));
    d.settle();
    QVERIFY_NEAR(d.at(0, 10), QColor(Qt::blue), 2);
    QVERIFY_NEAR(d.at(119, 0), QColor(Qt::red), 2);
}

void TestNodeAgentTools::testRadialGradientInSelection()
{
    ToolDocument d;
    Selection left;
    left.select(0, 0, 60, 100, 255);
    const QVariantList colors({QColor(Qt::white), QColor(Qt::black)});

    QVERIFY(d.paintNode->gradient(QPointF(40, 50), QPointF(40, 80),
                                  {{"shape", "radial"}, {"colors", colors}, {"dither", false}}, &left));
    d.settle();

    QVERIFY_NEAR(d.at(40, 50), QColor(Qt::white), 3); // the centre
    QVERIFY_NEAR(d.at(2, 2), QColor(Qt::black), 2);   // beyond the radius
    const QColor ring = d.at(40, 65);                  // halfway out
    QVERIFY2(ring.red() > 90 && ring.red() < 165, qPrintable(describe(ring)));
    QCOMPARE(d.at(40, 35), d.at(55, 50)); // the same distance from the centre, the same colour
    QCOMPARE(d.at(61, 50).alpha(), 0);    // outside the selection
    QCOMPARE(d.at(119, 99).alpha(), 0);
}

namespace {

/// \p gradient with its foreground and background stops in \p foreground and \p background.
KoAbstractGradientSP baked(KoAbstractGradientSP gradient, const QColor &foreground, const QColor &background)
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    QSharedPointer<KoLocalStrokeCanvasResources> colors(new KoLocalStrokeCanvasResources());
    colors->storeResource(KoCanvasResource::ForegroundColor, QVariant::fromValue(KoColor(foreground, cs)));
    colors->storeResource(KoCanvasResource::BackgroundColor, QVariant::fromValue(KoColor(background, cs)));
    return gradient->cloneAndBakeVariableColors(colors);
}

QColor colorAt(KoAbstractGradientSP gradient, qreal t)
{
    KoColor color;
    gradient->colorAt(color, t);
    return color.toQColor();
}

} // namespace

void TestNodeAgentTools::testGradientFromResource()
{
    // Krita's own gradients: one with fixed colours, and one whose start is the foreground colour.
    KoAbstractGradientSP fixed;
    KoAbstractGradientSP variable;
    KisResourceModel model(ResourceType::Gradients);
    for (int row = 0; row < model.rowCount(); row++) {
        KoAbstractGradientSP g = model.resourceForIndex(model.index(row, 0)).dynamicCast<KoAbstractGradient>();
        if (!g || model.resourcesForName(g->name()).size() != 1) continue;
        if (g->requiredCanvasResources().isEmpty()) {
            if (!fixed) fixed = g;
        } else if (!variable && colorAt(baked(g, Qt::red, Qt::blue), 0.0) == QColor(Qt::red)
                   && colorAt(baked(g, Qt::green, Qt::blue), 0.0) == QColor(Qt::green)) {
            variable = g;
        }
    }
    QVERIFY(fixed);
    QVERIFY(variable);

    ToolDocument d;
    QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0), {{"gradient", fixed->name()}}));
    d.settle();
    QVERIFY_NEAR(d.at(0, 50), colorAt(fixed, 0.0), 3);
    QVERIFY_NEAR(d.at(119, 50), colorAt(fixed, 1.0), 3);
    d.undo();

    // A gradient of the foreground and background colours takes them from "colors".
    QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0),
                                  {{"gradient", variable->name()},
                                   {"colors", QVariantList({QColor(Qt::red), QColor(Qt::blue)})}}));
    d.settle();
    QVERIFY_NEAR(d.at(0, 50), QColor(Qt::red), 3);
    QVERIFY_NEAR(d.at(119, 50), colorAt(baked(variable, Qt::red, Qt::blue), 1.0), 3);

    // An unknown gradient is refused.
    const int undoBefore = d.undoCount();
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0), {{"gradient", "no such gradient"}}));
    QCOMPARE(d.undoCount(), undoBefore);
}

void TestNodeAgentTools::testSmartPatchChangesOnlyInsideTheMask()
{
    // Diagonal stripes, with a red seam across them.
    ToolDocument d;
    const KoColorSpace *cs = d.image->colorSpace();
    for (int y = 0; y < 100; y++) {
        for (int x = 0; x < 120; x++) {
            const bool dark = ((x + y) / 6) % 2;
            d.paint->paintDevice()->setPixel(x, y, KoColor(dark ? QColor(40, 60, 90) : QColor(200, 210, 220), cs));
        }
    }
    d.paint->paintDevice()->fill(QRect(50, 20, 6, 60), KoColor(Qt::red, cs));
    d.render();
    const QByteArray before = d.bytes(d.paint);
    const int undoBefore = d.undoCount();

    Selection seam;
    seam.select(48, 18, 10, 64, 255);
    QVERIFY(d.paintNode->smartPatch(&seam, {{"accuracy", 50}, {"patchRadius", 4}}));
    d.settle();

    // No red left in the seam, and every pixel outside the mask as it was.
    int red = 0;
    for (int y = 20; y < 80; y++) {
        for (int x = 50; x < 56; x++) {
            const QColor c = d.at(x, y);
            if (c.red() > 180 && c.green() < 80) red++;
        }
    }
    QCOMPARE(red, 0);
    const QByteArray after = d.bytes(d.paint);
    const int pixelSize = d.paint->paintDevice()->pixelSize();
    int changedOutside = 0;
    int changedInside = 0;
    for (int y = 0; y < 100; y++) {
        for (int x = 0; x < 120; x++) {
            const int i = (y * 120 + x) * pixelSize;
            const bool changed = before.mid(i, pixelSize) != after.mid(i, pixelSize);
            const bool inside = QRect(48, 18, 10, 64).contains(x, y);
            if (changed && !inside) changedOutside++;
            if (changed && inside) changedInside++;
        }
    }
    QCOMPARE(changedOutside, 0);
    QVERIFY(changedInside >= 6 * 60);

    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Smart Patch"));
    d.undo();
    QVERIFY(d.bytes(d.paint) == before);
}

void TestNodeAgentTools::testMoveIsOneUndoStep()
{
    ToolDocument d;
    const KoColorSpace *cs = d.image->colorSpace();
    d.paint->paintDevice()->fill(QRect(10, 10, 20, 20), KoColor(Qt::red, cs));
    d.render();
    const int undoBefore = d.undoCount();

    QVERIFY(d.paintNode->move(30, 15));
    d.settle();
    QCOMPARE(d.paintNode->position(), QPoint(30, 15));
    QVERIFY_NEAR(d.at(45, 30), QColor(Qt::red), 0); // the box moved by (30, 15)
    QCOMPARE(d.at(15, 15).alpha(), 0);
    QImage projection = d.projection();
    QCOMPARE(QColor(projection.pixel(45, 30)), QColor(Qt::red));
    QCOMPARE(QColor(projection.pixel(15, 15)), QColor(Qt::white));

    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Move"));
    d.undo();
    QCOMPARE(d.paintNode->position(), QPoint(0, 0));
    QVERIFY_NEAR(d.at(15, 15), QColor(Qt::red), 0);
    projection = d.projection();
    QCOMPARE(QColor(projection.pixel(15, 15)), QColor(Qt::red));
    QCOMPARE(QColor(projection.pixel(45, 30)), QColor(Qt::white));

    // Moving to where it is adds no step.
    QVERIFY(d.paintNode->move(0, 0));
    d.settle();
    QCOMPARE(d.undoCount(), undoBefore + 1);
}

void TestNodeAgentTools::testRefusals()
{
    ToolDocument d;
    outline(d.paint, QRect(20, 20, 60, 50), Qt::black);
    d.render();
    const QByteArray before = d.bytes(d.paint);
    const int undoBefore = d.undoCount();
    Selection area;
    area.select(30, 30, 10, 10, 255);
    Selection empty;
    const QVariantList colors({QColor(Qt::red), QColor(Qt::blue)});

    // A locked layer, or one inside a locked group: every call refuses.
    d.paint->setUserLocked(true);
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red)));
    QVERIFY(!d.paintNode->encloseAndFill(&area, QColor(Qt::red)));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", colors}}));
    QVERIFY(!d.paintNode->smartPatch(&area));
    QVERIFY(!d.paintNode->move(5, 5));
    d.paint->setUserLocked(false);

    KisGroupLayerSP group = new KisGroupLayer(d.image, "group", OPACITY_OPAQUE_U8);
    d.image->addNode(group);
    KisPaintLayerSP inner = new KisPaintLayer(d.image, "inner", OPACITY_OPAQUE_U8);
    d.image->addNode(inner, group);
    group->setUserLocked(true);
    QScopedPointer<Node> innerNode(Node::createNode(d.image, inner));
    QVERIFY(!innerNode->fill(5, 5, QColor(Qt::red)));
    QVERIFY(!innerNode->move(5, 5));
    group->setUserLocked(false);

    // A group has no pixels of its own to paint.
    QScopedPointer<Node> groupNode(Node::createNode(d.image, group));
    QVERIFY(!groupNode->fill(5, 5, QColor(Qt::red)));
    QVERIFY(!groupNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", colors}}));

    // Bad arguments: no or an empty area, a point outside the image, unknown options and values.
    QVERIFY(!d.paintNode->encloseAndFill(nullptr, QColor(Qt::red)));
    QVERIFY(!d.paintNode->encloseAndFill(&empty, QColor(Qt::red)));
    QVERIFY(!d.paintNode->smartPatch(nullptr));
    QVERIFY(!d.paintNode->smartPatch(&empty));
    QVERIFY(!d.paintNode->fill(500, 45, QColor(Qt::red)));
    QVERIFY(!d.paintNode->fill(50, 45, QColor()));
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red), {{"treshold", 10}}));
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red), {{"sample", "everything"}}));
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red), {{"threshold", "high"}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(0, 0), {{"colors", colors}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0)));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", colors}, {"shape", "star"}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", QVariantList({QColor(Qt::red)})}}));
    QVERIFY(!d.paintNode->smartPatch(&area, {{"patchRadius", 40}}));

    // A node whose layer has left the image.
    KisPaintLayerSP gone = new KisPaintLayer(d.image, "gone", OPACITY_OPAQUE_U8);
    QScopedPointer<Node> goneNode(Node::createNode(d.image, gone));
    QVERIFY(!goneNode->fill(5, 5, QColor(Qt::red)));
    QVERIFY(!goneNode->smartPatch(&area));

    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
    QVERIFY(d.bytes(d.paint) == before);
    QCOMPARE(d.paintNode->position(), QPoint(0, 0));
}

void TestNodeAgentTools::testEachJoinsAnAgentMove()
{
    ToolDocument d;
    outline(d.paint, QRect(20, 20, 60, 50), Qt::black);
    KisPaintLayerSP sky = new KisPaintLayer(d.image, "sky", OPACITY_OPAQUE_U8);
    d.image->addNode(sky, d.image->root(), d.background);
    QScopedPointer<Node> skyNode(Node::createNode(d.image, sky));
    d.render();
    const QImage before = d.projection();
    const QByteArray paintBefore = d.bytes(d.paint);
    const QByteArray skyBefore = d.bytes(sky);
    const int undoBefore = d.undoCount();
    Selection patch;
    patch.select(40, 40, 6, 6, 255);
    Selection enclosing;
    enclosing.select(0, 0, 120, 100, 255);

    // Each call alone in a move: one step, the move's.
    QVERIFY(d.doc->beginAgentMove("fill"));
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red)));
    QVERIFY(d.doc->endAgentMove());
    for (int i = 0; i < 3; i++) d.settle();
    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Agent: fill"));
    d.undo();
    QVERIFY(d.bytes(d.paint) == paintBefore);

    // All of them in one move: one step, and one undo restores both layers and the position.
    QVERIFY(d.doc->beginAgentMove("tools"));
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red)));
    QVERIFY(d.paintNode->encloseAndFill(&enclosing, QColor(Qt::green), {{"regions", "transparent"}}));
    QVERIFY(skyNode->gradient(QPointF(0, 0), QPointF(0, 99),
                              {{"colors", QVariantList({QColor(Qt::cyan), QColor(Qt::darkBlue)})}}));
    QVERIFY(d.paintNode->smartPatch(&patch));
    QVERIFY(d.paintNode->move(7, 3));
    QVERIFY(d.doc->endAgentMove());
    for (int i = 0; i < 3; i++) d.settle();

    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Agent: tools"));
    QCOMPARE(d.paintNode->position(), QPoint(7, 3));
    QVERIFY(d.bytes(sky) != skyBefore);
    QVERIFY(!difference(before, d.projection(), 1).isEmpty());

    d.undo();
    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.paintNode->position(), QPoint(0, 0));
    QVERIFY(d.bytes(d.paint) == paintBefore);
    QVERIFY(d.bytes(sky) == skyBefore);
    const QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

namespace {

/// Sets the tool functions' wait limit for one test and restores it however the test ends.
struct WaitLimit {
    const int previous = KisToolFunctions::waitLimit();
    explicit WaitLimit(int milliseconds) { KisToolFunctions::setWaitLimit(milliseconds); }
    ~WaitLimit() { KisToolFunctions::setWaitLimit(previous); }
};

/// The names of \p d's undo steps from \p first on.
QStringList stepsFrom(const ToolDocument &d, int first)
{
    QStringList names;
    for (int i = first; i < d.undoCount(); i++) names << d.doc->undoText(i);
    return names;
}

/// The number of pixels of \p layer whose alpha is strictly between 0 and 255.
int partlyCovered(const ToolDocument &d, KisPaintLayerSP layer)
{
    int count = 0;
    for (int y = 0; y < d.image->height(); y++) {
        for (int x = 0; x < d.image->width(); x++) {
            const int alpha = d.at(layer, x, y).alpha();
            if (alpha > 0 && alpha < 255) count++;
        }
    }
    return count;
}

} // namespace

void TestNodeAgentTools::testFillKeepsInsideTheSelectionByDefault()
{
    // Two selected boxes, joined only through unselected pixels. A dot keeps the layer from being empty, so the fill
    // is a real flood fill (an empty layer fills the whole selection, as with the tool).
    ToolDocument d;
    d.paint->paintDevice()->setPixel(110, 90, KoColor(Qt::black, d.image->colorSpace()));
    d.render();
    Selection two;
    two.select(10, 10, 20, 20, 255);
    two.select(70, 50, 20, 20, 255);

    // As the Fill tool by default: the selection is the boundary, so the other box is not reached.
    QVERIFY(d.paintNode->fill(15, 15, QColor(Qt::red), QVariantMap(), &two));
    d.settle();
    QVERIFY_NEAR(d.at(15, 15), QColor(Qt::red), 0);
    QCOMPARE(d.at(75, 55).alpha(), 0);
    QCOMPARE(d.paintedPixels(), 20 * 20 + 1);
    d.undo();

    // Without it, the region is found on the whole layer and then limited to the selection.
    QVERIFY(d.paintNode->fill(15, 15, QColor(Qt::red), {{"useSelectionAsBoundary", false}}, &two));
    d.settle();
    QVERIFY_NEAR(d.at(75, 55), QColor(Qt::red), 0);
    QCOMPARE(d.paintedPixels(), 2 * 20 * 20 + 1);
}

void TestNodeAgentTools::testEncloseLeavesContourRegionsByDefault()
{
    // A box inside the enclosing area; the transparent pixels around it touch the area's edge.
    ToolDocument d;
    outline(d.paint, QRect(10, 20, 30, 30), Qt::black);
    d.render();
    Selection area;
    area.select(5, 15, 45, 45, 255);

    // As the Enclose and Fill tool by default: regions touching the enclosing contour are not filled.
    QVERIFY(d.paintNode->encloseAndFill(&area, QColor(Qt::red)));
    d.settle();
    QVERIFY_NEAR(d.at(25, 35), QColor(Qt::red), 0);
    QCOMPARE(d.at(7, 17).alpha(), 0);
    d.undo();

    QVERIFY(d.paintNode->encloseAndFill(&area, QColor(Qt::red), {{"includeContourRegions", true}}));
    d.settle();
    QVERIFY_NEAR(d.at(7, 17), QColor(Qt::red), 0);
}

void TestNodeAgentTools::testNonFiniteInputIsRefused()
{
    ToolDocument d;
    const int undoBefore = d.undoCount();
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();
    const QVariantList colors({QColor(Qt::red), QColor(Qt::blue)});

    // Options first: a refused call must stop before anything reaches the painters.
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red), {{"opacity", nan}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", colors}, {"opacity", nan}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", colors}, {"antiAliasThreshold", inf}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", colors}, {"opacity", -inf}}));

    // Then the gradient's ends: not finite, or beyond a million pixels.
    QVERIFY(!d.paintNode->gradient(QPointF(nan, 0), QPointF(50, 0), {{"colors", colors}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, nan), {{"colors", colors}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(inf, 0), {{"colors", colors}}));
    QVERIFY(!d.paintNode->gradient(QPointF(-inf, 0), QPointF(50, 0), {{"colors", colors}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(2e6, 0), {{"colors", colors}}));
    QVERIFY(!d.paintNode->gradient(QPointF(0, -1.5e6), QPointF(5, 0), {{"colors", colors}}));

    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
    QCOMPARE(d.paintedPixels(), 0);
}

void TestNodeAgentTools::testDoesNotEndOpenStrokes()
{
    // Starting a stroke asks open strokes (the artist's) to end unless it says not to; these never ask.
    ToolDocument d;
    outline(d.paint, QRect(20, 20, 60, 50), Qt::black);
    d.render();
    QSignalSpy endRequests(d.image.data(), SIGNAL(sigStrokeEndRequested()));
    QVERIFY(endRequests.isValid());
    Selection area;
    area.select(40, 40, 6, 6, 255);

    const QList<QPair<QString, std::function<bool()>>> calls = {
        {"fill", [&]() { return d.paintNode->fill(50, 45, QColor(Qt::red)); }},
        {"encloseAndFill", [&]() { return d.paintNode->encloseAndFill(&area, QColor(Qt::green)); }},
        {"gradient", [&]() { return d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", QVariantList({QColor(Qt::red), QColor(Qt::blue)})}}); }},
        {"smartPatch", [&]() { return d.paintNode->smartPatch(&area); }},
        {"move", [&]() { return d.paintNode->move(3, 2); }},
    };
    // Counted right after each call: the test's own waits (KisImage::waitForDone()) ask strokes to end too.
    for (const auto &call : calls) {
        endRequests.clear();
        QVERIFY2(call.second(), qPrintable(call.first));
        QVERIFY2(endRequests.count() == 0, qPrintable(call.first + " asked open strokes to end"));
        d.settle();
    }
}

void TestNodeAgentTools::testGivesUpBehindAnOpenStroke()
{
    ToolDocument d;
    const int undoBefore = d.undoCount();
    WaitLimit limit(300);

    // The artist's pen is down: a stroke started and not ended holds every later stroke back.
    KisStrokeId artist = d.image->startStroke(
        new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("artist"), false, d.image.data()));
    QVERIFY(artist);

    // The calls wait a bounded time, then give up: false, their strokes cancelled, nothing changed.
    QElapsedTimer timer;
    timer.start();
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red)));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", QVariantList({QColor(Qt::red), QColor(Qt::blue)})}}));
    QVERIFY(!d.paintNode->move(5, 5));
    QVERIFY2(timer.elapsed() < 5000, qPrintable(QString::number(timer.elapsed())));

    // The artist's stroke was left open, and ends when the artist lifts the pen.
    d.image->endStroke(artist);
    d.settle();
    QCOMPARE(d.paintedPixels(), 0);
    QCOMPARE(d.paintNode->position(), QPoint(0, 0));
    // Only the artist's stroke may have added a step.
    const QStringList steps = stepsFrom(d, undoBefore);
    QVERIFY2(steps.isEmpty() || steps == QStringList({"artist"}), qPrintable(steps.join(", ")));
}

void TestNodeAgentTools::testWaitsForItsOwnStrokeOnly()
{
    ToolDocument d;
    KisToolFunctions::Target target;
    target.image = d.image;
    target.node = d.paint;
    target.completion.reset(new KisToolFunctions::Completion());
    QVERIFY(KisToolFunctions::fill(target, QPoint(50, 45), KoColor(Qt::red, d.image->colorSpace()),
                                   KisToolFunctions::FillOptions()));

    // A long stroke queued after it.
    QSharedPointer<std::atomic<bool>> longDone(new std::atomic<bool>(false));
    KisStrokeId id = d.image->startStroke(
        new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("long"), false, d.image.data()));
    d.image->addJob(id, new KisStrokeStrategyUndoCommandBased::Data(
                            KUndo2CommandSP(new KisCommandUtils::LambdaCommand([longDone]() -> KUndo2Command * {
                                QThread::msleep(1500);
                                *longDone = true;
                                return nullptr;
                            })),
                            false, KisStrokeJobData::SEQUENTIAL, KisStrokeJobData::EXCLUSIVE));
    d.image->endStroke(id);

    QElapsedTimer timer;
    timer.start();
    QVERIFY(target.completion->wait(10000));
    QVERIFY2(timer.elapsed() < 1000, qPrintable(QString::number(timer.elapsed())));
    QVERIFY(!*longDone);
    QVERIFY(target.completion->finished());
    QVERIFY_NEAR(d.at(50, 45), QColor(Qt::red), 0);

    d.settle();
    QVERIFY(*longDone);
}

void TestNodeAgentTools::testSmartPatchRefusesLargeAreas()
{
    // An area above the limit is refused at once, instead of holding the window for minutes.
    const int limit = KisToolFunctions::smartPatchAreaLimit();
    QVERIFY(limit > 0);
    const int width = 1200;
    const int height = limit / width + 10;
    ToolDocument d(QSize(width, height));
    d.paint->paintDevice()->fill(QRect(0, 0, width, height), KoColor(QColor(90, 120, 150), d.image->colorSpace()));
    d.render();
    const int undoBefore = d.undoCount();

    Selection big;
    big.select(0, 0, width, height, 255);
    QElapsedTimer timer;
    timer.start();
    QVERIFY(!d.paintNode->smartPatch(&big));
    QVERIFY2(timer.elapsed() < 2000, qPrintable(QString::number(timer.elapsed())));
    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
}

void TestNodeAgentTools::testMoveRefusesRootAndDetachedNodes()
{
    ToolDocument d;
    const int undoBefore = d.undoCount();

    QScopedPointer<Node> root(d.doc->rootNode());
    QVERIFY(root);
    QVERIFY(!root->move(5, 5));
    QCOMPARE(d.image->root()->x(), 0);

    // A node not (or no longer) in the document.
    KisPaintLayerSP gone = new KisPaintLayer(d.image, "gone", OPACITY_OPAQUE_U8);
    QScopedPointer<Node> goneNode(Node::createNode(d.image, gone));
    QVERIFY(!goneNode->move(5, 5));
    QCOMPARE(QPoint(gone->x(), gone->y()), QPoint(0, 0));

    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
}

void TestNodeAgentTools::testMinorRefusals()
{
    ToolDocument d;
    outline(d.paint, QRect(10, 20, 30, 30), Qt::black);
    d.render();
    const int undoBefore = d.undoCount();
    const QByteArray before = d.bytes(d.paint);
    Selection area;
    area.select(5, 15, 45, 45, 255);
    Selection empty;
    const QVariantList colors({QColor(Qt::red), QColor(Qt::blue)});

    // The tools' own ranges: threshold from 1, accuracy up to 99.
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red), {{"threshold", 0}}));
    QVERIFY(!d.paintNode->smartPatch(&area, {{"accuracy", 100}}));
    // Sampling colour labels needs at least one label.
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red), {{"sample", "labels"}, {"labels", QVariantList()}}));
    // A limiting selection that selects nothing.
    QVERIFY(!d.paintNode->fill(50, 45, QColor(Qt::red), QVariantMap(), &empty));
    QVERIFY(!d.paintNode->gradient(QPointF(0, 0), QPointF(50, 0), {{"colors", colors}}, &empty));
    QVERIFY(!d.paintNode->encloseAndFill(&area, QColor(Qt::red), QVariantMap(), &empty));
    // Region methods that name a colour need it.
    for (const QString &regions : {"color", "colorOrTransparent", "allExceptColor", "allExceptColorOrTransparent",
                                   "surroundedByColor", "surroundedByColorOrTransparent"}) {
        QVERIFY2(!d.paintNode->encloseAndFill(&area, QColor(Qt::red), {{"regions", regions}}), qPrintable(regions));
    }

    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
    QVERIFY(d.bytes(d.paint) == before);
}

void TestNodeAgentTools::testGradientUsesTheSelectionAtRunTime()
{
    // In an agent move, the document's selection is set by a queued step: the fill and the gradient queued after it
    // use it, not the selection there was when they were called.
    ToolDocument d;
    KisPaintLayerSP sky = new KisPaintLayer(d.image, "sky", OPACITY_OPAQUE_U8);
    d.image->addNode(sky);
    QScopedPointer<Node> skyNode(Node::createNode(d.image, sky));
    d.render();
    Selection left;
    left.select(0, 0, 60, 100, 255);

    QVERIFY(d.doc->beginAgentMove("selection"));
    d.doc->setSelection(&left);
    QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0), {{"colors", QVariantList({QColor(Qt::red), QColor(Qt::blue)})}}));
    QVERIFY(skyNode->fill(5, 5, QColor(Qt::green)));
    QVERIFY(d.doc->endAgentMove());
    for (int i = 0; i < 3; i++) d.settle();

    QVERIFY(d.at(30, 50).alpha() > 0);
    QCOMPARE(d.at(100, 50).alpha(), 0);
    QVERIFY_NEAR(d.at(sky, 30, 50), QColor(Qt::green), 0);
    QCOMPARE(d.at(sky, 100, 50).alpha(), 0);
}

void TestNodeAgentTools::testDocumentSelectionIsUsedByDefault()
{
    ToolDocument d;
    Selection left;
    left.select(0, 0, 60, 100, 255);
    d.doc->setSelection(&left);
    d.settle();

    QVERIFY(d.paintNode->fill(10, 10, QColor(Qt::red)));
    d.settle();
    QCOMPARE(d.paintedPixels(), 60 * 100);
    d.undo();

    QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0), {{"colors", QVariantList({QColor(Qt::red), QColor(Qt::blue)})}}));
    d.settle();
    QCOMPARE(d.paintedPixels(), 60 * 100);

    // A selection passed to the call replaces the document's.
    d.undo();
    Selection right;
    right.select(60, 0, 60, 100, 255);
    QVERIFY(d.paintNode->fill(100, 10, QColor(Qt::red), QVariantMap(), &right));
    d.settle();
    QVERIFY_NEAR(d.at(100, 10), QColor(Qt::red), 0);
    QCOMPARE(d.at(10, 10).alpha(), 0);
}

void TestNodeAgentTools::testHiddenLayerIsPainted()
{
    ToolDocument d;
    d.paint->setVisible(false);
    d.render();
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red)));
    QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0),
                                  {{"colors", QVariantList({QColor(Qt::red), QColor(Qt::blue)})}, {"opacity", 0.5}}));
    d.settle();
    QVERIFY(d.at(50, 45).alpha() == 255);
    QVERIFY(!d.paint->visible());
}

void TestNodeAgentTools::testRedo()
{
    ToolDocument d;
    const KoColorSpace *cs = d.image->colorSpace();
    for (int y = 0; y < 100; y++) {
        for (int x = 0; x < 120; x++) {
            d.paint->paintDevice()->setPixel(x, y, KoColor(((x + y) / 6) % 2 ? QColor(40, 60, 90) : QColor(200, 210, 220), cs));
        }
    }
    d.render();
    Selection area;
    area.select(50, 40, 8, 8, 255);
    const QVariantList colors({QColor(Qt::red), QColor(Qt::blue)});

    const QList<std::function<bool()>> calls = {
        [&]() { return d.paintNode->fill(3, 3, QColor(Qt::red), {{"threshold", 30}}); },
        [&]() { return d.paintNode->gradient(QPointF(0, 0), QPointF(60, 0), {{"colors", colors}, {"opacity", 0.5}}); },
        [&]() { return d.paintNode->smartPatch(&area); },
        [&]() { return d.paintNode->encloseAndFill(&area, QColor(Qt::green), {{"includeContourRegions", true}}); },
        [&]() { return d.paintNode->move(6, 4); },
    };
    for (int i = 0; i < calls.size(); i++) {
        const QByteArray before = d.bytes(d.paint);
        QVERIFY2(calls[i](), qPrintable(QString::number(i)));
        d.settle();
        const QByteArray after = d.bytes(d.paint);
        const QPoint position = d.paintNode->position();
        QVERIFY2(after != before, qPrintable(QString::number(i)));
        d.undo();
        QVERIFY2(d.bytes(d.paint) == before, qPrintable(QString::number(i)));
        d.redo();
        QVERIFY2(d.bytes(d.paint) == after, qPrintable(QString::number(i)));
        QCOMPARE(d.paintNode->position(), position);
    }
}

void TestNodeAgentTools::testArtistStepStaysSeparateDuringAMove()
{
    ToolDocument d;
    const int undoBefore = d.undoCount();
    KisPaintLayerSP background = d.background;
    const KoColor green(Qt::green, d.image->colorSpace());

    QVERIFY(d.doc->beginAgentMove("tools"));
    QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red)));
    // The artist paints the background with a tool while the move is open: a transaction on its device, run as a
    // stroke into the document's history, as the tools' strokes do.
    KisTransaction transaction(kundo2_noi18n("artist"), background->paintDevice());
    background->paintDevice()->fill(QRect(0, 0, 10, 10), green);
    KisProcessingApplicator::runSingleCommandStroke(d.image, transaction.endAndTake());
    QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0), {{"colors", QVariantList({QColor(Qt::red), QColor(Qt::blue)})}, {"opacity", 0.5}}));
    QVERIFY(d.doc->endAgentMove());
    for (int i = 0; i < 3; i++) d.settle();

    // The artist's stroke is a step of its own, and the agent's work stays in the move's steps. A tool's stroke
    // lands as a saved macro whose devices DocumentHistory cannot read (task 2.5), so the move is split there into
    // "Agent: tools" and "Agent: tools (cont.)", as for any artist work it cannot rule out.
    const QStringList steps = stepsFrom(d, undoBefore);
    QVERIFY2(steps.count("artist") == 1, qPrintable(steps.join(" | ")));
    for (const QString &step : steps) {
        QVERIFY2(step == "artist" || step.startsWith("Agent: tools"), qPrintable(steps.join(" | ")));
    }
    QVERIFY2(steps.last().startsWith("Agent: tools"), qPrintable(steps.join(" | ")));

    // Undoing the agent's last step leaves the artist's work, and the gradient is gone.
    const QColor withGradient = d.at(100, 50);
    d.undo();
    QVERIFY_NEAR(d.at(background, 5, 5), QColor(Qt::green), 0);
    QVERIFY(d.at(100, 50) != withGradient);
}

void TestNodeAgentTools::testFillOptions()
{
    const KoColor black(Qt::black, KoColorSpaceRegistry::instance()->rgb8());

    // boundaryColor: fills across other colours, up to the boundary colour.
    {
        ToolDocument d;
        const KoColorSpace *cs = d.image->colorSpace();
        d.paint->paintDevice()->fill(QRect(0, 0, 40, 100), KoColor(QColor(100, 100, 100), cs));
        d.paint->paintDevice()->fill(QRect(40, 0, 20, 100), KoColor(QColor(180, 180, 180), cs));
        d.paint->paintDevice()->fill(QRect(60, 0, 2, 100), KoColor(Qt::red, cs));
        d.paint->paintDevice()->fill(QRect(62, 0, 58, 100), KoColor(QColor(100, 100, 100), cs));
        d.render();
        QVERIFY(d.paintNode->fill(10, 50, QColor(Qt::blue)));
        d.settle();
        QVERIFY_NEAR(d.at(50, 50), QColor(180, 180, 180), 0);
        d.undo();
        QVERIFY(d.paintNode->fill(10, 50, QColor(Qt::blue), {{"boundaryColor", QColor(Qt::red)}}));
        d.settle();
        QVERIFY_NEAR(d.at(50, 50), QColor(Qt::blue), 0);
        QVERIFY_NEAR(d.at(61, 50), QColor(Qt::red), 0);
        QVERIFY_NEAR(d.at(90, 50), QColor(100, 100, 100), 0);
    }

    // closeGap: a box with a gap in its wall leaks, unless the gap is closed.
    {
        ToolDocument d;
        outline(d.paint, QRect(20, 20, 60, 50), Qt::black);
        d.paint->paintDevice()->clear(QRect(20, 44, 2, 2));
        d.render();
        QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red)));
        d.settle();
        QVERIFY_NEAR(d.at(5, 5), QColor(Qt::red), 0);
        d.undo();
        QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red), {{"closeGap", 4}}));
        d.settle();
        QVERIFY_NEAR(d.at(50, 45), QColor(Qt::red), 0);
        QCOMPARE(d.at(5, 5).alpha(), 0);
    }

    // grow and feather: the filled area grows into the contour; feathering softens its edge.
    {
        ToolDocument d;
        outline(d.paint, QRect(20, 20, 60, 50), Qt::black, 4);
        d.render();
        QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red)));
        d.settle();
        QVERIFY_NEAR(d.at(22, 45), QColor(Qt::black), 0);
        QCOMPARE(partlyCovered(d, d.paint), 0);
        d.undo();
        QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red), {{"grow", 2}}));
        d.settle();
        QVERIFY_NEAR(d.at(22, 45), QColor(Qt::red), 0);
        QVERIFY_NEAR(d.at(20, 45), QColor(Qt::black), 0);
        d.undo();
        ToolDocument e;
        QVERIFY(e.paintNode->fill(50, 45, QColor(Qt::red), QVariantMap(), nullptr));
        e.settle();
        QCOMPARE(partlyCovered(e, e.paint), 0);
        e.undo();
        Selection box;
        box.select(30, 30, 40, 30, 255);
        e.paint->paintDevice()->setPixel(110, 90, black);
        e.render();
        QVERIFY(e.paintNode->fill(50, 45, QColor(Qt::red), {{"feather", 4}, {"useSelectionAsBoundary", true}}, &box));
        e.settle();
        QVERIFY(partlyCovered(e, e.paint) > 0);
    }

    // antialias: a fill against a diagonal edge gets partly covered pixels along it.
    {
        ToolDocument d;
        for (int y = 0; y < 100; y++) {
            d.paint->paintDevice()->fill(QRect(0, y, y + 10, 1), black);
        }
        d.render();
        QVERIFY(d.paintNode->fill(110, 5, QColor(Qt::red)));
        d.settle();
        QCOMPARE(partlyCovered(d, d.paint), 0);
        d.undo();
        QVERIFY(d.paintNode->fill(110, 5, QColor(Qt::red), {{"antialias", true}}));
        d.settle();
        QVERIFY(partlyCovered(d, d.paint) > 0);
    }

    // opacity and compositeOp.
    {
        ToolDocument d;
        QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red), {{"opacity", 0.5}}));
        d.settle();
        const int alpha = d.at(50, 45).alpha();
        QVERIFY2(qAbs(alpha - 128) <= 1, qPrintable(QString::number(alpha)));
        d.undo();
        d.paint->paintDevice()->fill(d.image->bounds(), KoColor(QColor(200, 200, 200), d.image->colorSpace()));
        d.render();
        QVERIFY(d.paintNode->fill(50, 45, QColor(Qt::red), {{"compositeOp", "multiply"}}));
        d.settle();
        QVERIFY_NEAR(d.at(50, 45), QColor(200, 0, 0), 1);
    }
}

void TestNodeAgentTools::testEncloseRegionMethods()
{
    // Box A holds blue, box B is empty; the enclosing area covers both.
    ToolDocument d;
    const KoColorSpace *cs = d.image->colorSpace();
    outline(d.paint, QRect(10, 20, 30, 30), Qt::black);
    d.paint->paintDevice()->fill(QRect(12, 22, 26, 26), KoColor(Qt::blue, cs));
    outline(d.paint, QRect(70, 20, 30, 30), Qt::black);
    d.render();
    Selection area;
    area.select(5, 15, 100, 45, 255);

    QVERIFY(d.paintNode->encloseAndFill(&area, QColor(Qt::red), {{"regions", "color"}, {"regionColor", QColor(Qt::blue)}}));
    d.settle();
    QVERIFY_NEAR(d.at(25, 35), QColor(Qt::red), 0);
    QCOMPARE(d.at(85, 35).alpha(), 0);
    d.undo();

    QVERIFY(d.paintNode->encloseAndFill(&area, QColor(Qt::red), {{"regions", "transparent"}}));
    d.settle();
    QVERIFY_NEAR(d.at(25, 35), QColor(Qt::blue), 0);
    QVERIFY_NEAR(d.at(85, 35), QColor(Qt::red), 0);
    d.undo();

    QVERIFY(d.paintNode->encloseAndFill(&area, QColor(Qt::red), {{"regions", "surroundedByColor"}, {"regionColor", QColor(Qt::black)}}));
    d.settle();
    QVERIFY_NEAR(d.at(25, 35), QColor(Qt::red), 0);
    QVERIFY_NEAR(d.at(85, 35), QColor(Qt::red), 0);
    QCOMPARE(d.at(7, 17).alpha(), 0);
}

void TestNodeAgentTools::testGradientRepeatAndDither()
{
    ToolDocument d;
    const QVariantList colors({QColor(Qt::red), QColor(Qt::blue)});

    // Without repeat, the end colour carries on past the end.
    QVERIFY(d.paintNode->gradient(QPointF(0, 50), QPointF(39, 50), {{"colors", colors}}));
    d.settle();
    const QColor at11 = d.at(11, 50);
    const QColor at28 = d.at(28, 50);
    QVERIFY_NEAR(d.at(50, 50), QColor(Qt::blue), 2);
    d.undo();

    // Forwards, it starts again: 50 is 11 into its second pass. Alternate, it comes back: 50 is at 28.
    QVERIFY(d.paintNode->gradient(QPointF(0, 50), QPointF(39, 50), {{"colors", colors}, {"repeat", "forwards"}}));
    d.settle();
    QVERIFY_NEAR(d.at(50, 50), at11, 8);
    d.undo();
    QVERIFY(d.paintNode->gradient(QPointF(0, 50), QPointF(39, 50), {{"colors", colors}, {"repeat", "alternate"}}));
    d.settle();
    QVERIFY_NEAR(d.at(50, 50), at28, 8);
    d.undo();

    // Dither: a shallow gradient is the same down every column without it, and varies with it.
    const QVariantList shallow({QColor(100, 100, 100), QColor(110, 110, 110)});
    auto columnsVary = [&d]() {
        for (int x = 0; x < d.image->width(); x++) {
            for (int y = 1; y < d.image->height(); y++) {
                if (d.at(x, y) != d.at(x, 0)) return true;
            }
        }
        return false;
    };
    QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0), {{"colors", shallow}}));
    d.settle();
    QVERIFY(!columnsVary());
    d.undo();
    for (const QVariant &dither : {QVariant("bayer4"), QVariant(true), QVariant("bayer8")}) {
        QVERIFY(d.paintNode->gradient(QPointF(0, 0), QPointF(119, 0), {{"colors", shallow}, {"dither", dither}}));
        d.settle();
        QVERIFY2(columnsVary(), qPrintable(dither.toString()));
        d.undo();
    }
}

void TestNodeAgentTools::benchSmartPatch()
{
    if (!qEnvironmentVariableIsSet("TOOLS53_BENCH")) QSKIP("timing only: set TOOLS53_BENCH");
    for (int side : {100, 200, 300, 400, 500}) {
        ToolDocument d(QSize(side * 3, side * 3));
        const KoColorSpace *cs = d.image->colorSpace();
        for (int y = 0; y < d.image->height(); y++) {
            for (int x = 0; x < d.image->width(); x++) {
                d.paint->paintDevice()->setPixel(x, y, KoColor(((x + y) / 6) % 2 ? QColor(40, 60, 90) : QColor(200, 210, 220), cs));
            }
        }
        Selection area;
        area.select(side, side, side, side, 255);
        QElapsedTimer timer;
        timer.start();
        QVERIFY(d.paintNode->smartPatch(&area));
        qWarning() << "BENCH smart patch" << side << "x" << side << "accuracy 50:" << timer.elapsed() << "ms";
    }
}

KISTEST_TEMPORARY_HOME_MAIN(TestNodeAgentTools)
