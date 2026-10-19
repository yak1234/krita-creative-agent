/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestFilterMaskBake.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include "AgentCraftTestUtils.h"

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
#include <kis_selection.h>
#include <kis_transparency_mask.h>

using namespace AgentCraftTest;

namespace {

KisFilterConfigurationSP filterConfiguration(const QString &id, int blurRadius = 0)
{
    KisFilterSP filter = KisFilterRegistry::instance()->value(id);
    if (!filter) return KisFilterConfigurationSP();
    KisFilterConfigurationSP config = filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
    if (blurRadius > 0) {
        config->setProperty("halfWidth", blurRadius);
        config->setProperty("halfHeight", blurRadius);
    }
    return config->cloneWithResourcesSnapshot();
}

/// The layer's pixels over the whole image, as raw bytes.
QByteArray pixels(KisPaintLayerSP layer, const QRect &rect)
{
    QByteArray bytes(rect.width() * rect.height() * layer->paintDevice()->pixelSize(), 0);
    layer->paintDevice()->readBytes(reinterpret_cast<quint8 *>(bytes.data()), rect);
    return bytes;
}

/// A white background and a "paint" layer with a red square, a half-transparent blue bar and a gap.
struct MaskedLayer : public UndoableDocument {
    KisPaintLayerSP layer;

    MaskedLayer()
    {
        const KoColorSpace *cs = image->colorSpace();
        KisPaintLayerSP background = new KisPaintLayer(image, "background", OPACITY_OPAQUE_U8);
        background->paintDevice()->fill(image->bounds(), KoColor(Qt::white, cs));
        image->addNode(background);

        layer = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        layer->paintDevice()->fill(QRect(30, 25, 50, 50), KoColor(Qt::red, cs));
        KoColor halfBlue(Qt::blue, cs);
        halfBlue.setOpacity(quint8(120));
        layer->paintDevice()->fill(QRect(70, 60, 60, 20), halfBlue);
        layer->paintDevice()->clear(QRect(45, 40, 8, 8));
        image->addNode(layer);
    }

    KisFilterMaskSP addFilterMask(const QString &name, KisFilterConfigurationSP config, KisNodeSP parent = nullptr)
    {
        KisFilterMaskSP mask = new KisFilterMask(image, name);
        KisLayerSP target = parent ? KisLayerSP(qobject_cast<KisLayer *>(parent.data())) : KisLayerSP(layer);
        mask->initSelection(target);
        mask->setFilter(config);
        image->addNode(mask, parent ? parent : KisNodeSP(layer));
        return mask;
    }

    FilterMask *wrap(KisFilterMaskSP mask)
    {
        return qobject_cast<FilterMask *>(Node::createNode(image, mask));
    }
};

} // namespace

void TestFilterMaskBake::testBakeBlurMask()
{
    MaskedLayer d;
    KisFilterConfigurationSP blur = filterConfiguration("blur", 6);
    QVERIFY(blur);
    KisFilterMaskSP mask = d.addFilterMask("blur", blur);
    d.render();
    const QImage before = d.projection();
    const QRect area = d.image->bounds();
    const QByteArray original = pixels(d.layer, area);
    const int undoBefore = d.undoCount();

    QScopedPointer<FilterMask> wrapper(d.wrap(mask));
    QVERIFY(wrapper);
    QVERIFY(wrapper->bake());
    d.settle();

    // The mask is gone, the layer is the same layer with blurred pixels, and the canvas did not change.
    QCOMPARE(d.layer->childCount(), 0u);
    QCOMPARE(d.layer->parent(), d.image->root());
    QCOMPARE(d.layer->name(), QString("paint"));
    QVERIFY(pixels(d.layer, area) != original);
    // The blur reached past the square's edge: its halo is in the layer now.
    QVERIFY(d.layer->paintDevice()->exactBounds().contains(QRect(26, 21, 58, 58)));
    QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));

    // One undo step brings back the mask and the original pixels.
    QCOMPARE(d.undoCount(), undoBefore + 1);
    d.undo();
    QCOMPARE(d.layer->childCount(), 1u);
    QCOMPARE(d.layer->firstChild()->name(), QString("blur"));
    QVERIFY(pixels(d.layer, area) == original);
    found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));

    d.redo();
    QCOMPARE(d.layer->childCount(), 0u);
    found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestFilterMaskBake::testBakeInvertMaskWithPartialSelection()
{
    MaskedLayer d;
    KisFilterConfigurationSP invert = filterConfiguration("invert");
    QVERIFY(invert);
    KisFilterMaskSP mask = d.addFilterMask("invert", invert);
    // The mask applies fully on the left half, half strength in a band, not at all elsewhere.
    KisPixelSelectionSP selection = mask->selection()->pixelSelection();
    selection->clear();
    selection->select(QRect(0, 0, 60, 120), MAX_SELECTED);
    selection->select(QRect(60, 0, 30, 120), 128);
    d.render();
    const QImage before = d.projection();
    const int undoBefore = d.undoCount();

    QScopedPointer<FilterMask> wrapper(d.wrap(mask));
    QVERIFY(wrapper->bake());
    d.settle();

    QCOMPARE(d.layer->childCount(), 0u);
    QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
    QCOMPARE(d.undoCount(), undoBefore + 1);

    d.undo();
    QCOMPARE(d.layer->childCount(), 1u);
    found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestFilterMaskBake::testBakeKeepsTheMasksAboveIt()
{
    MaskedLayer d;
    KisFilterConfigurationSP blur = filterConfiguration("blur", 4);
    QVERIFY(blur);
    KisFilterMaskSP mask = d.addFilterMask("blur", blur);
    // A transparency mask above the blur hides a band of the blurred result.
    KisTransparencyMaskSP hide = new KisTransparencyMask(d.image, "hide");
    hide->initSelection(d.layer);
    hide->selection()->pixelSelection()->clear(QRect(0, 50, 160, 10));
    d.image->addNode(hide, d.layer);
    d.render();
    const QImage before = d.projection();

    QScopedPointer<FilterMask> wrapper(d.wrap(mask));
    QVERIFY(wrapper->bake());
    d.settle();

    QCOMPARE(d.layer->childCount(), 1u);
    QCOMPARE(d.layer->firstChild()->name(), QString("hide"));
    const QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestFilterMaskBake::testBakeRefusesWhatWouldChangeTheLook()
{
    MaskedLayer d;
    KisFilterConfigurationSP blur = filterConfiguration("blur", 4);
    QVERIFY(blur);

    // A transparency mask below the filter mask applies first: baking the filter alone would change the look.
    KisTransparencyMaskSP hide = new KisTransparencyMask(d.image, "hide");
    hide->initSelection(d.layer);
    hide->selection()->pixelSelection()->clear(QRect(0, 50, 160, 10));
    d.image->addNode(hide, d.layer);
    KisFilterMaskSP afterHide = d.addFilterMask("blur after hide", blur);

    // A hidden filter mask, on a second layer.
    KisPaintLayerSP second = new KisPaintLayer(d.image, "second", OPACITY_OPAQUE_U8);
    second->paintDevice()->fill(QRect(10, 10, 20, 20), KoColor(Qt::black, second->colorSpace()));
    d.image->addNode(second);
    KisFilterMaskSP hidden = d.addFilterMask("hidden", blur, second);
    hidden->setVisible(false);

    // A filter mask on a group, and one on a locked layer.
    KisGroupLayerSP group = new KisGroupLayer(d.image, "group", OPACITY_OPAQUE_U8);
    d.image->addNode(group);
    KisPaintLayerSP inGroup = new KisPaintLayer(d.image, "in group", OPACITY_OPAQUE_U8);
    inGroup->paintDevice()->fill(QRect(100, 10, 20, 20), KoColor(Qt::green, inGroup->colorSpace()));
    d.image->addNode(inGroup, group);
    KisFilterMaskSP onGroup = d.addFilterMask("on group", blur, group);
    KisPaintLayerSP locked = new KisPaintLayer(d.image, "locked", OPACITY_OPAQUE_U8);
    d.image->addNode(locked);
    KisFilterMaskSP onLocked = d.addFilterMask("on locked", blur, locked);
    locked->setUserLocked(true);

    d.render();
    const QImage before = d.projection();
    const int undoBefore = d.undoCount();

    for (KisFilterMaskSP mask : {afterHide, hidden, onGroup, onLocked}) {
        QScopedPointer<FilterMask> wrapper(d.wrap(mask));
        QVERIFY2(!wrapper->bake(), qPrintable(mask->name()));
        QVERIFY2(mask->parent(), qPrintable(mask->name()));
    }
    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
    const QString found = difference(before, d.projection(), 0);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestFilterMaskBake::testBakeRefusesInLockedOrHiddenParents()
{
    MaskedLayer d;
    KisFilterConfigurationSP blur = filterConfiguration("blur", 4);
    QVERIFY(blur);
    // "paint" moves into a group, whose lock and visibility the test switches.
    KisGroupLayerSP group = new KisGroupLayer(d.image, "group", OPACITY_OPAQUE_U8);
    d.image->addNode(group);
    d.image->moveNode(d.layer, group, nullptr);
    KisFilterMaskSP mask = d.addFilterMask("blur", blur);
    d.render();
    const int undoBefore = d.undoCount();
    QScopedPointer<FilterMask> wrapper(d.wrap(mask));

    group->setUserLocked(true);
    QVERIFY(!wrapper->bake());
    group->setUserLocked(false);

    group->setVisible(false);
    QVERIFY(!wrapper->bake());
    group->setVisible(true);

    mask->setUserLocked(true);
    QVERIFY(!wrapper->bake());
    mask->setUserLocked(false);

    d.settle();
    QCOMPARE(d.undoCount(), undoBefore);
    QCOMPARE(mask->parent(), KisNodeSP(d.layer));

    // Unlocked and shown again, it bakes.
    QVERIFY(wrapper->bake());
    d.settle();
    QCOMPARE(d.layer->childCount(), 0u);
}

void TestFilterMaskBake::testBakeKeepsASmallLayerSmall()
{
    UndoableDocument d(QSize(1024, 768));
    KisPaintLayerSP layer = new KisPaintLayer(d.image, "dot", OPACITY_OPAQUE_U8);
    layer->paintDevice()->fill(QRect(500, 400, 12, 12), KoColor(Qt::red, layer->colorSpace()));
    d.image->addNode(layer);
    KisFilterMaskSP mask = new KisFilterMask(d.image, "blur");
    mask->initSelection(layer);
    mask->setFilter(filterConfiguration("blur", 3));
    d.image->addNode(mask, layer);
    d.render();
    const QImage before = d.projection();

    QScopedPointer<FilterMask> wrapper(qobject_cast<FilterMask *>(Node::createNode(d.image, mask)));
    QVERIFY(wrapper->bake());
    d.settle();

    // The blur's reach, not the whole canvas: the layer keeps only the tiles around the dot.
    const QRect reach = mask->changeRect(QRect(500, 400, 12, 12), KisNode::N_ABOVE_FILTHY);
    const QRect exact = layer->paintDevice()->exactBounds();
    const QRect extent = layer->paintDevice()->extent();
    QVERIFY2(reach.contains(exact), qPrintable(QString("exact bounds %1,%2 %3x%4")
                                                   .arg(exact.x()).arg(exact.y()).arg(exact.width()).arg(exact.height())));
    QVERIFY2(extent.width() <= 128 && extent.height() <= 128,
             qPrintable(QString("extent %1,%2 %3x%4").arg(extent.x()).arg(extent.y()).arg(extent.width()).arg(extent.height())));
    const QString found = difference(before, d.projection(), 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

KISTEST_TEMPORARY_HOME_MAIN(TestFilterMaskBake)
