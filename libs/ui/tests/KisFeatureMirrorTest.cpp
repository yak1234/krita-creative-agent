/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureMirrorTest.h"

#include <testui.h>
#include <KisTemporaryHomeUiTest.h>
#include <simpletest.h>

#include <QPointer>

#include <KisDocument.h>
#include <KisFeature.h>
#include <KisFeatureList.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisView.h>
#include <KisViewManager.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_node_manager.h>
#include <kis_paint_layer.h>
#include <kis_pixel_selection.h>
#include <kis_selection.h>
#include <kundo2stack.h>

namespace {

/**
 * Mirror Image runs in KisNodeManager (libs/ui), which needs a view: one main window (never shown) with one view, on
 * a 200 x 100 document with a feature "Square" at (20, 20, 40, 40). Made once, deleted in cleanupTestCase(): main
 * windows load dockers, some of which outlive a deleted window.
 */
struct MirrorView {
    QPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    KisMainWindow *mainWindow = nullptr;
    QPointer<KisView> view;

    static MirrorView *&instance()
    {
        static MirrorView *v = nullptr;
        return v;
    }

    static MirrorView *get()
    {
        if (!instance()) instance() = new MirrorView();
        return instance();
    }

    MirrorView()
    {
        kisdoc = KisPart::instance()->createDocument();
        kisdoc->setFileBatchMode(true); // never a dialog in a test
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(kisdoc->createUndoStore(), 200, 100, cs, "mirror");
        layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
        layer->paintDevice()->fill(QRect(20, 20, 40, 40), KoColor(Qt::green, cs));
        image->addNode(layer);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc, false);
        image->initialRefreshGraph();
        image->waitForDone();

        KisPixelSelectionSP mask = new KisPixelSelection();
        mask->select(QRect(20, 20, 40, 40), MAX_SELECTED);
        KisFeatureSP square = new KisFeature("Square", "test", mask);
        image->featureList()->insertFeature(square);
        square->measure(image->projection());

        mainWindow = KisPart::instance()->createMainWindow();
        view = new KisView(kisdoc, mainWindow->viewManager(), mainWindow);
        KisPart::instance()->addView(view);
        mainWindow->showView(view);
    }

    ~MirrorView()
    {
        if (view) {
            KisPart::instance()->removeView(view);
            delete view;
        }
        delete mainWindow;
        if (kisdoc) {
            KisPart::instance()->removeDocument(kisdoc, false);
            delete kisdoc;
        }
    }

    KisNodeManager *nodeManager() const
    {
        return mainWindow && mainWindow->viewManager() ? mainWindow->viewManager()->nodeManager() : nullptr;
    }

    QRect squareBounds() const
    {
        KisFeatureSP square = image->featureList()->featureByName("Square");
        return square ? square->bounds() : QRect();
    }

    QByteArray squareMask() const
    {
        KisFeatureSP square = image->featureList()->featureByName("Square");
        QByteArray bytes(200 * 100, 0);
        if (square) square->mask()->readBytes(reinterpret_cast<quint8 *>(bytes.data()), QRect(0, 0, 200, 100));
        return bytes;
    }

    void settle()
    {
        image->waitForDone();
        QCoreApplication::processEvents();
        image->waitForDone();
    }
};

} // namespace

void KisFeatureMirrorTest::cleanupTestCase()
{
    delete MirrorView::instance();
    MirrorView::instance() = nullptr;
}

void KisFeatureMirrorTest::testMirrorImageMovesMasks()
{
    MirrorView *v = MirrorView::get();
    QVERIFY(v->kisdoc && v->image && v->nodeManager());
    QCOMPARE(v->squareBounds(), QRect(20, 20, 40, 40));
    const int steps = v->kisdoc->undoStack()->count();

    // Image > Mirror Image Horizontally (the rotateimage plugin calls exactly this).
    v->nodeManager()->mirrorNode(v->image->root(), kundo2_noi18n("Mirror Image Horizontally"), Qt::Horizontal, nullptr);
    v->settle();
    QCOMPARE(v->squareBounds(), QRect(140, 20, 40, 40));
    QCOMPARE(v->kisdoc->undoStack()->count(), steps + 1);

    v->kisdoc->undoStack()->undo();
    v->settle();
    QCOMPARE(v->squareBounds(), QRect(20, 20, 40, 40));

    // Layer > Mirror All Layers Vertically, with no selection: the same path.
    v->nodeManager()->mirrorAllNodesY();
    v->settle();
    QCOMPARE(v->squareBounds(), QRect(20, 40, 40, 40));
    v->kisdoc->undoStack()->undo();
    v->settle();
    QCOMPARE(v->squareBounds(), QRect(20, 20, 40, 40));
}

void KisFeatureMirrorTest::testMirrorOfSelectedAreaOrLayerLeavesMasks()
{
    MirrorView *v = MirrorView::get();
    QVERIFY(v->kisdoc && v->image && v->nodeManager());
    const QByteArray before = v->squareMask();

    KisSelectionSP selection = new KisSelection();
    selection->pixelSelection()->select(QRect(0, 0, 100, 100), MAX_SELECTED);
    v->nodeManager()->mirrorNode(v->image->root(), kundo2_noi18n("Mirror"), Qt::Horizontal, selection);
    v->settle();
    QCOMPARE(v->squareMask(), before);

    v->nodeManager()->mirrorNode(v->layer, kundo2_noi18n("Mirror Layer"), Qt::Horizontal, nullptr);
    v->settle();
    QCOMPARE(v->squareMask(), before);
}

KISTEST_TEMPORARY_HOME_MAIN(KisFeatureMirrorTest)
