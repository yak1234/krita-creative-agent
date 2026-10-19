/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestDocumentAgentCraft.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include "AgentCraftTestUtils.h"

#include <Document.h>
#include <FilterMask.h>
#include <Node.h>

#include <KisGlobalResourcesInterface.h>
#include <KoColor.h>
#include <filter/kis_filter.h>
#include <filter/kis_filter_configuration.h>
#include <filter/kis_filter_registry.h>
#include <kis_filter_mask.h>
#include <kis_group_layer.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_pixel_selection.h>
#include <kis_psd_layer_style.h>
#include <kis_selection.h>
#include <kis_transparency_mask.h>

using namespace AgentCraftTest;

namespace {

KisFilterConfigurationSP blurConfiguration(int radius)
{
    KisFilterSP filter = KisFilterRegistry::instance()->value("blur");
    if (!filter) return KisFilterConfigurationSP();
    KisFilterConfigurationSP config = filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
    config->setProperty("halfWidth", radius);
    config->setProperty("halfHeight", radius);
    return config->cloneWithResourcesSnapshot();
}

/**
 * A striped background, then two groups of kept work above it:
 *  - "work A": a red layer with a blur filter mask and a transparency mask hiding part of it, and a half-transparent
 *    green layer;
 *  - "work B" (opacity 180, with a drop shadow): a blue layer.
 */
struct KeptWork : public UndoableDocument {
    KisGroupLayerSP groupA;
    KisGroupLayerSP groupB;
    KisPaintLayerSP red;
    bool ok = true;

    KeptWork()
    {
        const KoColorSpace *cs = image->colorSpace();
        KisPaintLayerSP background = new KisPaintLayer(image, "background", OPACITY_OPAQUE_U8);
        for (int y = 0; y < image->height(); y += 10) {
            background->paintDevice()->fill(QRect(0, y, image->width(), 10),
                                            KoColor(QColor(200, 180 - y, 40 + y, 255), cs));
        }
        image->addNode(background);

        groupA = new KisGroupLayer(image, "work A", OPACITY_OPAQUE_U8);
        image->addNode(groupA);
        red = new KisPaintLayer(image, "red", OPACITY_OPAQUE_U8);
        red->paintDevice()->fill(QRect(20, 20, 60, 40), KoColor(Qt::red, cs));
        image->addNode(red, groupA);
        KisFilterConfigurationSP blur = blurConfiguration(4);
        if (!blur) {
            ok = false;
            return;
        }
        KisFilterMaskSP blurMask = new KisFilterMask(image, "blur");
        blurMask->initSelection(red);
        blurMask->setFilter(blur);
        image->addNode(blurMask, red);
        KisTransparencyMaskSP hide = new KisTransparencyMask(image, "hide");
        hide->initSelection(red);
        hide->selection()->pixelSelection()->clear(QRect(30, 30, 20, 10));
        image->addNode(hide, red);

        KisPaintLayerSP green = new KisPaintLayer(image, "green", OPACITY_OPAQUE_U8);
        KoColor halfGreen(Qt::green, cs);
        halfGreen.setOpacity(quint8(140));
        green->paintDevice()->fill(QRect(60, 40, 50, 50), halfGreen);
        image->addNode(green, groupA);

        groupB = new KisGroupLayer(image, "work B", 180);
        image->addNode(groupB);
        KisPaintLayerSP blue = new KisPaintLayer(image, "blue", OPACITY_OPAQUE_U8);
        blue->paintDevice()->fill(QRect(90, 15, 40, 60), KoColor(Qt::blue, cs));
        image->addNode(blue, groupB);
        KisPSDLayerStyleSP style(new KisPSDLayerStyle());
        style->context()->keep_original = true;
        style->dropShadow()->setEffectEnabled(true);
        style->dropShadow()->setDistance(8);
        style->dropShadow()->setSpread(50);
        style->dropShadow()->setSize(5);
        style->dropShadow()->setNoise(0);
        style->dropShadow()->setKnocksOut(false);
        style->dropShadow()->setOpacity(80);
        style->dropShadow()->setAngle(45);
        groupB->setLayerStyle(style);

        render();
    }

    QStringList rootNames() const
    {
        QStringList names;
        for (KisNodeSP node = image->root()->firstChild(); node; node = node->nextSibling()) {
            names << node->name();
        }
        return names;
    }
};

} // namespace

void TestDocumentAgentCraft::testMergeGroupsKeepsTheProjection()
{
    KeptWork d;
    QVERIFY(d.ok);
    const QImage before = d.projection();
    QVERIFY(hasVariedPixels(before));
    const int undoBefore = d.undoCount();

    QScopedPointer<Node> a(Node::createNode(d.image, d.groupA));
    QScopedPointer<Node> b(Node::createNode(d.image, d.groupB));
    QScopedPointer<Node> merged(d.doc->mergeGroups({a.data(), b.data()}));
    QVERIFY(merged);
    QCOMPARE(merged->type(), QString("paintlayer"));
    d.settle();

    // One layer took the groups' place, above the background; the canvas is unchanged within 1 level.
    QCOMPARE(d.rootNames().size(), 2);
    QCOMPARE(d.rootNames().first(), QString("background"));
    QCOMPARE(merged->name(), d.rootNames().last());
    QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));

    // One undo step, and undoing it restores the groups, their masks and style, and the canvas.
    QCOMPARE(d.undoCount(), undoBefore + 1);
    d.undo();
    QCOMPARE(d.rootNames(), QStringList({"background", "work A", "work B"}));
    QCOMPARE(d.red->childCount(), 2u);
    QVERIFY(d.groupB->layerStyle());
    found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));

    // Redo merges again.
    d.redo();
    QCOMPARE(d.rootNames().size(), 2);
    found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestDocumentAgentCraft::testMergeOneGroupFlattensIt()
{
    KeptWork d;
    QVERIFY(d.ok);
    const QImage before = d.projection();
    const int undoBefore = d.undoCount();

    QScopedPointer<Node> b(Node::createNode(d.image, d.groupB));
    QScopedPointer<Node> merged(d.doc->mergeGroups({b.data()}));
    QVERIFY(merged);
    QCOMPARE(merged->type(), QString("paintlayer"));
    d.settle();

    QCOMPARE(d.rootNames().size(), 3);
    QCOMPARE(d.rootNames().at(1), QString("work A"));
    QCOMPARE(merged->name(), d.rootNames().at(2));
    QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));

    QCOMPARE(d.undoCount(), undoBefore + 1);
    d.undo();
    QCOMPARE(d.rootNames(), QStringList({"background", "work A", "work B"}));
    found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestDocumentAgentCraft::testMergeLeavesHiddenNodes()
{
    KeptWork d;
    QVERIFY(d.ok);
    d.groupA->setVisible(false);
    d.render();
    const QImage before = d.projection();

    QScopedPointer<Node> a(Node::createNode(d.image, d.groupA));
    QScopedPointer<Node> b(Node::createNode(d.image, d.groupB));

    // Only hidden nodes: nothing to merge, nothing changes.
    const int undoBefore = d.undoCount();
    QVERIFY(!d.doc->mergeGroups({a.data()}));
    QCOMPARE(d.undoCount(), undoBefore);

    // A hidden group in the list stays, hidden, where it was; the visible one is merged.
    QScopedPointer<Node> merged(d.doc->mergeGroups({a.data(), b.data()}));
    QVERIFY(merged);
    d.settle();
    QVERIFY(d.rootNames().contains("work A"));
    QVERIFY(!d.rootNames().contains("work B"));
    QVERIFY(!d.groupA->visible());
    QCOMPARE(d.groupA->parent(), d.image->root());
    const QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestDocumentAgentCraft::testMergeRejectsBadInput()
{
    KeptWork d;
    QVERIFY(d.ok);
    KeptWork other;
    QVERIFY(other.ok);
    const int undoBefore = d.undoCount();
    const QStringList namesBefore = d.rootNames();

    QScopedPointer<Node> a(Node::createNode(d.image, d.groupA));
    QScopedPointer<Node> red(Node::createNode(d.image, d.red));
    QScopedPointer<Node> foreign(Node::createNode(other.image, other.groupB));
    QScopedPointer<Node> mask(Node::createNode(d.image, d.red->firstChild()));
    QScopedPointer<Node> root(d.doc->rootNode());

    QVERIFY(!d.doc->mergeGroups({}));
    QVERIFY(!d.doc->mergeGroups({nullptr}));
    QVERIFY(!d.doc->mergeGroups({a.data(), foreign.data()}));
    QVERIFY(!d.doc->mergeGroups({a.data(), red.data()}));   // red is inside work A
    QVERIFY(!d.doc->mergeGroups({a.data(), mask.data()}));  // a mask is not a layer
    QVERIFY(!d.doc->mergeGroups({root.data()}));
    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
    QCOMPARE(d.rootNames(), namesBefore);
}

void TestDocumentAgentCraft::testMergeRefusesLockedOrHiddenAncestors()
{
    KeptWork d;
    QVERIFY(d.ok);
    QScopedPointer<Node> a(Node::createNode(d.image, d.groupA));
    QScopedPointer<Node> b(Node::createNode(d.image, d.groupB));
    QScopedPointer<Node> red(Node::createNode(d.image, d.red));
    const int undoBefore = d.undoCount();
    const QStringList namesBefore = d.rootNames();

    // A locked group in the list: refused, whatever else is listed.
    d.groupB->setUserLocked(true);
    QVERIFY(!d.doc->mergeGroups({a.data(), b.data()}));
    QVERIFY(!d.doc->mergeGroups({b.data()}));
    d.groupB->setUserLocked(false);

    // A listed layer inside a locked group, or inside a hidden one: refused.
    d.groupA->setUserLocked(true);
    QVERIFY(!d.doc->mergeGroups({red.data()}));
    d.groupA->setUserLocked(false);
    d.groupA->setVisible(false);
    QVERIFY(!d.doc->mergeGroups({red.data()}));
    d.groupA->setVisible(true);

    // A hidden listed node that is locked: refused too (it would be left as it is, but the call asks to merge it).
    d.groupA->setVisible(false);
    d.groupA->setUserLocked(true);
    QVERIFY(!d.doc->mergeGroups({a.data(), b.data()}));
    d.groupA->setUserLocked(false);
    d.groupA->setVisible(true);

    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
    QCOMPARE(d.rootNames(), namesBefore);
}

void TestDocumentAgentCraft::testMergeAndBakeInOneAgentMove()
{
    KeptWork d;
    QVERIFY(d.ok);
    // A layer of its own with a blur mask, beside the groups.
    const KoColorSpace *cs = d.image->colorSpace();
    KisPaintLayerSP lone = new KisPaintLayer(d.image, "lone", OPACITY_OPAQUE_U8);
    lone->paintDevice()->fill(QRect(10, 90, 30, 20), KoColor(Qt::black, cs));
    d.image->addNode(lone, d.image->root(), d.image->root()->firstChild());
    KisFilterMaskSP blurMask = new KisFilterMask(d.image, "lone blur");
    blurMask->initSelection(lone);
    blurMask->setFilter(blurConfiguration(3));
    d.image->addNode(blurMask, lone);
    d.render();

    const QImage before = d.projection();
    const QStringList namesBefore = d.rootNames();
    QByteArray lonePixels(d.image->width() * d.image->height() * lone->paintDevice()->pixelSize(), 0);
    lone->paintDevice()->readBytes(reinterpret_cast<quint8 *>(lonePixels.data()), d.image->bounds());
    const int undoBefore = d.undoCount();

    QVERIFY(d.doc->beginAgentMove("keep work"));
    QScopedPointer<FilterMask> mask(qobject_cast<FilterMask *>(Node::createNode(d.image, blurMask)));
    QVERIFY(mask);
    QVERIFY(mask->bake());
    QScopedPointer<Node> a(Node::createNode(d.image, d.groupA));
    QScopedPointer<Node> b(Node::createNode(d.image, d.groupB));
    QScopedPointer<Node> merged(d.doc->mergeGroups({a.data(), b.data()}));
    QVERIFY(merged);
    QVERIFY(d.doc->endAgentMove());
    for (int i = 0; i < 3; i++) d.settle();

    // Both are one step, the move's.
    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(d.undoCount() - 1), QString("Agent: keep work"));
    QCOMPARE(lone->childCount(), 0u);
    QCOMPARE(d.rootNames().size(), 3);
    QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));

    // One undo restores the layer tree, the mask and the pixels.
    d.undo();
    QCOMPARE(d.undoCount(), undoBefore + 1);
    QCOMPARE(d.rootNames(), namesBefore);
    QCOMPARE(lone->childCount(), 1u);
    QCOMPARE(d.red->childCount(), 2u);
    QVERIFY(d.groupB->layerStyle());
    QByteArray restored(lonePixels.size(), 0);
    lone->paintDevice()->readBytes(reinterpret_cast<quint8 *>(restored.data()), d.image->bounds());
    QVERIFY(restored == lonePixels);
    found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

KISTEST_TEMPORARY_HOME_MAIN(TestDocumentAgentCraft)
